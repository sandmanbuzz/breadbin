#!/usr/bin/env python3
"""Run illegal.prg under VICE and print the result line. Needs tools/vicetest.py's environment."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
from vicetest import Vice
with Vice(os.path.join(os.path.dirname(os.path.abspath(__file__)), "illegal.prg")) as v:
    v.wait_for("illegal ops:", timeout=60)
    print([l for l in v.screen().splitlines() if "illegal" in l.lower()])
