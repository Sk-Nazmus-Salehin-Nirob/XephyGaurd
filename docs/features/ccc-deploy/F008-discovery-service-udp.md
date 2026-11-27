# F8. Discovery service (UDP)

- **Component:** ccc-deploy (also: agent)
- **Area:** 1. CCC setup and operations
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** lets agents find the CCC on the LAN without a configured host.
- **Trigger:** UDP broadcast to port `XG_DISCOVERY_PORT` (47474); Docker service `discovery`.
- **Code:** `ccc-deploy/services/discovery.py`; agent side `A/core/src/discovery*` (reply parsing).
- **In/out/side effects:** replies with CCC address and CA fingerprint; no writes. `ca.crt` is read in a `with`
  block (no file handle left open per reply); ruff clean, CI rules and ruff's defaults (ccc-deploy Step 9).
  Only a JSON object with `"probe":"XEPHYGUARD_DISCOVER"` gets a reply (`reply_for`); `[]`, numbers, strings,
  invalid JSON or UTF-8 are ignored, a missing or malformed `ca.crt` gives `"ca_fingerprint": ""`, and an error on
  one datagram (e.g. `sendto`) is logged and the loop goes on (ccc-deploy Step 22, I-CCC-12).
  Only sources in `XG_LAB_SUBNET` are answered (unset: every source, with a warning; invalid: the service stops at
  start); the socket is bound to `XG_LAN_IF` with `SO_BINDTODEVICE` where the kernel allows it unprivileged
  (Linux 5.7+, else a warning and the subnet filter alone); each source gets 5 replies, then one every 2 s
  (token bucket, at most 4096 sources remembered). The reply (~200 bytes) is still larger than the probe
  (37 bytes): that amplification is accepted, limited to the lab subnet and the rate (ccc-deploy Step 23, I-CCC-19).
- **Status:** partly working (agent reply parsing tested; the service's reply, fingerprint and loop are unit-tested in `proxy/tests/test_ccc_deploy_scripts.py`, never run on a lab LAN).
- **Test:** 1. Start `python3 ccc-deploy/services/discovery.py`. 2. From a lab PC, run the agent
  enroll without `--ccc` and check it finds the server.
