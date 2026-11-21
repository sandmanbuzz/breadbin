#!/usr/bin/env python3
"""Type text into the running machine (key buffer by DMA, bus-idle gated). \\n, \\x0b etc. in an argument are decoded.
    BREADBIN_ULTIMATE=host tools/with-lock -r ultimate -- python3 experiments/con80/hw_type.py 'root\\n'"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
from ultimatetest import UltimateTarget
v = UltimateTarget()
for s in sys.argv[1:]:
    v.type(s.encode().decode("unicode_escape"))
print("typed")
