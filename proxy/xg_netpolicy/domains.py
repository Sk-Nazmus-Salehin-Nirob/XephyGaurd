"""Domain and path matching shared by the DNS generator and the proxy addon."""
from __future__ import annotations

import ipaddress
import posixpath
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import unquote

_LABEL = re.compile(r"^[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?$")


def normalize_domain(d: str) -> str | None:
    """Lowercase, strip scheme/port/trailing dot/wildcards. Returns None if invalid."""
    d = d.strip().lower()
    if not d or d.startswith("#"):
        return None
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split(":")[0].strip(".")
    if d.startswith("*."):
        d = d[2:]
    if not d or "." not in d:
        return None
    try:
        ipaddress.ip_address(d)
        return None  # IPs are not domains
    except ValueError:
        pass
    if not all(_LABEL.match(p) for p in d.split(".")):
        return None
    return d


def parse_list(text: str) -> tuple[list[str], list[str]]:
    """Parse a blocklist file: returns (domains, path_rules). Supports '#' comments, tags in [..],
    hosts-file format ('0.0.0.0 example.com') and 'host/path' path rules."""
    domains: list[str] = []
    paths: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        tokens = [t for t in line.split() if not t.startswith("[")]
        if not tokens:
            continue
        if len(tokens) >= 2 and tokens[0] in ("0.0.0.0", "127.0.0.1", "::"):
            tokens = tokens[1:]
        entry = tokens[0].lower()
        entry = re.sub(r"^[a-z]+://", "", entry)
        if "/" in entry.strip("/"):
            host, _, path = entry.partition("/")
            if normalize_domain(host):
                paths.append(f"{normalize_domain(host)}/{path.strip('/')}")
            continue
        d = normalize_domain(entry)
        if d:
            domains.append(d)
    return sorted(set(domains)), sorted(set(paths))


@dataclass
class DomainSet:
    """Suffix matcher: 'openai.com' matches 'openai.com' and 'api.openai.com', not 'notopenai.com'."""

    domains: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, items: Iterable[str]) -> "DomainSet":
        return cls({d for d in (normalize_domain(i) for i in items) if d})

    def matches(self, host: str | None) -> str | None:
        if not host:
            return None
        h = host.lower().rstrip(".")
        parts = h.split(".")
        for i in range(len(parts) - 1):
            cand = ".".join(parts[i:])
            if cand in self.domains:
                return cand
        return None

    def __len__(self) -> int:
        return len(self.domains)


# Sign-in, mail, documents and messaging hosts are never decrypted, whatever inspect_hosts says
# (a wildcard such as "*.google.com" included). Privacy floor, not a detection signature, so it
# stays in code where a setting can't remove it. Matched as suffixes.
NEVER_INSPECT = frozenset({
    "accounts.google.com", "myaccount.google.com", "mail.google.com", "docs.google.com",
    "drive.google.com", "calendar.google.com", "contacts.google.com", "chat.google.com",
    "meet.google.com", "keep.google.com", "photos.google.com", "pay.google.com", "gmail.com",
    "accounts.youtube.com", "login.live.com", "login.microsoftonline.com", "login.microsoft.com",
    "account.microsoft.com", "account.live.com", "outlook.live.com", "outlook.office.com",
    "outlook.office365.com", "login.yahoo.com", "mail.yahoo.com",
})


@dataclass
class InspectHosts:
    """Hosts the proxy may decrypt. 'www.google.com' matches only that host; '*.example.com' matches
    subdomains of example.com (not example.com itself). NEVER_INSPECT hosts never match."""

    exact: set[str] = field(default_factory=set)
    wildcard: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, items: Iterable[str]) -> "InspectHosts":
        s = cls()
        for it in items:
            if not isinstance(it, str):
                continue
            raw = it.strip().lower()
            wild = raw.startswith("*.")
            d = normalize_domain(raw[2:] if wild else raw)
            if d:
                (s.wildcard if wild else s.exact).add(d)
        return s

    def matches(self, host: str | None) -> bool:
        if not host:
            return False
        h = host.lower().rstrip(".")
        if _NEVER.matches(h):
            return False
        if h in self.exact:
            return True
        parts = h.split(".")
        return any(".".join(parts[i:]) in self.wildcard for i in range(1, len(parts) - 1))

    def __len__(self) -> int:
        return len(self.exact) + len(self.wildcard)


_NEVER = DomainSet(set(NEVER_INSPECT))


def normalize_path(path: str) -> str:
    """Request path as an origin is likely to read it, for path-rule matching (I-PROXY-16): no query
    or fragment, percent-decoded (repeated until stable, at most 3 times, so `%2563` is caught too),
    a backslash read as `/`, `;params` dropped from every segment, `//` collapsed, `.`/`..` resolved,
    lower-case, always starting with `/`. Only for matching; events still ship `loggable_path`."""
    p = path.split("#", 1)[0].split("?", 1)[0]
    for _ in range(3):
        d = unquote(p, errors="replace")
        if d == p:
            break
        p = d
    p = p.split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
    p = "/".join(seg.split(";", 1)[0] for seg in p.split("/"))
    p = re.sub(r"/{2,}", "/", "/" + p)
    p = posixpath.normpath(p)
    return p.lower() if p != "." else "/"


@dataclass
class PathRules:
    """'huggingface.co/chat' blocks https://huggingface.co/chat and below (and subdomains of the host)."""

    rules: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def of(cls, items: Iterable[str]) -> "PathRules":
        out = []
        for it in items:
            host, _, path = it.lower().partition("/")
            if host:
                out.append((host, normalize_path(path)))
        return cls(out)

    def matches(self, host: str | None, path: str) -> str | None:
        if not host:
            return None
        h = host.lower().rstrip(".")
        p = normalize_path(path)   # /%63hat, //chat, /chat;x, /x/../chat all read as /chat
        for rh, rp in self.rules:
            if (h == rh or h.endswith("." + rh)) and (p == rp or p.startswith(rp.rstrip("/") + "/")):
                return f"{rh}{rp}"
        return None
