#!/usr/bin/env python3
"""Run sweep.prg under VICE (tools/vicetest.py; run it in the CI container) and print the
result block: failures, finished magic, case count, then failing ids and got-bytes."""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "tools"))
from vicetest import Vice
with Vice(os.environ.get("PRG") or os.path.join(here, "sweep.prg")) as v:
    v.wait_for("sweep ", timeout=120)
    print([l for l in v.screen().splitlines() if "sweep" in l.lower()])
    print("hdr", v.mem(0xC000, 0xC003)); print("ids", v.mem(0xC010, 0xC02F)); print("got", v.mem(0xC050, 0xC07F))
