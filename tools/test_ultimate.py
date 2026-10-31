"""Host tests: the Ultimate REST client and test backend, against a fake server.

No hardware or emulator. They check our side of the protocol as documented; what
the real firmware does is for the hardware session to confirm (docs/hardware-notes.md).
"""
import threading
import time
import unittest

import fake_ultimate
import ultimate
import ultimatetest
from ultimate import Ultimate, UltimateError
from ultimatetest import UltimateTarget, keys_for, petscii


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = fake_ultimate.FakeUltimate().start()
        self.addCleanup(self.fake.stop)
        self.u = Ultimate(self.fake.host, port=self.fake.port)


class Client(Base):
    def test_info_and_version(self):
        self.assertEqual(self.u.version()["version"], "0.1")
        self.assertIn("Ultimate", self.u.info()["product"])

    def test_memory_round_trip(self):
        self.u.writemem(0x0400, b"hello")                      # small: PUT with hex
        self.assertEqual(self.u.readmem(0x0400, 5), b"hello")
        big = bytes(range(256)) * 2
        self.u.writemem(0x2000, big)                           # large: POST body
        self.assertEqual(self.u.readmem(0x2000, 512), big)
        self.assertEqual(self.u.readmem(0xFFFF, 1), b"\x00")

    def test_memory_ranges_are_checked(self):
        with self.assertRaises(ValueError):
            self.u.readmem(0xFFFF, 2)
        with self.assertRaises(ValueError):
            self.u.writemem(0xFFFF, b"ab")

    def test_password(self):
        with fake_ultimate.FakeUltimate(password="secret").start() as f:
            with self.assertRaisesRegex(UltimateError, "403"):
                Ultimate(f.host, port=f.port).info()
            self.assertIn("product", Ultimate(f.host, port=f.port, password="secret").info())

    def test_errors_in_the_reply_raise(self):
        with self.assertRaises(UltimateError):
            self.u.call("PUT", "/v1/machine:nosuchthing")

    def test_unreachable_host_raises(self):
        with self.assertRaises(UltimateError):
            Ultimate("127.0.0.1", port=1, timeout=1).info()

    def test_machine_control(self):
        self.u.reset()
        self.assertEqual(self.fake.resets, 1)
        self.u.pause()
        self.assertTrue(self.fake.paused)
        self.u.resume()
        self.assertFalse(self.fake.paused)
        self.assertEqual(len(self.u.menu_screen()[0]), 1000)

    def test_keyboard_events(self):
        self.u.keyboard(["left_shift", "1"])
        self.u.keyboard(["a"], "press")
        self.u.release_all()
        self.assertEqual([e["kind"] for e in self.fake.events], ["keyboard", "keyboard", "release_all"])
        self.assertEqual(self.fake.events[0]["inputs"], ["left_shift", "1"])

    def test_input_is_split_to_64_events(self):
        self.u.input([{"kind": "keyboard", "inputs": ["a"], "transition": "tap"}] * 130)
        self.assertEqual(len(self.fake.events), 130)
        posts = [r for r in self.fake.requests if r[1] == "/v1/machine:input"]
        self.assertEqual(len(posts), 3)

    def test_input_is_split_to_4096_bytes(self):
        ev = {"kind": "keyboard", "inputs": list("abcdefgh"), "transition": "tap"}
        self.u.input([ev] * 64)                 # 64 events, but over 4096 bytes of JSON
        self.assertEqual(len(self.fake.events), 64)
        self.assertGreater(len([r for r in self.fake.requests if r[1] == "/v1/machine:input"]), 1)

    def test_mount_multipart_and_raw(self):
        img = b"D64" * 100
        self.u.mount("a", img, mode="unlinked")
        raw = Ultimate(self.fake.host, port=self.fake.port, attach="raw")
        raw.mount("b", img, mode="readonly")
        a, b = self.fake.mounts
        self.assertEqual((a["drive"], a["how"], a["mode"], a["type"], a["data"]),
                         ("a", "multipart", "unlinked", "d64", img))
        self.assertEqual((b["drive"], b["how"], b["mode"], b["data"]), ("b", "raw", "readonly", img))

    def test_mount_a_file_on_the_ultimate(self):
        self.u.mount("a", "/USB0/breadbin.d64")
        self.assertEqual(self.fake.mounts[0]["image"], "/USB0/breadbin.d64")

    def test_run_prg_loads_at_its_address(self):
        self.u.run_prg(b"\x00\xc0\xa9\x05\x60")
        self.assertEqual(bytes(self.fake.ram[0xC000:0xC003]), b"\xa9\x05\x60")
        self.assertEqual(self.fake.runs[0]["how"], "multipart")
        self.assertEqual(self.fake.resets, 1)

    def test_streams(self):
        self.u.stream_start("video", "192.168.1.2:11000")
        self.assertEqual(self.fake.streams, {"video": "192.168.1.2:11000"})
        self.u.stream_stop("video")
        self.assertEqual(self.fake.streams, {})


class Keys(unittest.TestCase):
    def test_keys_for(self):
        self.assertEqual(keys_for("a"), ["a"])
        self.assertEqual(keys_for("A"), ["left_shift", "a"])
        self.assertEqual(keys_for("!"), ["left_shift", "1"])
        self.assertEqual(keys_for("|"), ["left_shift", "minus"])
        self.assertEqual(keys_for("\n"), ["return"])
        self.assertEqual(keys_for(" "), ["space"])
        with self.assertRaises(ValueError):
            keys_for("{")

    def test_keys_are_all_valid_ultimate_names(self):
        valid = set(fake_ultimate.KEYS)
        for ch in "abcxyz0189 \n+-.,:;=/*@_^!\"#$%&'()<>?[]|ABZ\x08":
            self.assertLessEqual(set(keys_for(ch)), valid, ch)
        for names in ultimatetest.XNAMES.values():
            self.assertLessEqual(set(names), valid)

    def test_petscii(self):
        self.assertEqual([petscii(c) for c in "aZ1\n|"], [0x41, 0xDA, 0x31, 0x0D, 0xDD])


class Target(Base):
    def target(self):
        return UltimateTarget(client=self.u)

    def drain(self):
        """Stand in for the C64 consuming keys: empty the buffer, record what was in it."""
        seen = bytearray()
        stop = threading.Event()

        def run():
            while not stop.is_set():
                with self.fake.lock:                  # a paused C64 does not run
                    n = self.fake.ram[0xC6]
                    if n and not self.fake.paused:
                        seen.extend(self.fake.ram[0x0277:0x0277 + n])
                        self.fake.ram[0xC6] = 0
                time.sleep(0.01)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join()))
        return seen

    def test_keybuf_writes_the_stock_buffer(self):
        self.fake.ram[0x0289] = 10
        self.target().keybuf(b"\x03\x91")
        self.assertEqual(bytes(self.fake.ram[0x0277:0x0279]), b"\x03\x91")
        self.assertEqual(self.fake.ram[0xC6], 2)
        self.assertFalse(self.fake.paused)

    def test_type_chunks_and_waits_for_room(self):
        self.fake.ram[0x0289] = 10
        seen = self.drain()
        self.target().type("echo hello world\n")
        deadline = time.time() + 5
        while len(seen) < 17 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(bytes(seen), bytes(petscii(c) for c in "echo hello world\n"))

    def test_keybuf_times_out_if_nothing_drains(self):
        self.fake.ram[0x0289] = 10
        self.fake.ram[0xC6] = 10
        with self.assertRaises(TimeoutError):
            self.target().keybuf(b"x", timeout=0.3)
        self.assertFalse(self.fake.paused)

    def test_screen_is_read_from_screen_ram(self):
        self.fake.poke(0x0400, b"\x20" * 1000)                      # blank screen
        self.fake.poke(0x0400, bytes([0x2F, 0x20, 0x24]))          # "/ $"
        self.fake.poke(0x0400 + 40, bytes([0x08, 0x09]))            # "hi"
        lines = self.target().screen_lines()
        self.assertEqual(lines[0], "/ $")
        self.assertEqual(lines[1], "hi")

    def test_mem_is_inclusive_like_vice(self):
        self.fake.poke(0x0100, b"\x01\x02\x03")
        self.assertEqual(self.target().mem(0x0100, 0x0102), [1, 2, 3])

    def test_real_keys(self):
        t = self.target()
        t.xkey("a", "Return", "exclam", delay=0)
        t.xtype("Hi", delay=0)
        t.xdown("Shift_L")
        t.xup("Shift_L")
        got = [(e["inputs"], e["transition"]) for e in self.fake.events]
        self.assertEqual(got, [
            (["a"], "tap"), (["return"], "tap"), (["left_shift", "1"], "tap"),
            (["left_shift", "h"], "tap"), (["i"], "tap"),
            (["left_shift"], "press"), (["left_shift"], "release")])

    def test_boot_resumes_a_machine_left_paused(self):
        import os
        import tempfile
        self.u.pause()
        self.u.reset()
        self.assertTrue(self.fake.paused)       # as on hardware: a reset keeps the pause
        self.fake.ram[0x0289] = 10
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.poke(0x0400, bytes([0x12, 0x05, 0x01, 0x04, 0x19, 0x2E]))
        self.drain()
        with tempfile.NamedTemporaryFile(suffix=".d64", delete=False) as f:
            f.write(b"X")
        self.addCleanup(os.unlink, f.name)
        self.fake.paused_at_reset.clear()
        UltimateTarget(f.name, client=self.u, settle=0)
        self.assertEqual(self.fake.paused_at_reset, [False])    # the pause did not reach the reset

    def test_boot_mounts_resets_and_types_the_load_command(self):
        import os
        import tempfile
        self.fake.ram[0x0289] = 10
        # a screen that already says "ready." so the waits pass
        text = bytes([0x12, 0x05, 0x01, 0x04, 0x19, 0x2E])         # "ready."
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.poke(0x0400, text)
        seen = self.drain()
        with tempfile.NamedTemporaryFile(suffix=".d64", delete=False) as f:
            f.write(b"IMG" * 50)
        self.addCleanup(os.unlink, f.name)
        UltimateTarget(f.name, client=self.u, settle=0)
        deadline = time.time() + 5
        want = bytes(petscii(c) for c in 'load"*",8,1\nrun\n')
        while len(seen) < len(want) and time.time() < deadline:
            time.sleep(0.05)
        m = self.fake.mounts[0]
        self.assertEqual((m["drive"], m["mode"], m["data"]), ("a", "unlinked", b"IMG" * 50))
        self.assertGreaterEqual(self.fake.resets, 1)
        self.assertEqual(bytes(seen), want)


if __name__ == "__main__":
    unittest.main()
