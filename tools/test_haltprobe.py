"""Host tests for experiments/iec-stall/haltprobe.py against the fake Ultimate.

The fake is a byte array, not a C64: a stand-in thread plays the probe's part of the contract (RUNNING
once SYS is typed, CLEAR, STOP -> DONE, counts in the results block). What this cannot show: that the
6502 program measures anything (tests/haltprobe_vice.py does, in VICE), or what the real firmware's
DMA does to the CPU (hardware only).
"""
import os
import shutil
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", "iec-stall"))
import fake_ultimate  # noqa: E402
import haltprobe as hp  # noqa: E402
from ultimate import Ultimate  # noqa: E402


class StandIn(threading.Thread):
    def __init__(self, fake, with_reu):
        super().__init__(daemon=True)
        self.fake, self.with_reu, self.go = fake, with_reu, True
        self.clears = 0

    def run(self):
        ram = self.fake.ram
        while self.go:
            time.sleep(0.01)
            with self.fake.lock:
                if ram[0xC6] and not ram[hp.RES + 0x0D]:        # "sys49152" typed: start
                    ram[0xC6] = 0
                    ram[hp.RES + 0x0C] = 56
                    ram[hp.RES + 0x0D] = 1
                    ram[hp.RES + 1] = 1 if self.with_reu else 0
                if not ram[hp.RES + 0x0D]:
                    continue
                if ram[hp.CLEAR]:
                    ram[hp.CLEAR] = 0
                    self.clears += 1
                    ram[hp.RES + 0x10:hp.RES + 0x34] = bytes(0x24)
                n = int.from_bytes(ram[hp.RES + 0x10:hp.RES + 0x14], "little") + 100
                ram[hp.RES + 0x10:hp.RES + 0x14] = n.to_bytes(4, "little")
                if ram[hp.MODE] & hp.FLAG_REU:
                    ram[hp.RES + 0x24:hp.RES + 0x28] = (5).to_bytes(4, "little")      # bucket 5 (201-400)
                    ram[hp.RES + 2] = 7
                if ram[hp.STOP]:
                    ram[hp.RES] = 1
                    ram[hp.RES + 0x0D] = 0
                    self.go = False


@unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "needs cc65")
class Driver(unittest.TestCase):
    def go(self, with_reu, **kw):
        fake = fake_ultimate.FakeUltimate().start()
        self.addCleanup(fake.stop)
        t = StandIn(fake, with_reu)
        t.start()
        self.addCleanup(setattr, t, "go", False)
        u = Ultimate(fake.host, port=fake.port)
        out = []
        rows = hp.run(u, idle=0.3, r1=0.5, r01=0.5, r1000=0.5, reu=0.3, boot_wait=0.0, settle=0.1,
                      say=out.append, **kw)
        return fake, t, rows, out

    def test_five_arms_and_resume(self):
        fake, t, rows, out = self.go(True)
        self.assertEqual([r["name"] for r in rows], ["1 idle", "2 1B/1s", "3 1B/0.1s", "4 1000B/2s", "5 REU"])
        self.assertFalse(fake.paused)                                   # left resumed
        self.assertEqual(fake.ram[hp.RES], 1)                           # stopped, DONE
        self.assertEqual(bytes(fake.ram[0xC000:0xC000 + 8]), hp.assemble()[:8])    # the probe was loaded
        self.assertEqual(t.clears, 5)                                   # results cleared at the start of each arm
        self.assertEqual(rows[0]["requests"], 0)                        # arm 1: no REST traffic
        self.assertGreaterEqual(rows[2]["requests"], 3)                 # 0.1 s arm: many reads
        self.assertGreaterEqual(rows[1]["requests"], 1)
        self.assertTrue(all(r["clear_acked"] for r in rows))
        self.assertEqual(rows[4]["buckets"][5], 5)
        self.assertEqual(rows[4]["xfers"], 7)
        self.assertIn("5 REU", out[-1])
        self.assertIn("201-400", out[-1])

    def test_request_counts(self):
        fake, t, rows, out = self.go(False)
        n = sum(1 for m, path in fake.requests if path.endswith("machine:readmem"))
        self.assertGreater(n, rows[1]["requests"] + rows[2]["requests"] + rows[3]["requests"])

    def test_no_reu_is_skipped(self):
        fake, t, rows, out = self.go(False)
        self.assertIn("skipped", rows[4])
        self.assertFalse(fake.paused)

    def test_machine_resumed_when_the_probe_never_starts(self):
        fake = fake_ultimate.FakeUltimate().start()         # no stand-in: RUNNING never appears
        self.addCleanup(fake.stop)
        u = Ultimate(fake.host, port=fake.port)
        with self.assertRaisesRegex(RuntimeError, "did not start"):
            hp.run(u, boot_wait=0.0, code=b"\x00", say=lambda *a: None, start_timeout=0.5)
        self.assertFalse(fake.paused)


if __name__ == "__main__":
    unittest.main()
