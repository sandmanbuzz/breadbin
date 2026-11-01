# Local containerized CI (MVP)

Tooling under `tools/ci/` to run the Breadbin tests in disposable containers and to arbitrate shared machines (VICE, the Ultimate) between sessions that do not share a filesystem. Local only; nothing here is wired into the Makefile or `tools/with-lock`.

## Run tests in a container

```sh
tools/ci/run.sh test-host
tools/ci/run.sh test-smoke
tools/ci/run.sh test-only T="tests.test_system.Boot.test_02_echo"
```

`run.sh` builds the `breadbin-ci` image on first use (Debian trixie, cc65, VICE 3.9 `x64sc`, xvfb, xdotool, python3, make; arm64 native). The repo is mounted read-only and copied into the container, so every run has its own `build/` and its own VICE (monitor port included); concurrent runs do not collide. The exit code is make's. Results of a run are not kept (`BREADBIN_CI_*` below).

ROMs are never baked into the image. They live in a host directory (`BREADBIN_CI_ROMS`, default `~/.cache/breadbin-ci/roms`), mounted read-only and copied into VICE's data directory at container start. If the directory has no C64 KERNAL, `run.sh` fills it with `tools/setup-vice-roms.sh` (needs network once). JiffyDOS ROMs: mount them yourself and pass `BREADBIN_VICE_ARGS` (not wired through `run.sh` yet).

Env: `BREADBIN_CI_IMAGE`, `BREADBIN_CI_ROMS`, `BREADBIN_CI_MEM` (container memory limit), `BREADBIN_BROKER` (passed in, `127.0.0.1` rewritten to `host.containers.internal`). Rebuild the image after editing the Containerfile or entrypoint: `podman build -t breadbin-ci -f tools/ci/Containerfile tools/ci`.

Always wrap manual experiments in `timeout`; `run.sh` uses `--rm --init`.

## Lease broker

`tools/ci/broker.py` is a stdlib-only lease broker: named resources (`vice`, `ultimate`, anything), FIFO queue, holder label, lease dies when the client's connection drops. `tools/ci/lease` is the client, same shape as `tools/with-lock`:

```sh
tools/ci/run-broker.sh start                         # in a container, 127.0.0.1:7077 only
python3 tools/ci/broker.py --listen 127.0.0.1:7077   # or plain on the host (or unix:/path)
export BREADBIN_BROKER=127.0.0.1:7077
tools/ci/lease -r ultimate -t 600 -- python3 tools/ultimate.py ...
tools/ci/lease -r vice -- tools/ci/run.sh test-smoke
python3 tools/ci/broker.py status                    # holders and queue (or run-broker.sh status)
```

If the broker is down, `lease` exits 69 with a message and does not run the command; `BREADBIN_LEASE_FALLBACK=with-lock` makes it use `tools/with-lock` instead (host-local only). Timeout exits 75, as with-lock does. Sessions in other containers reach the host broker at `host.containers.internal:7077`.

Broker state is in memory. A restart drops all leases and queues; the running commands continue (the client warns) and clients must re-request. Test: `python3 -m unittest tools.ci.test_broker` (no containers; not picked up by `make test-host`, whose pattern only scans `tools/`).

## Limits and not done

- The broker is advisory: nothing stops someone running VICE without a lease. No authentication; bind it to localhost only.
- `tools/with-lock` and the broker do not know about each other; use one or the other for a given resource.
- Not done: keyboard/console tests were not run in the container; JiffyDOS runs; the full suite; wiring into the Makefile or `docs/process.md`; hardware (Ultimate) access from containers; a persistent results/log store; CI triggers on push.
