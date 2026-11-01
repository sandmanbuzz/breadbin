#!/bin/bash
# ucirun.py with the config it needs, restored afterwards. Run under tools/with-lock -r ultimate.
H=${BREADBIN_ULTIMATE:?}; here=$(cd "$(dirname "$0")" && pwd)
C="C64%20and%20Cartridge%20Settings/DMA%20Load%20Mimics%20ID%3A"
put(){ curl -s -m10 -X PUT "http://$H/v1/configs/$1?value=$2" >/dev/null; }
trap 'put $C 8; echo restored' EXIT
put $C 9
python3 "$here/ucirun.py" "$@"
