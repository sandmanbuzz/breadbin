# Local containerized CI (MVP)

Tooling under `tools/ci/` to run the Breadbin tests in disposable containers and to arbitrate shared machines (VICE, the Ultimate) between sessions that do not share a filesystem. Local only; nothing here is wired into the Makefile or `tools/with-lock`.

## Run tests in a container

```sh
tools/ci/run.sh test-host
tools/ci/run.sh test-smoke
tools/ci/run.sh test-only T="tests.test_system.Boot.test_02_echo"
```

`run.sh` builds the `breadbin-ci` image on first use (Debian trixie, cc65, VICE 3.9 `x64sc`, xvfb, xdotool, python3, make; arm64 native). The repo is mounted read-only and copied into the container, so every run has its own `build/` and its own VICE (monitor port included); concurrent runs do not collide. The exit code is make's. Results of a run are not kept (`BREADBIN_CI_*` below).

ROMs are never baked into the image. They live in a host directory (`BREADBIN_CI_ROMS`, default `~/.cache/breadbin-ci/roms`), mounted read-only and copied into VICE's data directory at container start. If the directory has no C64 KERNAL, `run.sh` fills it with `tools/setup-vice-roms.sh` (needs network once). JiffyDOS ROMs: `BREADBIN_CI_JIFFY=<dir>` (holding `JiffyDOS-C64.bin` and `JiffyDOS_1541-II.bin`) mounts them read-only and passes them to VICE as the KERNAL and the 1541 ROMs; `BREADBIN_VICE_ARGS` is passed through. Wired but not yet run against the real ROMs (`docs/runner-move.md`, step 0).

Env: `BREADBIN_CI_IMAGE`, `BREADBIN_CI_ROMS`, `BREADBIN_CI_MEM` (container memory limit), `BREADBIN_BROKER` (passed in, `127.0.0.1` rewritten to `host.containers.internal`). Rebuild the image after editing the Containerfile or entrypoint: `podman build -t breadbin-ci -f tools/ci/Containerfile tools/ci`.

Always wrap manual experiments in `timeout`; `run.sh` uses `--rm --init`.

## Sharded suite

`tools/ci/sharded.sh` runs the VICE suite as six containers at once (`tools/ci/shards.txt`: Boot whole; Cache split by method; Console and Keyboard alone), under one `with-lock -x`, so the only load is its own six VICEs. It builds and runs the host tests first, snapshots the commit with `git archive` so every shard sees one tree, then prints a table per shard and writes `merged.log` (failures first) and load samples. It fails on any non-zero shard, a shard with no `Ran` line, any skip, or a total that differs from the discovered test count. `tools/ci/sharded.sh --check` (and `tools/test_shards.py`, in `make test-host`) checks without VICE that every test is in exactly one shard, so a new test cannot fall out of it: add it to `shards.txt`. No retry: a red shard stays red until its cause is known. The serial run (`BREADBIN_CI_EXCLUSIVE=1 tools/ci/run.sh test`) stays the reference gate until three sharded runs in a row give the same pass/fail set.

Cap check on the runner (2026-11-03, `tools/with-lock -x`, 6 slots, VICE 3.9, x86_64): `Boot.test_26` alone 70 s, 3 at once 72 s, 6 at once 73 s; the `Cache` class (9 tests, about 17 boots) 486 s alone, 489 s with five `Boot.test_26` copies beside it, and 489 s with six `Cache` runs at once. No failures in any of it. So six concurrent runs cost under 1 % here; the knee, if there is one, is above six (not measured).

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
- `tools/with-lock` and the broker do not know about each other; use one or the other for a given resource. `run.sh` takes a `vice` slot through `tools/with-lock` (6 slots, `-x` for wall-clock runs: `docs/process.md`); the broker is not running and has no slots, so it is not on the default path.
- The slot cap is a guess, not a measurement. On the Mac it was 3, limited by the podman VM (4 CPUs, 2 GiB). On the runner podman runs natively (no VM; 32 threads, 125 GB) and the cap is 6; `--cpus` and `--cpuset-cpus` need cgroup delegation to the user (not set up: `docs/runner-move.md`, step 0.7), so slots are not pinned yet. Measure jitter at 1, 3 and 6 concurrent runs before raising it.
- Done 2026-10-31 (Agent 3, on `main` ca89021, VICE 3.9 in the container, `timeout 1500 tools/with-lock -- tools/ci/run.sh test-host|test-keyboard`): `test-host` 48 pass; `test-keyboard` 7 of 7 pass in about 4 minutes (the first run of the real-keystroke tests since they need X). `tools/ci/run.sh test-keyboard` is the way to run them from a Mac.
- Not done: console tests were not run in the container; JiffyDOS runs; the full suite; wiring into the Makefile or `docs/process.md`; hardware (Ultimate) access from containers; a persistent results/log store; CI triggers on push.
