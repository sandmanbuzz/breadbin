#!/bin/bash
# Put the Ultimate in the state the nibbler test needs (stock KERNAL, Software IEC off, a CBM disk image read-only in
# drive A on bus 9) or put it back. Call under tools/with-lock -r ultimate, by hand, around the steps in nibtest.py.
#   BREADBIN_ULTIMATE=host nibsetup.sh up IMAGE_PATH_ON_THE_ULTIMATE | nibsetup.sh down
H=${BREADBIN_ULTIMATE:?}; here=$(cd "$(dirname "$0")" && pwd)
put(){ curl -s -m10 -X PUT "http://$H/v1/configs/$1?value=$2" >/dev/null; }
K="C64%20and%20Cartridge%20Settings/Kernal%20ROM"
reboot(){ curl -s -m10 -X PUT "http://$H/v1/machine:reboot" >/dev/null; sleep 15; }
case $1 in
up) export HERE="$here"; put "SoftIEC%20Drive%20Settings/IEC%20Drive" Disabled; put $K ""; reboot
    python3 - "$2" <<'P'
import os, sys
sys.path.insert(0, os.environ.get("HERE", "."))
from bench_basic import u
u.resume()
u.mount("a", sys.argv[1], type="d64", mode="readonly")
print("drive A:", [d["a"] for d in u.drives()["drives"] if "a" in d][0])
P
    ;;
down) put $K "JiffyDOS-C64.bin"; put "SoftIEC%20Drive%20Settings/IEC%20Drive" Enabled; reboot; echo "restored: JiffyDOS KERNAL, Software IEC on" ;;
*) echo "usage: nibsetup.sh up IMAGE | down" >&2; exit 2 ;;
esac
