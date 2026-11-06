#!/bin/bash
# Write a disk image to the physical 1541 (device 8) through the Ultimate, one command.
#
#   tools/with-lock -r ultimate -- ... (this script takes the lock itself; you do not need to)
#   BREADBIN_ULTIMATE=HOST NIBBLER=PATH experiments/iec-stall/write-physical.sh IMAGE.d64
#
# IMAGE.d64: a local file. Its sha256 must match IMAGE_SHA (default: the build of main 9cab610).
# The physical disk is OVERWRITTEN with the image. Needs the owner's go for each write.
# Takes about 50 s on the bench (owner's observation); the copy waits up to 1500 s.
#
# Preflight, in order, before anything changes on the Ultimate:
#   1 IMAGE and NIBBLER are readable; NIBBLER's sha256 is NIBBLER_SHA (30808e1f...)
#   2 IMAGE's sha256 is IMAGE_SHA
#   3 BREADBIN_ULTIMATE is set, and the machine answers /v1/version
# Then, under the ultimate lock: config up (Software IEC off, stock KERNAL, drive A on bus 9 with
# the image read-only), the nibbler copy 8 -> 9 and back, and config down (JiffyDOS KERNAL,
# Software IEC on) in an EXIT trap, so the config comes back even when the copy fails.
#
# Exit status: 0 written and restored; 1 refused in preflight (nothing changed); 2 the copy or
# restore failed (read the last lines printed: the config was put back by the trap).
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
# the Ultimate address comes from the environment, else from .breadbin-local.env at the repo root (gitignored)
[ -n "${BREADBIN_ULTIMATE:-}" ] || [ ! -r "$(cd "$(dirname "$0")/../.." && pwd)/.breadbin-local.env" ] || . "$(cd "$(dirname "$0")/../.." && pwd)/.breadbin-local.env"

IMAGE=${1:-}
IMAGE_SHA=${IMAGE_SHA:-f6efbf78418ce18f30956b6102d25c9327b184a392413dc5ba44746964bc5f90}
NIBBLER_SHA=30808e1f581d6427f839e4fce96bd46762c29c6343c09ec5d37ea4c4881fcfe5
NIBBLER=${NIBBLER:-$here/keym.d.nibbler.prg}

refuse() { echo "write-physical: REFUSED: $*" >&2; exit 1; }
[ -n "$IMAGE" ] || refuse "usage: write-physical.sh IMAGE.d64 (see the header)"
[ -r "$IMAGE" ] || refuse "cannot read IMAGE: $IMAGE"
[ -r "$NIBBLER" ] || refuse "cannot read NIBBLER: $NIBBLER (set NIBBLER=path to keym.d.nibbler.prg)"
got=$(sha256sum "$NIBBLER" | cut -d' ' -f1)
[ "$got" = "$NIBBLER_SHA" ] || refuse "NIBBLER sha256 is $got, expected $NIBBLER_SHA (wrong program)"
got=$(sha256sum "$IMAGE" | cut -d' ' -f1)
[ "$got" = "$IMAGE_SHA" ] || refuse "IMAGE sha256 is $got, expected $IMAGE_SHA (set IMAGE_SHA for another image)"
[ -n "${BREADBIN_ULTIMATE:-}" ] || refuse "BREADBIN_ULTIMATE is not set (the Ultimate's address; keep it out of the repo)"

# the lock: re-run this script under it, once (the guard stops a loop)
if [ -z "${BREADBIN_WRITE_LOCKED:-}" ]; then
    export BREADBIN_WRITE_LOCKED=1 NIBBLER IMAGE_SHA
    exec "$root/tools/with-lock" -r ultimate -- "$0" "$IMAGE"
fi

echo "write-physical: lock held; reachability"
curl -s -m 10 "http://$BREADBIN_ULTIMATE/v1/version" >/dev/null || { echo "write-physical: REFUSED: the Ultimate does not answer" >&2; exit 1; }

cd "$here" || exit 2
restore() { echo "write-physical: restoring config (JiffyDOS KERNAL, Software IEC on)"; ./nibsetup.sh down; }
trap restore EXIT
echo "write-physical: config up and writing $(basename "$IMAGE")"
./nibsetup.sh up "$IMAGE" || { echo "write-physical: FAILED at config up" >&2; exit 2; }
NIBBLER="$NIBBLER" python3 nibcopy.py "$IMAGE" || { echo "write-physical: FAILED in the copy (config restored by the trap)" >&2; exit 2; }
echo "write-physical: DONE (the copy printed its directory above; check it says 'blocks free' as the image's BAM has it)"
