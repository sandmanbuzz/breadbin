# Local containerized CI (MVP)

Tooling under `tools/ci/` to run the Breadbin tests in disposable containers and and, with `tools/with-lock`, to share the machine (VICE slots, the Ultimate) between sessions. Local only; not wired into the Makefile. `run.sh` takes a `vice` slot through `tools/with-lock` (`docs/process.md`).

## Run tests in a container

```sh
tools/ci/run.sh test-host
tools/ci/run.sh test-smoke
tools/ci/run.sh test-only T="tests.test_system.Boot.test_02_echo"
```

`run.sh` builds the `breadbin-ci` image on first use (Debian trixie, cc65 2.19, VICE 3.9 `x64sc`, xvfb, xdotool, python3, make, py65 in `/opt/venv`; built natively for the host's architecture: x86_64 on the runner, arm64 on the Mac it came from). The repo is mounted read-only and copied into the container, so every run has its own `build/` and its own VICE (monitor port included); concurrent runs do not collide. The exit code is make's. Results of a run are not kept (`BREADBIN_CI_*` below).

ROMs are never baked into the image. They live in a host directory (`BREADBIN_CI_ROMS`, default `~/.cache/breadbin-ci/roms`), mounted read-only and copied into VICE's data directory at container start. If the directory has no C64 KERNAL, `run.sh` fills it with `tools/setup-vice-roms.sh` (needs network once). JiffyDOS ROMs: `BREADBIN_CI_JIFFY=<dir>` (holding `JiffyDOS-C64.bin` and `JiffyDOS_1541-II.bin`) mounts them read-only and passes them to VICE as the KERNAL and the 1541 ROMs; `BREADBIN_VICE_ARGS` is passed through. Wired but not yet run against the real ROMs.

Env: `BREADBIN_CI_IMAGE`, `BREADBIN_CI_ROMS`, `BREADBIN_CI_MEM` (container memory limit). Rebuild the image after editing the Containerfile or entrypoint: `podman build -t breadbin-ci -f tools/ci/Containerfile tools/ci`.

Always wrap manual experiments in `timeout`; `run.sh` uses `--rm --init`.

## Sharded suite

`tools/ci/sharded.sh` runs the VICE suite as six containers (`tools/ci/shards.txt`, packed on 2026-11-24: Boot in two halves; Cache, IecFault, IecRestart and Drives by method; Console and Keyboard whole modules; Drives last in its shard), one vice slot each, so a sharded run holds six of the twelve-slot pool and no more (a work unit takes at most six). Other VICE runs share the rest of the pool. `--exclusive` takes the whole pool under `with-lock -x --emergency` instead (the exclusive-run pattern, `docs/process.md`: the notice grows with the slot count), for a run whose wall-clock figures you will quote: that goes past the six-slot guideline, so use it only for timing, and say why (the exclusivity backlog item in `docs/wip.md` tests whether it is needed). It builds and runs the host tests first, snapshots the commit with `git archive` so every shard sees one tree, then prints a table per shard and writes `merged.log` (failures first) and load samples. It fails on any non-zero shard, a shard with no `Ran` line, any skip, or a total that differs from the discovered test count. `tools/ci/sharded.sh --check` (and `tools/test_shards.py`, in `make test-host`) checks without VICE that every test is in exactly one shard, so a new test cannot fall out of it: add it to `shards.txt`. A shard that runs past `--shard-timeout` (default 1800 s) is killed and reads red (rc 124, shown as `timeout`); Ctrl-C or TERM stops every shard and removes its container; a rerun in the same `--out` clears the old verdict files; the driver runs the commit `--rev`, not the working tree (it warns about uncommitted changes); `--check` also refuses a class and one of its methods in the same shard, and a shard line without specs. No retry: a red shard stays red until its cause is known. Result on the runner (2026-11-03, commit bb24568, same image, `-x`): three runs in a row, each 63 of 63 passed with no skips, wall 639, 637 and 639 s (the serial exclusive run: 2,804 s); Boot is in two halves (00-15 and 16-26, each about 470 s), Drives is the longest shard (585 s), Console and Keyboard run together (about 375 s). Agent D then split Drives by method across the Console and Keyboard shards (still six shards, six slots): three more green runs on 782fbdf, 63 of 63 each, wall 550, 553 and 553 s, the longest shard about 496 s. That matches the serial run's pass/fail set (all green) three times, but none of these runs was red, so the sharded run's ability to catch a failure is shown only by its checks (exit codes, `Ran` lines, skips, the count), not by a failing test. The serial run stays available as the reference (`BREADBIN_CI_EXCLUSIVE=1 tools/ci/run.sh test`).

Cap check on the runner (2026-11-03, `tools/with-lock -x`, 6 slots, VICE 3.9, x86_64): `Boot.test_26` alone 70 s, 3 at once 72 s, 6 at once 73 s; the `Cache` class (9 tests, about 17 boots) 486 s alone, 489 s with five `Boot.test_26` copies beside it, and 489 s with six `Cache` runs at once. No failures in any of it. So six concurrent runs cost under 1 % here; the knee, if there is one, is above six (not measured).

## Retired: the lease broker

`tools/ci/broker.py`, `tools/ci/lease`, `tools/ci/run-broker.sh` and `tools/ci/test_broker.py` were a lease broker for sharing machines between sessions that do not share a filesystem. The sessions now share one machine and one lock directory, so `tools/with-lock` is the only arbiter (`docs/process.md`); the broker has never been on the default path and no session runs it. The files are still in the repository; whether to delete them is the owner's call (the list is in the commit that retired this section). `run.sh` still passes `BREADBIN_BROKER` into the container if it is set; nothing reads it.

## Limits and not done

- The lock is advisory: nothing stops someone running VICE outside `run.sh`. Host VICE is retired as a test path (the container is the only toolchain: `docs/process.md`); a host run that bypasses the lock disturbs the timing of the runs that hold it.
- The slot cap is 12 (raised from 8 on 2026-11-23 for testing; not yet measured at 12). Before that it was 8 (the owner's number; raised from 6 on 2026-11-13, not yet measured at 8). On the Mac it was 3, limited by the podman VM. On the runner podman runs natively (32 threads, 125 GB) and six concurrent runs cost nothing measurable (see "Sharded suite"); the knee above 6 is not measured. `--cpus` and `--cpuset-cpus` need cgroup delegation to the user (not set up), so slots are not pinned.
- Done 2026-10-31 (Agent 3, on `main` ca89021, VICE 3.9 in the container, `timeout 1500 tools/with-lock -- tools/ci/run.sh test-host|test-keyboard`): `test-host` 48 pass; `test-keyboard` 7 of 7 pass in about 4 minutes (the first run of the real-keystroke tests since they need X). `tools/ci/run.sh test-keyboard` is the way to run them.
- Done since: the console tests, the full suite (serial and sharded) and JiffyDOS runs in the container (see the sections above and `docs/testing.md`); `docs/process.md` makes `run.sh` the default path.
- Not done: wiring into the Makefile; hardware (Ultimate) access from containers; a persistent results/log store; CI triggers on push.

Sharded run on 6158182 (2026-11-13, `-x`, default slots now 8, six shards, one run): 136 of 136 tests PASS, no skips, wall 1,439 s (host tests 84 s first). Longest shards: s5 compiled-console-modules 1,419 s, s1 boota-cache 1,377 s. The suite has grown from 63 to 136 tests since the 639 s runs, so the wall time is not comparable with them; six shards leave two of the eight slots idle (a rebalance into eight shards is the lever, not done). Red-detection is shown by the checks only, as before.
