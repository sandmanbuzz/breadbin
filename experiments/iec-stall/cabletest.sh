#!/bin/bash
# N DMA boots of one kernel on the physical drive (stock KERNAL host, clean bus), appended to a results file under a label.
# For hardware changes (cable, IEC socket, drive power): change one thing, run this with a label saying what, compare.
#   BREADBIN_ULTIMATE=host SCRATCH=dir tools/with-lock -r ultimate -- experiments/iec-stall/cabletest.sh LABEL [N] [IMAGE.prg]
label=$1; n=${2:-6}; img=${3:-$SCRATCH/old.prg}; H=$BREADBIN_ULTIMATE; here=$(cd "$(dirname "$0")" && pwd)
res=${SCRATCH:-/tmp}/cabletest-results.txt
put(){ curl -s -m10 -X PUT "http://$H/v1/configs/$1?value=$2" >/dev/null; }
K="C64%20and%20Cartridge%20Settings/Kernal%20ROM"
reboot(){ curl -s -m10 -X PUT "http://$H/v1/machine:reboot" >/dev/null; sleep 15; }
restore(){ put $K "JiffyDOS-C64.bin"; put "Drive%20A%20Settings/Drive" Enabled; put "SoftIEC%20Drive%20Settings/IEC%20Drive" Enabled; reboot; }
trap restore EXIT
put "Drive%20A%20Settings/Drive" Disabled; put "SoftIEC%20Drive%20Settings/IEC%20Drive" Disabled; put $K ""; reboot
pass=0
for i in $(seq $n); do
  r=$(timeout 230 python3 "$here/plainboot.py" "$img" 2>&1 | tail -1); echo "boot $i: ${r:0:70}"
  case "$r" in OK*) pass=$((pass+1));; esac
done
echo "RESULT $label: $pass of $n passed" | tee -a "$res"
