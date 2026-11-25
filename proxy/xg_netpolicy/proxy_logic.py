"""Pure decision logic for the XephyGuard proxy addon (no mitmproxy imports, fully unit-testable)."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import pathlib
import queue
import re
import threading
import time
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
    that get the hide_selectors CSS (host ends with the entry)."""
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
        return self.is_search_host(h) or any(h.endswith(e) for e in self.css_hosts)


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
        rule = self.state.path_rules_for_group(group).matches(host, path)
        if rule:
            return TlsDecision("block", "ai", rule, "path rule")
        return TlsDecision("pass")

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
        self._stop = threading.Event()
        self._warned_token = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def should_emit_observed(self, client_ip: str | None, matched: str, window_s: float = 30.0) -> bool:
        """Deduplicates observed AI/IDE events per (client_ip, matched_domain) within window_s."""
        ip = client_ip.removeprefix("::ffff:") if client_ip else None
        now = time.monotonic()
        key = (ip, matched)
        with self._seen_lock:
            last = self._seen_observed.get(key)
            if last is not None and now - last < window_s:
                return False
            if len(self._seen_observed) > 4096:
                cutoff = now - window_s
                self._seen_observed = {k: v for k, v in self._seen_observed.items() if v > cutoff}
            self._seen_observed[key] = now
            return True

    def emit(self, **ev: Any) -> None:
        if isinstance(ev.get("client_ip"), str):
            ev["client_ip"] = ev["client_ip"].removeprefix("::ffff:")
        ev.setdefault("ts", int(time.time() * 1000))
        try:
            self.q.put_nowait(ev)
        except queue.Full:
            pass

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            batch: list[dict[str, Any]] = []
            try:
                batch.append(self.q.get(timeout=1.0))
                while len(batch) < 500:
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

    def _ship(self, batch: list[dict[str, Any]]) -> None:
        url, token = self.cache.state.events_url, self.token()
        if url:
            try:
                req = urllib.request.Request(url, data=json.dumps({"events": batch}).encode(), method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    if 200 <= r.status < 300:
                        return
            except Exception as e:  # noqa: BLE001 - network errors must never break the proxy
                log.warning("event shipping failed (%s); writing to %s", e, self.fallback)
        try:
            os.makedirs(os.path.dirname(self.fallback), exist_ok=True)
            with open(self.fallback, "a") as f:
                for ev in batch:
                    f.write(json.dumps(ev) + "\n")
        except OSError:
            pass
