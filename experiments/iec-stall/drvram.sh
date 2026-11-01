#!/bin/bash
# drvram.py on the stock KERNAL with a clean bus, restoring the Ultimate's configuration afterwards.
#   BREADBIN_ULTIMATE=host SCRATCH=dir tools/with-lock -r ultimate -- experiments/iec-stall/drvram.sh
H=$BREADBIN_ULTIMATE; here=$(cd "$(dirname "$0")" && pwd)
put(){ curl -s -m10 -X PUT "http://$H/v1/configs/$1?value=$2" >/dev/null; }
K="C64%20and%20Cartridge%20Settings/Kernal%20ROM"
reboot(){ curl -s -m10 -X PUT "http://$H/v1/machine:reboot" >/dev/null; sleep 15; }
restore(){ put $K "JiffyDOS-C64.bin"; put "Drive%20A%20Settings/Drive" Enabled; put "SoftIEC%20Drive%20Settings/IEC%20Drive" Enabled; reboot; echo "restored"; }
trap restore EXIT
put "Drive%20A%20Settings/Drive" Disabled; put "SoftIEC%20Drive%20Settings/IEC%20Drive" Disabled; put $K ""; reboot
python3 "$here/drvram.py"
