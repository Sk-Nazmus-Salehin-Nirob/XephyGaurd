"""Pure decision logic for the XephyGuard proxy addon (no mitmproxy imports, fully unit-testable)."""
from __future__ import annotations

import ipaddress
import itertools
import json
import logging
import os
import pathlib
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .domains import DomainSet, InspectHosts, PathRules
from .state import State

log = logging.getLogger("xg-proxy")

# AI-endpoint signatures (I-PROXY-21). They live in data/network/proxy.yaml (google_search_hosts,
# google_ai_paths, search_css_hosts) and reach the proxy in state.json -> proxy.json `google`
# (search_hosts, ai_paths, css_hosts). These are only the fallback for a document that lacks them;
# a test keeps them equal to the YAML.
SEARCH_AI_DEFAULTS: dict[str, list[str]] = {
    "search_hosts": [r"^(?:www\.|encrypted\.)?google\.[a-z]{2,6}(?:\.[a-z]{2})?$"],
    "ai_paths": ["/async/folwr"],
    "css_hosts": ["bing.com"],
}
GOOGLE_HOST = re.compile(SEARCH_AI_DEFAULTS["search_hosts"][0])
STYLE_NONCE_RE = re.compile(r"<(?:style|script)[^>]*\bnonce=[\"']([^\"']+)[\"']", re.IGNORECASE)


UPSTREAM_PORTS = frozenset({80, 443})


def refused_destination(host: str, port: int, own_ips: tuple[str, ...] = ()) -> str | None:
    """Why an upstream connection to host:port must be refused, or None when it may go ahead.

    Applies to every client and both listeners: only web ports, never loopback, link-local,
    unspecified, multicast or the CCC's own addresses. `host` that is not an IP literal is only
    checked for localhost names; the caller resolves other names and checks each address.
    """
    if port not in UPSTREAM_PORTS:
        return f"port {port} not allowed"
    h = (host or "").strip().strip("[]").rstrip(".").lower()
    if h == "localhost" or h.endswith(".localhost"):
        return "loopback destination"
    try:
        ip = ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback destination"
    if ip.is_link_local:
        return "link-local destination"
    if ip.is_unspecified or ip.is_multicast:
        return "invalid destination"
    for own in own_ips:
        try:
            if ip == ipaddress.ip_address(own):
                return "CCC address"
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class SearchAi:
    """Where the Google/Bing AI suppression acts: search hosts (regexes on the lower-case host; udm=14
    rewrite, AI paths, CSS), AI paths on them answered 204 (prefixes, query ignored), and other hosts
    that get the hide_selectors CSS (the entry or a subdomain of it)."""
    search_hosts: tuple[re.Pattern[str], ...] = (GOOGLE_HOST,)
    ai_paths: tuple[str, ...] = tuple(SEARCH_AI_DEFAULTS["ai_paths"])
    css_hosts: tuple[str, ...] = tuple(SEARCH_AI_DEFAULTS["css_hosts"])

    def is_search_host(self, host: str | None) -> bool:
        h = (host or "").lower()
        return any(p.match(h) for p in self.search_hosts)

    def is_ai_path(self, host: str | None, path: str) -> bool:
        clean = path.split("?", 1)[0]
        return self.is_search_host(host) and any(clean.startswith(p) for p in self.ai_paths)

    def wants_css(self, host: str | None) -> bool:
        h = (host or "").lower()
        # the entry itself or a subdomain of it, never a look-alike such as notbing.com (I-PROXY-23)
        return self.is_search_host(h) or any(h == e or h.endswith("." + e) for e in self.css_hosts)


def search_ai_signatures(google: dict[str, Any]) -> SearchAi:
    """SearchAi from the policy's `google` object. A key that is missing, not a list or left empty
    after dropping bad entries (non-string, blank, a regex that doesn't compile; each logged) uses
    SEARCH_AI_DEFAULTS, so a document from an older CCC keeps today's behaviour."""
    out: dict[str, list[Any]] = {}
    for key, default in SEARCH_AI_DEFAULTS.items():
        raw = google.get(key)
        if raw is not None and not isinstance(raw, list):
            log.warning("google.%s must be a list, not %s; using the built-in list", key, type(raw).__name__)
            raw = None
        kept: list[Any] = []
        for e in raw or []:
            if not isinstance(e, str) or not e.strip():
                log.warning("google.%s: skipping %r", key, e)
                continue
            if key == "search_hosts":
                try:
                    kept.append(re.compile(e.strip()))
                except re.error as err:
                    log.warning("google.%s: skipping %r (%s)", key, e, err)
            else:
                kept.append(e.strip().lower() if key == "css_hosts" else e.strip())
        if not kept:
            kept = [re.compile(x) for x in default] if key == "search_hosts" else list(default)
        out[key] = kept
    return SearchAi(tuple(out["search_hosts"]), tuple(out["ai_paths"]), tuple(out["css_hosts"]))


@dataclass
class TlsDecision:
    action: str               # "block" | "inspect" | "pass"
    category: str | None = None
    matched: str | None = None
    reason: str = ""


NO_POLICY = "no valid proxy policy loaded yet"
_LOADS = itertools.count(1)  # PolicyCache.generation: unique per successful load, across instances


class PolicyCache:
    """Hot-reloads proxy.json (checked at most every `interval` seconds). A document that can't be
    read, parsed or validated never replaces the last good policy (I-PROXY-15). Until one valid
    policy has loaded (`loaded`), every TLS and HTTP decision is "block" (fail closed)."""

    def __init__(self, path: str | pathlib.Path, interval: float = 2.0) -> None:
        self.path = pathlib.Path(path)
        self.interval = interval
        self._mtime = 0.0
        self._failed_mtime: float | None = None  # mtime of a document that failed to load (logged once)
        self._checked = 0.0
        self.loaded = False
        self.generation = 0     # changes on every successful load (live connections are rechecked, I-PROXY-22)
        self.state = State()
        self._blocked: dict[str | None, DomainSet] = {}
        self._inspect = InspectHosts()
        self._ai_doms = DomainSet()
        self._ide_doms = DomainSet()
        self._ai_paths = PathRules()
        self._ide_paths = PathRules()
        self.search_ai = SearchAi()
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked < self.interval:
            return
        self._checked = now
        try:
            m = self.path.stat().st_mtime
        except OSError:
            return  # not written yet (or unreadable dir): keep the current policy, check again later
        if not force and m in (self._mtime, self._failed_mtime):
            return
        try:
            text = self.path.read_text()
        except OSError as e:
            # e.g. replaced between stat and read: transient, so retried at the next check
            log.warning("proxy policy %s unreadable, keeping previous: %s", self.path, e)
            return
        try:
            state = State.from_dict(json.loads(text))
            # build every derived view before swapping, so a failure leaves no half-updated policy
            derived = (InspectHosts.of(state.inspect_hosts),
                       DomainSet.of(state.categories.get("ai", [])), DomainSet.of(state.categories.get("ide", [])),
                       PathRules.of(state.path_rules.get("ai", [])), PathRules.of(state.path_rules.get("ide", [])),
                       search_ai_signatures(state.google))
        except Exception as e:  # ValueError, TypeError, AttributeError, KeyError, RecursionError, ...
            if m != self._failed_mtime:
                log.error("proxy policy %s invalid, keeping %s: %s: %s", self.path,
                          f"v{self.state.version}" if self.loaded else "fail-closed (no policy loaded yet)",
                          type(e).__name__, e)
            self._failed_mtime = m
            return
        self.state = state
        (self._inspect, self._ai_doms, self._ide_doms, self._ai_paths, self._ide_paths,
         self.search_ai) = derived
        self._blocked = {}
        self._mtime = m
        self._failed_mtime = None
        self.loaded = True
        self.generation = next(_LOADS)
        log.info("proxy policy v%s loaded", self.state.version)

    def blocked(self, group: str | None) -> DomainSet:
        if group not in self._blocked:
            self._blocked[group] = self.state.blocked_domains_for_group(group)
        return self._blocked[group]

    def match_ai_domain(self, host: str | None) -> tuple[str, str] | None:
        """Returns (matched_domain, category) when host belongs to tracked AI or IDE categories."""
        if not host:
            return None
        if m := self._ai_doms.matches(host):
            return m, "ai"
        if m := self._ide_doms.matches(host):
            return m, "ide"
        return None

    def match_ai_path(self, host: str | None, path: str) -> tuple[str, str] | None:
        """Returns (matched_rule, category) when host+path matches tracked AI or IDE path rules."""
        if not host:
            return None
        if r := self._ai_paths.matches(host, path):
            return r, "ai"
        if r := self._ide_paths.matches(host, path):
            return r, "ide"
        return None

    # -- decisions ------------------------------------------------------------------------------
    def decide_tls(self, client_ip: str | None, sni: str | None) -> TlsDecision:
        self.reload()
        if not self.loaded:
            return TlsDecision("block", "no_policy", sni, NO_POLICY)
        group = self.state.group_of(client_ip)
        if group == "isolated":
            return TlsDecision("block", "isolated", sni, "PC is isolated")
        if not sni:
            if group == "test":
                return TlsDecision("block", "no_sni", None, "TLS without SNI is not allowed in Test mode")
            return TlsDecision("pass")
        hit = self.blocked(group).matches(sni)
        if hit:
            return TlsDecision("block", self.state.category_of(hit), hit, "domain blocklist")
        if (
            group in ("test", "block_ai")
            or (self.wants_google_rewrite(client_ip) and self.search_ai.is_search_host(sni))
        ) and self._inspect.matches(sni):
            return TlsDecision("inspect", reason="selective inspection host")
        return TlsDecision("pass")

    def decide_http(self, client_ip: str | None, host: str, path: str) -> TlsDecision:
        """For plaintext HTTP and for inspected HTTPS requests."""
        self.reload()
        if not self.loaded:
            return TlsDecision("block", "no_policy", host, NO_POLICY)
        group = self.state.group_of(client_ip)
        if group == "isolated":
            return TlsDecision("block", "isolated", host, "PC is isolated")
        hit = self.blocked(group).matches(host)
        if hit:
            return TlsDecision("block", self.state.category_of(hit), hit, "domain blocklist")
        if m := self.state.path_rule_match(group, host, path):
            return TlsDecision("block", m[1], m[0], "path rule")  # category of the matched rule (I-PROXY-24)
        return TlsDecision("pass")

    def recheck_live(self, live: dict[str, tuple[str | None, str | None, str]]) -> list[str]:
        """Ids of live TLS connections ({id: (client_ip, sni, action at ClientHello)}) whose decision
        tightened under the current policy (I-PROXY-22): now "block", or now "inspect" while passed
        through. Closing them makes the client reconnect and get the new decision. A decision that
        loosened (e.g. inspect -> pass after a session ends) keeps its connection."""
        out = []
        for cid, (ip, sni, old) in list(live.items()):
            new = self.decide_tls(ip, sni).action
            if new != old and new in ("block", "inspect"):
                out.append(cid)
        return out

    def records_observed(self, client_ip: str | None) -> bool:
        """`observed` AI/IDE events are recorded only with `log_urls` on and for a PC in a running
        session (I-PROXY-10, ETHICS.md "Visited hosts/paths of allowed sites")."""
        return bool(self.state.log_urls.get("enabled")) and self.state.in_session(client_ip)

    def wants_google_rewrite(self, client_ip: str | None) -> bool:
        if not client_ip:
            return False
        ip = client_ip.removeprefix("::ffff:")
        group = self.state.group_of(ip)
        if group in ("exempt", "isolated"):
            return False
        if "udm14_clients" in self.state.google and isinstance(self.state.google.get("udm14_clients"), list):
            if ip in self.state.google["udm14_clients"]:
                return True
            return group in ("test", "block_ai") and bool(self.state.google.get("force_udm14", False))
        return group in ("test", "block_ai") and bool(self.state.google.get("force_udm14", True))


def loggable_path(path: str, limit: int = 512) -> str:
    """Path of a request as shipped in events: never the query string or fragment, which hold typed
    text such as search terms (I-PROXY-9, PRIVACY). The `log_urls.query` setting no longer widens this."""
    return path.split("?", 1)[0].split("#", 1)[0][:limit] or "/"


def observed_path(path: str) -> str:
    """Path of an `observed` event: only the first segment (`/search/<query-slug>` -> `/search`),
    since some AI sites put the prompt text in the path (I-PROXY-10); never the query or fragment."""
    first = loggable_path(path).lstrip("/").split("/", 1)[0]
    return "/" + first[:255]


def google_search_rewrite(host: str, path: str, query: list[tuple[str, str]],
                          sig: SearchAi | None = None) -> list[tuple[str, str]] | None:
    """Returns a new query list with udm=14 ("Web" results, no AI Overview) or None if unchanged.

    - Only /search on a search host (`sig`, default google.<tld>).
    - Leaves other verticals alone (tbm=isch images, udm=2 images, ...), except udm=50 (AI Mode)
      which is forced to 14.
    """
    if not (sig or SearchAi()).is_search_host(host) or path.split("?", 1)[0] != "/search":
        return None
    keys = {k for k, _ in query}
    if "tbm" in keys:
        return None
    udm = [v for k, v in query if k == "udm"]
    if udm and udm[0] not in ("50", "14"):
        return None
    has_aep = "aep" in keys
    if udm and udm[0] == "14" and not has_aep:
        return None
    new = [(k, v) for k, v in query if k not in ("udm", "aep")]
    new.append(("udm", "14"))
    return new


def extract_nonce(html: str) -> str:
    m = STYLE_NONCE_RE.search(html or "")
    return m.group(1) if m else ""


# Characters a hide selector may use: names, #id, .class, [attr op "value"], combinators, :pseudo(...).
# Nothing that can end the rule or the <style> element or start an at-rule or comment: no { } ; @ <
# or backslash, and no /* or */ (a / alone may appear in a quoted value such as [href^='https://']).
SELECTOR_RE = re.compile(r"""[A-Za-z0-9_\-#.:\[\]=*>+~,()|^$"'/ ]+""")
SELECTOR_MAX = 256


def valid_selector(s: object) -> bool:
    """True when `s` is safe to put in front of `{display:none!important}` (I-PROXY-26): allowed
    characters only, no comment, balanced quotes, brackets and parentheses, at most SELECTOR_MAX characters."""
    if not isinstance(s, str) or not s.strip() or len(s) > SELECTOR_MAX or not SELECTOR_RE.fullmatch(s):
        return False
    if "/*" in s or "*/" in s:
        return False
    if s.count('"') % 2 or s.count("'") % 2:
        return False
    depth = {"[": 0, "(": 0}
    for ch in s:
        if ch in "[(":
            depth[ch] += 1
        elif ch in "])":
            k = "[" if ch == "]" else "("
            depth[k] -= 1
            if depth[k] < 0:
                return False
    return not any(depth.values())


def hide_css(selectors: list[str], nonce: str = "") -> str:
    """Selectors that fail valid_selector are left out; nothing is injected when none is left."""
    sel = ",".join(s.strip() for s in selectors if valid_selector(s))
    if not sel:
        return ""
    safe_nonce = re.sub(r"[^A-Za-z0-9+/=_-]", "", nonce or "")
    nonce_attr = f' nonce="{safe_nonce}"' if safe_nonce else ""
    return f'<style id="xephyguard"{nonce_attr}>{sel}{{display:none!important}}</style>'


def inject_css(html: str, selectors: list[str], nonce: str = "") -> str | None:
    eff_nonce = nonce or extract_nonce(html)
    css = hide_css(selectors, nonce=eff_nonce)
    if not css:
        return None
    idx = html.lower().find("</head>")
    if idx < 0:
        return None
    return html[:idx] + css + html[idx:]


def relax_style_csp(csp_value: str) -> str:
    """Allows injected inline fallback <style> under strict style-src CSP headers."""
    parts = [p.strip() for p in csp_value.split(";") if p.strip()]
    out = []
    for p in parts:
        tokens = p.split()
        directive = tokens[0].lower() if tokens else ""
        if directive in ("style-src", "style-src-elem"):
            # CSP ignores 'unsafe-inline' whenever any 'nonce-*' or 'sha*-*' token remains.
            kept = [t for t in tokens if not re.match(r"^'(?:nonce|sha256|sha384|sha512)-[^']+'$", t, re.I)]
            if "'unsafe-inline'" not in [t.lower() for t in kept]:
                kept.append("'unsafe-inline'")
            p = " ".join(kept)
        out.append(p)
    return "; ".join(out)


BLOCK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Blocked by XephyGuard</title>
<style>body{{font-family:system-ui,sans-serif;background:#f5f5f5;color:#222;display:flex;align-items:center;
justify-content:center;height:100vh;margin:0}}main{{background:#fff;padding:2rem 2.5rem;border-radius:12px;
max-width:520px;box-shadow:0 2px 12px rgba(0,0,0,.08)}}h1{{font-size:1.3rem;margin-top:0}}code{{background:#eee;
padding:2px 6px;border-radius:4px}}</style></head><body><main><h1>This site is not available right now</h1>
<p><code>{host}</code> is blocked on lab computers during the current session ({reason}).</p>
<p>The attempt was recorded. If you think this is a mistake, ask your instructor.</p>
<p style="color:#777;font-size:.85rem">XephyGuard &middot; lab AI-use policy</p></main></body></html>"""


def block_page(host: str, reason: str) -> str:
    esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return BLOCK_PAGE.format(host=esc(host), reason=esc(reason))


TOKEN_ENV = "XG_INTERNAL_TOKEN"


EVENT_HOST_MAX = 255  # NetEventsController: events.*.host max:255
EVENT_PATH_MAX = 512  # events.*.path max:512
EVENT_BATCH_MAX = 500  # events per POST, live and replayed (NetEventsController allows max:1000)

# Spill file for batches the CCC did not take (I-PROXY-12). It holds raw network events (client IP,
# host, path), so it follows the raw-event retention of docs/ETHICS.md "Retention and access":
# "Raw events ... deleted after the configured period (default 140 days)". The server reads the
# same default from env XG_RETENTION_RAW_DAYS (server/config/xephyguard.php); the proxy reads that
# env too, clamped to the server's allowed 7..1095 days.
RETENTION_ENV = "XG_RETENTION_RAW_DAYS"
RETENTION_DEFAULT_DAYS = 140
RETENTION_MIN_DAYS, RETENTION_MAX_DAYS = 7, 1095
SPILL_MAX_BYTES = 8 * 1024 * 1024  # live file rotated to .1 at this size
SPILL_KEEP = 3                      # rotated files kept (.1 newest .. .3 oldest); total <= 4 x 8 MiB
REPLAY_MAX_BATCHES = 20             # replayed per successful POST, so live events are not held up
PURGE_INTERVAL_S = 3600.0
# a batch the CCC refuses as invalid is never accepted later: it is split to find the bad events,
# which are dropped, instead of being spilled and replayed forever
REJECTED_STATUS = frozenset({400, 413, 422})

ALLOWED_DEDUP_S = 60.0   # one `allowed` SNI event per (client, host) per minute (I-PROXY-30)
OBSERVED_DEDUP_S = 30.0
DEDUP_MAX_KEYS = 8192    # per dedup table; older keys are pruned beyond this
STATS_INTERVAL_S = 60.0  # proxy-stats.json next to the spill file is rewritten this often


def retention_days() -> int:
    raw = os.environ.get(RETENTION_ENV, "").strip()
    if not raw:
        return RETENTION_DEFAULT_DAYS
    try:
        days = int(raw)
    except ValueError:
        log.warning("%s=%r is not a number; using %d days", RETENTION_ENV, raw, RETENTION_DEFAULT_DAYS)
        return RETENTION_DEFAULT_DAYS
    return min(max(days, RETENTION_MIN_DAYS), RETENTION_MAX_DAYS)


def event_text(value: Any, limit: int) -> Any:
    """A client-controlled event string as the CCC accepts it: characters that are not printable
    (control characters, the surrogates mitmproxy uses for undecodable bytes, which JSON can't carry
    to PHP) are dropped, then the rest is cut to `limit` characters. Non-strings are left alone."""
    if not isinstance(value, str):
        return value
    return "".join(ch for ch in value if ch.isprintable())[:limit]


class EventShipper:
    """Batches network events and POSTs them to the CCC; falls back to a JSONL file.

    The bearer token comes from env XG_INTERNAL_TOKEN (I-PROXY-13); `events_token` in proxy.json is
    only read when the env var is unset (a proxy.json from an older generator), with a warning."""

    def __init__(self, cache: PolicyCache, fallback: str = "/var/log/xephyguard/proxy-events.jsonl") -> None:
        self.cache = cache
        self.fallback = fallback
        self.q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=50000)
        self._seen_lock = threading.Lock()
        self._seen_observed: dict[tuple[str | None, str], float] = {}
        self._seen_allowed: dict[tuple[str | None, str], float] = {}
        self._stop = threading.Event()
        self._warned_token = False
        # spilled: kept for replay; replayed: delivered later; rejected: refused by the CCC as
        # invalid and dropped; purged: past retention; spill_lost: could not be kept;
        # queue_full: dropped by emit because the queue was full; deduped_allowed/_observed:
        # suppressed as repeats within the dedup window. Written to proxy-stats.json (stats_path).
        self.stats: dict[str, int] = {"spilled": 0, "replayed": 0, "rejected": 0, "purged": 0, "spill_lost": 0,
                                      "queue_full": 0, "deduped_allowed": 0, "deduped_observed": 0}
        self._logged_queue_full = 0
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _first_in_window(self, seen: dict[tuple[str | None, str], float], counter: str,
                         client_ip: str | None, name: str, window_s: float) -> bool:
        """True for the first (client_ip, name) within window_s (and records it); a repeat is
        counted in stats[counter] and returns False."""
        ip = client_ip.removeprefix("::ffff:") if client_ip else None
        now = time.monotonic()
        key = (ip, name)
        with self._seen_lock:
            last = seen.get(key)
            if last is not None and now - last < window_s:
                self.stats[counter] += 1
                return False
            if len(seen) >= DEDUP_MAX_KEYS:
                cutoff = now - window_s
                for k in [k for k, v in seen.items() if v <= cutoff]:
                    del seen[k]
                if len(seen) >= DEDUP_MAX_KEYS:  # all still inside the window: keep the newest half
                    for k, _ in sorted(seen.items(), key=lambda kv: kv[1])[:len(seen) // 2]:
                        del seen[k]
            seen[key] = now
            return True

    def should_emit_observed(self, client_ip: str | None, matched: str, window_s: float = OBSERVED_DEDUP_S) -> bool:
        """Deduplicates observed AI/IDE events per (client_ip, matched_domain) within window_s."""
        return self._first_in_window(self._seen_observed, "deduped_observed", client_ip, matched, window_s)

    def should_emit_allowed(self, client_ip: str | None, host: str, window_s: float = ALLOWED_DEDUP_S) -> bool:
        """Deduplicates `log_urls` allowed SNI events per (client_ip, host) within window_s; a
        browser opens many TLS connections per site, each would be one event (I-PROXY-30)."""
        name = (host or "").strip().rstrip(".").lower()
        return self._first_in_window(self._seen_allowed, "deduped_allowed", client_ip, name, window_s)

    def emit(self, **ev: Any) -> None:
        if isinstance(ev.get("client_ip"), str):
            ev["client_ip"] = ev["client_ip"].removeprefix("::ffff:")
        # host is the client's Host header or SNI: one over-long or unencodable value would get the
        # whole batch rejected by the CCC (host max:255), hiding other PCs' events (I-PROXY-11)
        for key, limit in (("host", EVENT_HOST_MAX), ("path", EVENT_PATH_MAX)):
            if key in ev:
                ev[key] = event_text(ev[key], limit)
        ev.setdefault("ts", int(time.time() * 1000))
        try:
            self.q.put_nowait(ev)
        except queue.Full:
            with self._seen_lock:
                self.stats["queue_full"] += 1

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=3)
        self.write_stats()

    @property
    def stats_path(self) -> pathlib.Path:
        return pathlib.Path(self.fallback).with_name("proxy-stats.json")

    def write_stats(self) -> None:
        """Writes the counters to proxy-stats.json (atomic, counts only, no hosts or IPs) and logs
        events dropped because the queue was full since the last write."""
        with self._seen_lock:
            snap = dict(self.stats)
        snap["queued"] = self.q.qsize()
        snap["updated_at"] = int(time.time())
        lost = snap["queue_full"] - self._logged_queue_full
        if lost > 0:
            log.warning("%d events dropped: event queue full (%d in total)", lost, snap["queue_full"])
            self._logged_queue_full = snap["queue_full"]
        f = self.stats_path
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f.name + ".tmp")
            tmp.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(tmp, 0o644)
            tmp.replace(f)
        except OSError as e:
            log.warning("cannot write %s (%s)", f, e)

    def _run(self) -> None:
        next_purge = 0.0
        next_stats = time.monotonic() + STATS_INTERVAL_S
        while not self._stop.is_set():
            if time.monotonic() >= next_purge:
                self.purge_spill()
                next_purge = time.monotonic() + PURGE_INTERVAL_S
            if time.monotonic() >= next_stats:
                self.write_stats()
                next_stats = time.monotonic() + STATS_INTERVAL_S
            batch: list[dict[str, Any]] = []
            try:
                batch.append(self.q.get(timeout=1.0))
                while len(batch) < EVENT_BATCH_MAX:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            if batch:
                self._ship(batch)

    def token(self) -> str:
        env = os.environ.get(TOKEN_ENV, "").strip()
        if env:
            return env
        legacy = self.cache.state.events_token
        if not self._warned_token:
            self._warned_token = True
            if legacy:
                log.warning("%s is not set; using events_token from %s (older generator)", TOKEN_ENV, self.cache.path)
            else:
                log.warning("%s is not set; event shipping will be refused by the CCC", TOKEN_ENV)
        return legacy if isinstance(legacy, str) else ""

    def _post(self, batch: list[dict[str, Any]]) -> int | None:
        """POSTs one batch; the HTTP status, or None when the CCC could not be reached."""
        url, token = self.cache.state.events_url, self.token()
        if not url:
            return None
        req = urllib.request.Request(url, data=json.dumps({"events": batch}).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return int(r.status)
        except urllib.error.HTTPError as e:
            return int(e.code)
        except Exception as e:  # noqa: BLE001 - network errors must never break the proxy
            log.warning("event shipping failed (%s)", e)
            return None

    def _send(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sends `batch`; returns the events still to keep (the CCC unreachable or failing). A batch
        refused as invalid (REJECTED_STATUS) is halved until the bad events are found; those are
        dropped and counted, the others are sent."""
        if not batch:
            return []
        status = self._post(batch)
        if status is not None and 200 <= status < 300:
            return []
        if status in REJECTED_STATUS:
            if len(batch) == 1:
                self.stats["rejected"] += 1
                # layer/action only: the log is not covered by the retention purge
                log.warning("CCC refused a %s/%s event (HTTP %s); dropped", batch[0].get("layer"),
                            batch[0].get("action"), status)
                return []
            mid = len(batch) // 2
            return self._send(batch[:mid]) + self._send(batch[mid:])
        if status is not None:
            log.warning("event shipping failed (HTTP %s)", status)
        return batch

    def _ship(self, batch: list[dict[str, Any]]) -> None:
        unsent = self._send(batch)
        if unsent:
            self._spill(unsent)
        elif self.cache.state.events_url:
            self.replay_spill()

    # spill file: only the shipper thread reads or writes it, so no lock is needed

    def _spill_files(self) -> list[pathlib.Path]:
        """Existing spill files, oldest first (.3, .2, .1, then the live file)."""
        live = pathlib.Path(self.fallback)
        names = [live.with_name(f"{live.name}.{i}") for i in range(SPILL_KEEP, 0, -1)] + [live]
        return [f for f in names if f.exists()]

    def _rotate(self) -> None:
        live = pathlib.Path(self.fallback)
        oldest = live.with_name(f"{live.name}.{SPILL_KEEP}")
        if oldest.exists():
            with oldest.open("rb") as fh:
                lost = sum(1 for _ in fh)
            self.stats["spill_lost"] += lost
            log.warning("spill files full; dropping %s (%d events)", oldest, lost)
            oldest.unlink()
        for i in range(SPILL_KEEP - 1, 0, -1):
            f = live.with_name(f"{live.name}.{i}")
            if f.exists():
                f.replace(live.with_name(f"{live.name}.{i + 1}"))
        live.replace(live.with_name(f"{live.name}.1"))

    def _spill(self, batch: list[dict[str, Any]]) -> None:
        live = pathlib.Path(self.fallback)
        log.warning("%d events kept in %s for replay", len(batch), live)
        try:
            live.parent.mkdir(parents=True, exist_ok=True)
            if live.exists() and live.stat().st_size >= SPILL_MAX_BYTES:
                self._rotate()
            with live.open("a", encoding="utf-8") as f:
                for ev in batch:
                    f.write(json.dumps(ev) + "\n")
            self.stats["spilled"] += len(batch)
        except OSError as e:
            log.warning("cannot write %s (%s); %d events lost", live, e, len(batch))
            self.stats["spill_lost"] += len(batch)

    def _cutoff_ms(self) -> int:
        return int((time.time() - retention_days() * 86400) * 1000)

    def _read_spill(self, f: pathlib.Path, cutoff_ms: int) -> tuple[list[dict[str, Any]], int]:
        """The events in `f` still inside retention, and how many lines were dropped (expired,
        not JSON, or without an integer ts)."""
        keep: list[dict[str, Any]] = []
        dropped = 0
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                dropped += 1
                continue
            ts = ev.get("ts") if isinstance(ev, dict) else None
            if not isinstance(ts, int) or isinstance(ts, bool) or ts < cutoff_ms:
                dropped += 1
                continue
            keep.append(ev)
        return keep, dropped

    def _rewrite(self, f: pathlib.Path, events: list[dict[str, Any]]) -> None:
        if not events:
            f.unlink(missing_ok=True)
            return
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text("".join(json.dumps(ev) + "\n" for ev in events), encoding="utf-8")
        tmp.replace(f)

    def purge_spill(self) -> int:
        """Deletes spilled events older than the retention period, also while the CCC stays
        unreachable (they would escape the CCC's retention purge otherwise). Returns how many."""
        cutoff_ms = self._cutoff_ms()
        purged = 0
        for f in self._spill_files():
            try:
                if f.stat().st_mtime * 1000 < cutoff_ms:  # last written before the cutoff: all expired
                    with f.open("rb") as fh:
                        n = sum(1 for _ in fh)
                    f.unlink()
                else:
                    keep, n = self._read_spill(f, cutoff_ms)
                    if n:
                        self._rewrite(f, keep)
            except OSError as e:
                log.warning("cannot purge %s (%s)", f, e)
                continue
            purged += n
        if purged:
            self.stats["purged"] += purged
            log.info("purged %d spilled events older than %d days", purged, retention_days())
        return purged

    def replay_spill(self, max_batches: int = REPLAY_MAX_BATCHES) -> int:
        """Re-sends spilled events, oldest file and oldest event first, in batches of at most
        EVENT_BATCH_MAX. Stops at the first batch the CCC does not take (it stays in the file, the
        next successful POST tries again) or after `max_batches`. Expired lines are dropped on the
        way. Returns how many events were delivered."""
        cutoff_ms = self._cutoff_ms()
        sent = 0
        batches = 0
        for f in self._spill_files():
            try:
                events, expired = self._read_spill(f, cutoff_ms)
            except OSError as e:
                log.warning("cannot read %s (%s)", f, e)
                return sent
            self.stats["purged"] += expired
            i = 0
            while i < len(events):
                if batches >= max_batches:
                    self._rewrite_quiet(f, events[i:])
                    return sent
                chunk = events[i:i + EVENT_BATCH_MAX]
                batches += 1
                unsent = self._send(chunk)
                if unsent:
                    self._rewrite_quiet(f, unsent + events[i + len(chunk):])
                    return sent
                sent += len(chunk)
                self.stats["replayed"] += len(chunk)
                i += len(chunk)
            self._rewrite_quiet(f, [])
        if sent:
            log.info("replayed %d spilled events", sent)
        return sent

    def _rewrite_quiet(self, f: pathlib.Path, events: list[dict[str, Any]]) -> None:
        try:
            self._rewrite(f, events)
        except OSError as e:
            log.warning("cannot rewrite %s (%s)", f, e)
