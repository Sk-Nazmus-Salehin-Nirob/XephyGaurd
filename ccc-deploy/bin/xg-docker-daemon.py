#!/usr/bin/env python3
"""Merges XephyGuard's settings into /etc/docker/daemon.json instead of overwriting it (I-CCC-17).

Usage: xg-docker-daemon.py PATH  ->  prints "changed" or "unchanged"; exit 1 if PATH is not a JSON object.

Docker must not touch the firewall (XephyGuard owns forwarding via nftables, and every CCC container
uses host networking), so "iptables" and "ip6tables" are always set to false. The log rotation is only
a default: an existing "log-driver"/"log-opts" is kept. Every other key the admin set stays as it is.
A changed file is first copied to PATH.xephyguard-<UTC time>.bak, then replaced atomically, same mode.
"""
import datetime
import json
import os
import shutil
import sys
import tempfile

REQUIRED = {"iptables": False, "ip6tables": False}
DEFAULTS = {"log-driver": "json-file", "log-opts": {"max-size": "20m", "max-file": "5"}}


def merge(text: str) -> dict:
    """Returns the merged settings; ValueError for invalid JSON, TypeError for JSON that is not an object."""
    current = json.loads(text) if text.strip() else {}
    if not isinstance(current, dict):
        raise TypeError("daemon.json is not a JSON object")
    merged = dict(current)
    merged.update(REQUIRED)
    if "log-driver" not in current:   # the rotation options belong to the driver: add both or neither
        merged.update(DEFAULTS)
    return merged


def main(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    try:
        merged = merge(text)
    except (ValueError, TypeError) as e:   # json.JSONDecodeError is a ValueError
        print(f"{path}: {e}; not changed, fix it by hand", file=sys.stderr)
        return 1
    if text.strip() and json.loads(text) == merged:
        print("unchanged")
        return 0
    if text:
        # timezone.utc, not datetime.UTC: Ubuntu 22.04 (supported by install.sh) has Python 3.10.
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
        shutil.copy2(path, f"{path}.xephyguard-{stamp}.bak")
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".daemon.json.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
            f.write("\n")
        if text:
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print("changed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
