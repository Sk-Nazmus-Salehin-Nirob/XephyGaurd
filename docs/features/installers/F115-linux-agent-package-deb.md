# F115. Linux agent package (.deb)

- **Component:** installers (also: agent)
- **Area:** 19. Packaging and deployment tools
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** CPack `.deb` with the agent, helper, systemd units, default config, postinst/prerm/postrm.
- **Trigger:** `cmake -S agent -B agent/build-rel -DCMAKE_BUILD_TYPE=Release -DXG_BUILD_TESTS=OFF && cmake --build agent/build-rel -j2 && (cd agent/build-rel && cpack)`.
- **Code:** `agent/CMakeLists.txt`, `agent/packaging/`, `installers/linux/*`.
  Uninstall also drops the proxy's interception CA the agent installed (agent Step 41): `prerm` removes the
  "XephyGuard Interception CA" nickname from the NSS databases (`install-browser-ca.sh --remove`, which now also
  takes `CERT NICKNAME`), `postrm` deletes the system copy and runs `update-ca-certificates --fresh`; the Firefox
  policy lists the interception CA's path next to the lab CA's (agent Step 42).
- **Status:** unclear (CI builds it; not built today).
- **Test:** 1. Build it. 2. `sudo apt install ./xephyguard-agent_*.deb` in a VM.
