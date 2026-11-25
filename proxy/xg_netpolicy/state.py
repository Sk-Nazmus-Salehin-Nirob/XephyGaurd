"""Typed view of the network policy state document written by the CCC."""
from __future__ import annotations

import ipaddress
import json
import logging
import pathlib
from dataclasses import dataclass, field
from typing import Any

from .domains import DomainSet, PathRules

GROUPS = ("test", "block_ai", "isolated", "exempt")
# A PC listed in several groups is kept only in the first of these (State._disjoint, I-PROXY-28).
GROUP_PRECEDENCE = ("exempt", "isolated", "test", "block_ai")

log = logging.getLogger("xg-netpolicy.state")

# VPN/tunnel ports block_ai PCs may not reach through the gateway (I-PROXY-18), as "port/proto".
# Same list as data/network/proxy.yaml `vpn_ports` (a test keeps them equal); used when the state
# document has no usable `vpn_ports` (missing, not a list, or nothing valid left).
VPN_PORTS_DEFAULTS = ["51820/udp", "1194/udp", "1194/tcp", "500/udp", "4500/udp", "1723/tcp", "22/tcp", "1701/udp"]

# Field types checked by validate() (I-PROXY-19). A wrong type rejects the document (ValueError).
INT_FIELDS = ("version", "proxy_port", "agent_port")
STR_FIELDS = ("ccc_ip", "lab_subnet", "lan_if", "wan_if")
OPT_STR_FIELDS = ("events_url", "events_token")  # null (unset server config) is read as ""
STR_LIST_FIELDS = ("always_block", "inspect_hosts")
STR_LIST_DICT_FIELDS = ("categories", "path_rules", "group_categories")  # {name: [str, ...]}
DICT_FIELDS = ("groups", "google", "log_urls")


def _type_name(v: Any) -> str:
    return "null" if v is None else type(v).__name__


@dataclass
class State:
    version: int = 0
    ccc_ip: str = "192.168.10.2"
    lab_subnet: str = "192.168.10.0/24"
    lan_if: str = "lan0"
    wan_if: str = "wan0"
    proxy_port: int = 8080
    agent_port: int = 8443
    # None = the document has no (or a null) network_mode; generate then uses env XG_NETWORK_MODE
    network_mode: str | None = None
    groups: dict[str, list[str]] = field(default_factory=lambda: {g: [] for g in GROUPS})
    categories: dict[str, list[str]] = field(default_factory=dict)
    path_rules: dict[str, list[str]] = field(default_factory=dict)
    group_categories: dict[str, list[str]] = field(default_factory=dict)
    always_block: list[str] = field(default_factory=lambda: ["doh"])
    doh_ips: list[str] = field(default_factory=list)
    google: dict[str, Any] = field(default_factory=lambda: {"force_udm14": True, "udm14_clients": [], "hide_selectors": [], "strip_markers": []})
    inspect_hosts: list[str] = field(default_factory=list)
    log_urls: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "query": False})
    events_url: str = ""
    events_token: str = ""
    # "port/proto" (tcp|udp); validate() replaces a missing or unusable list with VPN_PORTS_DEFAULTS
    vpn_ports: list[str] | None = None
    # PCs in a running session (I-PROXY-10); None = the document has no list, so a PC counts as in
    # a session when it is in test, block_ai or exempt (the server lists only those PCs today)
    session_clients: list[str] | None = None
    # entries dropped by validate() as "<where>: <entry> (<reason>)"; not read from the document
    skipped: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "State":
        s = cls()
        for k, v in d.items():
            if hasattr(s, k):
                setattr(s, k, v)
        s.validate()
        for g in GROUPS:
            s.groups.setdefault(g, [])
        return s

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "State":
        return cls.from_dict(json.loads(pathlib.Path(path).read_text()))

    def validate(self) -> None:
        """Structural errors (wrong types, bad ccc_ip/lab_subnet/interface names) raise ValueError
        and reject the document. A single bad PC entry in a group or in google.udm14_clients
        (not a string, not an IPv4 address, outside lab_subnet) is dropped with a warning, so
        one odd PC never stops a session from being enforced for all the others; so is a bad
        doh_ips entry. Every field is type-checked first (I-PROXY-19): an integer ccc_ip or
        lab_subnet would pass ipaddress and be rendered as e.g. 3232238085/32."""
        self._check_types()
        if self.network_mode is not None and not isinstance(self.network_mode, str):
            raise ValueError(f"network_mode must be a string, not {_type_name(self.network_mode)}")
        # canonical text, so the Unbound/nft/proxy files only ever hold what ipaddress printed
        self.ccc_ip = str(ipaddress.ip_address(self.ccc_ip))
        net = ipaddress.ip_network(self.lab_subnet, strict=False)
        self.lab_subnet = str(net)
        self.skipped = []
        self.doh_ips = self._doh_ips(self.doh_ips)
        groups: dict[str, list[str]] = {}
        for g, ips in self.groups.items():
            if not isinstance(ips, list):
                raise ValueError(f"groups.{g} must be a list, not {type(ips).__name__}")
            groups[g] = self._pc_ips(f"groups.{g}", ips, net)
        self.groups = self._disjoint(groups)
        udm = self.google.get("udm14_clients")
        if udm is not None:
            if not isinstance(udm, list):
                raise ValueError(f"udm14_clients must be a list, not {type(udm).__name__}")
            self.google = {**self.google, "udm14_clients": self._pc_ips("udm14_clients", udm, net)}
        self.vpn_ports = self._vpn_ports(self.vpn_ports)
        if self.session_clients is not None:
            if not isinstance(self.session_clients, list):
                raise ValueError(f"session_clients must be a list, not {_type_name(self.session_clients)}")
            self.session_clients = self._pc_ips("session_clients", self.session_clients, net)
        for name in self.lan_if, self.wan_if:
            if not isinstance(name, str) or not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
                raise ValueError(f"bad interface name {name!r}")

    def _check_types(self) -> None:
        """ValueError on any field of the wrong JSON type. bool is not accepted as int. An empty
        JSON array is read as an empty object for categories/path_rules/group_categories: PHP's
        json_encode writes an empty array as [] (e.g. path_rules when no path entry is enabled)."""
        for k in INT_FIELDS:
            v = getattr(self, k)
            if not isinstance(v, int) or isinstance(v, bool):
                raise ValueError(f"{k} must be an integer, not {_type_name(v)}")
        for k in STR_FIELDS:
            v = getattr(self, k)
            if not isinstance(v, str):
                raise ValueError(f"{k} must be a string, not {_type_name(v)}")
        for k in OPT_STR_FIELDS:
            v = getattr(self, k)
            if v is None:
                setattr(self, k, "")
            elif not isinstance(v, str):
                raise ValueError(f"{k} must be a string, not {_type_name(v)}")
        for k in DICT_FIELDS + STR_LIST_DICT_FIELDS:
            v = getattr(self, k)
            if v == [] and k in STR_LIST_DICT_FIELDS:
                setattr(self, k, {})
            elif not isinstance(v, dict):
                raise ValueError(f"{k} must be an object, not {_type_name(v)}")
        for k in STR_LIST_FIELDS:
            self._str_list(k, getattr(self, k))
        for k in STR_LIST_DICT_FIELDS:
            for name, v in getattr(self, k).items():
                self._str_list(f"{k}.{name}", v)
        if not isinstance(self.doh_ips, list):
            raise ValueError(f"doh_ips must be a list, not {_type_name(self.doh_ips)}")

    @staticmethod
    def _str_list(where: str, v: Any) -> None:
        if not isinstance(v, list):
            raise ValueError(f"{where} must be a list, not {_type_name(v)}")
        for e in v:
            if not isinstance(e, str):
                raise ValueError(f"{where} entries must be strings, not {_type_name(e)} ({e!r})")

    def _doh_ips(self, entries: list[Any]) -> list[str]:
        """Resolver IPs/networks as ipaddress prints them; a bad entry (imported blocklist data) is
        dropped with a warning instead of making nft -f fail for every set."""
        kept: list[str] = []
        for e in entries:
            try:
                if not isinstance(e, str):
                    raise ValueError(f"not a string ({_type_name(e)})")
                n = ipaddress.ip_network(e.strip(), strict=False)
                kept.append(str(n.network_address) if n.prefixlen == n.max_prefixlen else str(n))
            except ValueError as err:
                reason = str(err) if not isinstance(e, str) else "not an IP address or network"
                self.skipped.append(f"doh_ips: {e!r} ({reason})")
                log.warning("doh_ips: skipping %r, %s", e, reason)
        return kept

    def _pc_ips(self, where: str, entries: list[Any], net: ipaddress.IPv4Network | ipaddress.IPv6Network) -> list[str]:
        kept: list[str] = []
        for e in entries:
            reason = None
            if not isinstance(e, str):
                reason = f"not a string ({type(e).__name__})"
            else:
                try:
                    a = ipaddress.ip_address(e.strip())
                except ValueError:
                    reason = "not an IP address"
                else:
                    if a.version != 4:
                        reason = "not IPv4"
                    elif a not in net:
                        reason = f"outside the lab subnet {self.lab_subnet}"
            if reason:
                self.skipped.append(f"{where}: {e!r} ({reason})")
                log.warning("%s: skipping %r, %s", where, e, reason)
            else:
                kept.append(str(a))
        return kept

    def _disjoint(self, groups: dict[str, list[str]]) -> dict[str, list[str]]:
        """Each IP stays in one group only (I-PROXY-28), the first in GROUP_PRECEDENCE (exempt wins,
        as in group_of), so Unbound, nft and the proxy all treat a PC the same way. An IP repeated
        within a group is kept once. A dropped membership is logged and recorded in `skipped`."""
        owner: dict[str, str] = {}
        out = {g: list(v) for g, v in groups.items()}
        for g in GROUP_PRECEDENCE:
            kept: list[str] = []
            for ip in groups.get(g, []):
                if ip not in owner:
                    owner[ip] = g
                    kept.append(ip)
                elif owner[ip] != g:
                    self.skipped.append(f"groups.{g}: {ip!r} (also in {owner[ip]}, {owner[ip]} wins)")
                    log.warning("groups.%s: %s is also in %s, keeping it only in %s", g, ip, owner[ip], owner[ip])
            if g in out:
                out[g] = kept
        return out

    def _vpn_ports(self, entries: Any) -> list[str]:
        """Canonical "port/proto" entries, de-duplicated in their order. A bad entry is dropped with
        a warning; a missing list, a non-list or one with nothing valid left gives the defaults."""
        if entries is None:
            return list(VPN_PORTS_DEFAULTS)
        if not isinstance(entries, list):
            self.skipped.append(f"vpn_ports: {entries!r} (not a list)")
            log.warning("vpn_ports is not a list (%s), using the built-in VPN ports", type(entries).__name__)
            return list(VPN_PORTS_DEFAULTS)
        kept: list[str] = []
        for e in entries:
            port, _, proto = e.strip().lower().partition("/") if isinstance(e, str) else ("", "", "")
            if port.isascii() and port.isdigit() and 1 <= int(port) <= 65535 and proto in ("tcp", "udp"):
                v = f"{int(port)}/{proto}"
                if v not in kept:
                    kept.append(v)
            else:
                self.skipped.append(f"vpn_ports: {e!r} (not port/tcp or port/udp)")
                log.warning("vpn_ports: skipping %r, not port/tcp or port/udp", e)
        if not kept:
            log.warning("vpn_ports has no valid entry, using the built-in VPN ports")
            return list(VPN_PORTS_DEFAULTS)
        return kept

    def vpn_port_numbers(self, proto: str) -> list[int]:
        """Sorted port numbers of vpn_ports for "tcp" or "udp" (the vpn_<proto>_ports nft set)."""
        ports = self.vpn_ports if self.vpn_ports is not None else VPN_PORTS_DEFAULTS
        return sorted({int(p) for p, _, pr in (e.partition("/") for e in ports) if pr == proto})

    # -- derived views ------------------------------------------------------------------------
    def group_of(self, ip: str | None) -> str | None:
        """The client's group; validate() already made groups disjoint with the same precedence
        (exempt wins over everything)."""
        if not ip:
            return None
        ip = ip.removeprefix("::ffff:")
        for g in GROUP_PRECEDENCE:
            if ip in self.groups.get(g, []):
                return g
        return None

    def in_session(self, ip: str | None) -> bool:
        """True when the PC is in a running session: listed in `session_clients`, or, when the
        document has no such list, in test, block_ai or exempt (a session PC whose profile blocks
        nothing is in no group, so it counts as not in a session until the server sends the list)."""
        if not ip:
            return False
        ip = ip.removeprefix("::ffff:")
        if self.session_clients is not None:
            return ip in self.session_clients
        return self.group_of(ip) in ("test", "block_ai", "exempt")

    def blocked_domains_for_group(self, group: str | None) -> DomainSet:
        cats = list(self.always_block)
        if group and group != "exempt":
            cats += self.group_categories.get(group, [])
        doms: list[str] = []
        for c in cats:
            doms += self.categories.get(c, [])
        return DomainSet.of(doms)

    def path_rules_for_group(self, group: str | None) -> PathRules:
        if not group or group == "exempt":
            return PathRules()
        rules: list[str] = []
        for c in self.group_categories.get(group, []):
            rules += self.path_rules.get(c, [])
        return PathRules.of(rules)

    def category_of(self, domain: str) -> str | None:
        for c, doms in self.categories.items():
            if DomainSet.of(doms).matches(domain):
                return c
        return None
