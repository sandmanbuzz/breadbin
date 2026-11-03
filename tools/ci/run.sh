#!/bin/sh
# Run make targets from the repo inside a fresh breadbin-ci container.
#   tools/ci/run.sh test-host
#   tools/ci/run.sh test-smoke
#   tools/ci/run.sh test-only T="tests.test_system.Boot.test_02_echo"
# Env: BREADBIN_CI_ROMS   host ROM dir (default ~/.cache/breadbin-ci/roms; filled by
#                         tools/setup-vice-roms.sh when empty: needs network once)
#      BREADBIN_CI_IMAGE  image name (default breadbin-ci; built if missing, and rebuilt when
#                         the Containerfile or entrypoint changed)
#      BREADBIN_CI_MEM    optional container memory limit, e.g. 1500m
#      BREADBIN_BROKER    passed through (host.containers.internal rewrite for localhost)
#      BREADBIN_CI_EXCLUSIVE  set to 1 to hold every VICE slot (wall-clock measurements)
#      BREADBIN_CI_JIFFY  host dir with JiffyDOS-C64.bin and JiffyDOS_1541-II.bin: mounted
#                         read-only and passed to VICE as the KERNAL and the 1541 ROMs
#      BREADBIN_VICE_ARGS extra VICE options for the whole run (passed through)
# The repo is mounted read-only and copied inside, so concurrent runs do not collide.
# Exit code is make's. Set BREADBIN_CI_KEEP_BUILD=<dir> to copy build/ out afterwards.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
img=${BREADBIN_CI_IMAGE:-breadbin-ci}
roms=${BREADBIN_CI_ROMS:-$HOME/.cache/breadbin-ci/roms}
[ $# -gt 0 ] || { echo "usage: run.sh <make target...>" >&2; exit 2; }

# The image is rebuilt when it is missing or, for the default image, when the Containerfile
# or entrypoint changed since it was built (a label holds their hash): a host that already
# has an older image would otherwise never get the new packages. The build runs under a
# lock of its own so that two runs do not build at once, and re-checks after taking it.
src=$(cat "$here/Containerfile" "$here/entrypoint.sh" | sha256sum | cut -c1-16)
image_ok() {
    podman image exists "$img" || return 1
    [ "$img" = breadbin-ci ] || return 0
    [ "$(podman image inspect --format '{{index .Config.Labels "breadbin.ci.src"}}' "$img" 2>/dev/null)" = "$src" ]
}
if [ "${1:-}" = --build-image ]; then      # inner half of the locked build below
    image_ok && exit 0
    echo "run.sh: building $img" >&2
    podman build -q -t "$img" --label "breadbin.ci.src=$src" -f "$here/Containerfile" "$here" >&2
    exit $?
fi
if ! image_ok; then
    "$repo/tools/with-lock" -r image -- "$0" --build-image
fi
if [ ! -f "$roms/C64/kernal-901227-03.bin" ]; then
    echo "run.sh: ROM dir empty, fetching ROMs into $roms (network)" >&2
    "$repo/tools/setup-vice-roms.sh" "$roms" >&2
fi
mem=
[ -n "${BREADBIN_CI_MEM:-}" ] && mem="--memory=$BREADBIN_CI_MEM"
broker=${BREADBIN_BROKER:-}
case $broker in
    127.0.0.1:*|localhost:*) broker=host.containers.internal:${broker#*:} ;;
esac
viceargs=${BREADBIN_VICE_ARGS:-}
jiffy=${BREADBIN_CI_JIFFY:-}
if [ -n "$jiffy" ]; then
    for f in JiffyDOS-C64.bin JiffyDOS_1541-II.bin; do
        [ -f "$jiffy/$f" ] || { echo "run.sh: $jiffy/$f not found" >&2; exit 2; }
    done
    viceargs="-kernal /jiffy/JiffyDOS-C64.bin -dos1541 /jiffy/JiffyDOS_1541-II.bin -dos1541II /jiffy/JiffyDOS_1541-II.bin $viceargs"
fi
# A run that starts VICE takes its own slot (tools/with-lock: up to 6 at once,
# BREADBIN_VICE_SLOTS); BREADBIN_CI_EXCLUSIVE=1 takes them all, for runs whose wall-clock
# data matters. A caller that already holds the lock passes straight through. Build-only
# targets (test-host, size, all, clean) take no slot; any other target is assumed to
# start VICE.
lockbin=
for t in "$@"; do
    case $t in
        test-host|size|all|clean|T=*|CACHE=*) ;;
        *) lockbin="$repo/tools/with-lock" ;;
    esac
done
name="breadbin-ci-run-$$"
# The command line is built backwards in the positional parameters (the make targets are
# already there), so that no word is split and optional parts are simply left out.
set -- "$img" "$@"
[ -n "$viceargs" ] && set -- -e "BREADBIN_VICE_ARGS=$viceargs" "$@"
[ -n "$jiffy" ] && set -- -v "$jiffy:/jiffy:ro" "$@"
[ -n "$broker" ] && set -- -e "BREADBIN_BROKER=$broker" "$@"
set -- -v "$repo:/src:ro" -v "$roms:/roms:ro" "$@"
[ -n "$mem" ] && set -- "$mem" "$@"
set -- podman run --rm --init --name "$name" "$@"
if [ -n "$lockbin" ]; then
    if [ "${BREADBIN_CI_EXCLUSIVE:-}" = 1 ]; then set -- "$lockbin" -x -- "$@"; else set -- "$lockbin" -- "$@"; fi
fi
# Not exec'd: a signal removes the container, otherwise podman's own helper (its own
# session) would keep the VICE running after the lock holder died, outside the lock. A
# SIGKILL cannot be trapped; `podman rm -f breadbin-ci-run-<pid>` removes what it leaves.
cleanup() { podman rm -f "$name" >/dev/null 2>&1 || true; }
"$@" &
pid=$!
trap 'kill "$pid" 2>/dev/null; cleanup; exit 143' TERM
trap 'kill "$pid" 2>/dev/null; cleanup; exit 130' INT
trap 'kill "$pid" 2>/dev/null; cleanup; exit 129' HUP
rc=0
wait "$pid" || rc=$?
exit $rc
