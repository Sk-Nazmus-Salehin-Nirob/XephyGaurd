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

log = logging.getLogger("xg-netpolicy.state")

# VPN/tunnel ports block_ai PCs may not reach through the gateway (I-PROXY-18), as "port/proto".
# Same list as data/network/proxy.yaml `vpn_ports` (a test keeps them equal); used when the state
# document has no usable `vpn_ports` (missing, not a list, or nothing valid left).
VPN_PORTS_DEFAULTS = ["51820/udp", "1194/udp", "1194/tcp", "500/udp", "4500/udp", "1723/tcp", "22/tcp", "1701/udp"]


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
        one odd PC never stops a session from being enforced for all the others."""
        if self.network_mode is not None and not isinstance(self.network_mode, str):
            raise ValueError(f"network_mode must be a string, not {type(self.network_mode).__name__}")
        ipaddress.ip_address(self.ccc_ip)
        net = ipaddress.ip_network(self.lab_subnet, strict=False)
        if not isinstance(self.groups, dict):
            raise ValueError(f"groups must be an object, not {type(self.groups).__name__}")
        if not isinstance(self.google, dict):
            raise ValueError(f"google must be an object, not {type(self.google).__name__}")
        self.skipped = []
        groups: dict[str, list[str]] = {}
        for g, ips in self.groups.items():
            if not isinstance(ips, list):
                raise ValueError(f"groups.{g} must be a list, not {type(ips).__name__}")
            groups[g] = self._pc_ips(f"groups.{g}", ips, net)
        self.groups = groups
        udm = self.google.get("udm14_clients")
        if udm is not None:
            if not isinstance(udm, list):
                raise ValueError(f"udm14_clients must be a list, not {type(udm).__name__}")
            self.google = {**self.google, "udm14_clients": self._pc_ips("udm14_clients", udm, net)}
        self.vpn_ports = self._vpn_ports(self.vpn_ports)
        for name in self.lan_if, self.wan_if:
            if not isinstance(name, str) or not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
                raise ValueError(f"bad interface name {name!r}")

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
        """Most restrictive group a client belongs to (exempt wins over everything)."""
        if not ip:
            return None
        ip = ip.removeprefix("::ffff:")
        for g in ("exempt", "isolated", "test", "block_ai"):
            if ip in self.groups.get(g, []):
                return g
        return None

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
