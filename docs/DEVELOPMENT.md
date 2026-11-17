# Development

Development happens on Linux. Each component builds and tests on its own.

| Component | Build / run | Tests |
|---|---|---|
| Agent (C++20) | `cmake -S agent -B build && cmake --build build -j` | `ctest --test-dir build` (Catch2, fake adapters in `agent/tests/fakes.hpp`) |
| Agent package | `cmake -S agent -B build-rel -DCMAKE_BUILD_TYPE=Release -DXG_BUILD_TESTS=OFF && cmake --build build-rel && (cd build-rel && cpack)` | install test: `docker run ... ubuntu:24.04 apt install ./xephyguard-agent_*.deb` |
| Windows adapters | MSVC build on Windows (see `installers/windows/README.md`); on Linux a MinGW syntax check (CI job `agent-windows-compile-check`) | `docs/WINDOWS_TEST_CHECKLIST.md` on a real machine |
| CCC server (Laravel 13) | `cd server && composer install && npm ci && npm run build && php artisan migrate && php artisan xephyguard:ca:init && php artisan xephyguard:bootstrap && php artisan serve` | `php artisan test` |
| Proxy + network policy | `pip install -r proxy/requirements.txt` | `pytest proxy/tests` (uses mitmproxy's test helpers) |
| Analysis | `pip install -r analysis/requirements.txt`; `python -m xg_analysis serve` | `pytest analysis/tests` (schema generated from the migrations: `scripts/gen_analysis_schema.sh`) |
| Eval tools | – | `pytest eval/tests` |
| Signatures | edit `data/signatures/*.yaml` | `python3 scripts/compile_signatures.py` validates; CCC: Blocklists & signatures → Publish |

Dependencies of the agent: OpenSSL 3, SQLite3, pthreads (system); nlohmann/json, toml++ and Catch2 are
fetched by CMake and pinned. Optional: X11 + Xfixes for the Linux helper.

Agent sanitizers (GCC/Clang, no extra dependencies): configure a separate build dir with
`-DXG_SANITIZE=address,undefined` or `-DXG_SANITIZE=thread`, then build and `ctest` as usual. On Linux 6.x
kernels ThreadSanitizer can abort with "unexpected memory mapping" (also during Catch2 test discovery at link
time); run both the build and the tests under `setarch -R`. Last run (2026-11-17, actor core): both clean,
67/67 tests, 0 TSAN warnings.

## Screen streaming (xephyguard-screen)
Run each from the repo root:
* Gateway (Go): `(cd xephyguard-screen/gateway && go mod tidy && go vet ./... && go test -race ./...)`
* Core/capture (C++): `cmake -S xephyguard-screen -B xephyguard-screen/build -DCMAKE_INSTALL_DOCDIR=doc && systemd-run --user --scope -q -p MemoryMax=5G -p MemorySwapMax=0 nice cmake --build xephyguard-screen/build -j6 && ctest --test-dir xephyguard-screen/build --output-on-failure`
* Viewer (JS): `(cd xephyguard-screen && node --test viewer)`

Notes: without `-DCMAKE_INSTALL_DOCDIR=doc` a standalone configure fails inside the fetched libjpeg-turbo
(`set_property could not find CACHE variable CMAKE_INSTALL_DOCDIR`).
The build dir must sit inside `xephyguard-screen/`: the fixture test writes `../tests/fixtures/*.bin`
relative to the ctest working dir. `xgtests` takes ~2.5 min. `go.mod` asks for Go 1.27.4; an older `go`
downloads it once (`GOTOOLCHAIN=auto`).

Baseline (2026-11-17, Linux, Go 1.27.4, Node 20, CMake 3.28): gateway vet clean, `go test -race` ok;
core configure fails without the flag above; with it, `xgtests` 34/35 from a build dir outside the tree, and
the remaining fixture case passes when run from `xephyguard-screen/` (fixtures unchanged); viewer 5/5.

## Running the agent against a local CCC (no Docker)
1. In `server/`: `php artisan serve --port=8000` and `php artisan reverb:start --port=8081`
   (set `REVERB_PORT=8081`).
2. Put an nginx with the `:8443` server block from `ccc-deploy/nginx/xephyguard.conf` in front
   (`proxy_pass http://127.0.0.1:8000` and set `X-SSL-Client-Verify` / `X-SSL-Client-Cert`).
3. Write an `agent.toml` with non-root paths (`data_dir`, `ca_file`, `ipc`, …) and run
   `xephyguard-agent enroll --config agent.toml --key <key> --ccc localhost`, approve in the dashboard,
   then `XG_IPC_ALLOW_ANY=1 xephyguard-agent run --config agent.toml --foreground`.

This is how the end-to-end tests in the project log were run (enrollment, mTLS, Reverb commands, mode
switch in 0.55 s, process alert in < 0.1 s, machine-silent alert after ~15 s, tamper alerts).

## Conventions
* Nothing about detections is hard-coded in the agent: rules are data (`data/signatures`), compiled
  and signed by the CCC.
* Privacy: content never leaves the function that measures it (see `paste.cpp`, `keystats.cpp`,
  `input_evdev.cpp`, `helper_win.cpp`). Keep it that way in reviews.
* Record design choices in `docs/DECISIONS.md`.
