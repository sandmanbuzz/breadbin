#!/bin/bash
# Regression bisect on the physical drive: build COMMIT, write its disk image onto the physical 1541 with
# mcdup (stock KERNAL host, clean bus), then boot its kernel N times by DMA and count the stalls.
#   BREADBIN_ULTIMATE=host SCRATCH=dir tools/with-lock -r ultimate -- experiments/iec-stall/bisect.sh COMMIT [N]
# Needs: cc65, the repository (it adds a worktree under $SCRATCH), the drive's disk already formatted.
commit=$1; n=${2:-5}; H=$BREADBIN_ULTIMATE; here=$(cd "$(dirname "$0")" && pwd); repo=$(cd "$here/../.." && pwd)
S=${SCRATCH:-/tmp}; w="$S/bisect-$commit"
put(){ curl -s -m10 -X PUT "http://$H/v1/configs/$1?value=$2" >/dev/null; }
K="C64%20and%20Cartridge%20Settings/Kernal%20ROM"
reboot(){ curl -s -m10 -X PUT "http://$H/v1/machine:reboot" >/dev/null; sleep 15; }
restore(){ put $K "JiffyDOS-C64.bin"; put "SoftIEC%20Drive%20Settings/IEC%20Drive" Enabled; reboot; echo "restored"; }
trap restore EXIT
git -C "$repo" worktree add -q --detach "$w" "$commit" || exit 1
(cd "$w" && make 2>&1 | tail -1) || exit 1
cp "$w/build/breadbin.prg" "$S/bis-$commit.prg"; cp "$w/build/kernel.lbl" "$S/bis-$commit.lbl" 2>/dev/null
cp "$w/build/breadbin.d64" "$S/bis-$commit.d64"
git -C "$repo" worktree remove --force "$w"
put "SoftIEC%20Drive%20Settings/IEC%20Drive" Disabled; put $K ""; reboot
echo "== $commit: writing its image onto the physical disk"
python3 "$here/mcdup.py" --dst 8 --image "$S/bis-$commit.d64" --label "BB ${commit:0:7}" || { echo "== $commit: COPY NOT CLEAN, not booting"; exit 1; }
echo "== $commit: $n boots, stock KERNAL host, clean bus"
rm -f "$S/bis-$commit.prg.stall"
for i in $(seq $n); do echo -n "boot $i: "; timeout 230 python3 "$here/plainboot.py" "$S/bis-$commit.prg" 2>&1 | tail -1; done
