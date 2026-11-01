"""First integration run of the real kernel's UCI v1 on the Ultimate: boot build/breadbin.d64 from the
emulated drive A (bus 9; the physical 1541 stays on 8) by DMA with "DMA Load Mimics ID" = 9, log in
and run the shell commands given as arguments, printing each screen.

    BREADBIN_ULTIMATE=host python3 ucirun.py 'mount uci /u' 'ls /u' ...

The caller restores "DMA Load Mimics ID" to 8 (ucirun.sh does). Needs tools/with-lock -r ultimate."""
import os
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "tools"))
from ultimatetest import UltimateTarget  # noqa: E402

root = os.path.join(here, "..", "..")
t = UltimateTarget()
u = t.u
u.resume()
u.mount("a", open(os.path.join(root, "build", "breadbin.d64"), "rb").read(), type="d64", mode="unlinked", name="breadbin.d64")
u.reset()
time.sleep(10)
u.run_prg(open(os.path.join(root, "build", "breadbin.prg"), "rb").read())
time.sleep(25)                       # no DMA read during the root mount
t.wait_shell(timeout=120)
for c in sys.argv[1:]:
    print("$", c, flush=True)
    print(t.run(c, timeout=60), flush=True)
