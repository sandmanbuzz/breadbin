#!/bin/sh
# Run make targets from the repo inside a fresh breadbin-ci container.
#   tools/ci/run.sh test-host
#   tools/ci/run.sh test-smoke
#   tools/ci/run.sh test-only T="tests.test_system.Boot.test_02_echo"
# Env: BREADBIN_CI_ROMS   host ROM dir (default ~/.cache/breadbin-ci/roms; filled by
#                         tools/setup-vice-roms.sh when empty: needs network once)
#      BREADBIN_CI_IMAGE  image name (default breadbin-ci; built if missing)
#      BREADBIN_CI_MEM    optional container memory limit, e.g. 1500m
#      BREADBIN_BROKER    passed through (host.containers.internal rewrite for localhost)
# The repo is mounted read-only and copied inside, so concurrent runs do not collide.
# Exit code is make's. Set BREADBIN_CI_KEEP_BUILD=<dir> to copy build/ out afterwards.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
img=${BREADBIN_CI_IMAGE:-breadbin-ci}
roms=${BREADBIN_CI_ROMS:-$HOME/.cache/breadbin-ci/roms}
[ $# -gt 0 ] || { echo "usage: run.sh <make target...>" >&2; exit 2; }

if ! podman image exists "$img"; then
    echo "run.sh: building $img" >&2
    podman build -q -t "$img" -f "$here/Containerfile" "$here" >&2
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
# shellcheck disable=SC2086
exec podman run --rm --init --name "breadbin-ci-run-$$" $mem \
    -v "$repo:/src:ro" -v "$roms:/roms:ro" \
    ${broker:+-e "BREADBIN_BROKER=$broker"} \
    "$img" "$@"
