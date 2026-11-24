"""Vice._cmd and Vice.mem against a fake remote monitor (no emulator): the answer ends at its
prompt, not after a timeout; `x` returns at once; m output parses; a bad answer falls back
to the save path. The fake follows what VICE 3.9's monitor does: a command that arrives while
the emulator runs prints a prompt first; x leaves the monitor silently; an unknown command
echoes itself in an error block."""
import os
import re
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vicetest  # noqa: E402


class FakeMonitor:
    def __init__(self, ram, delay=0.0, broken_m=False):
        self.ram, self.delay, self.broken_m = ram, delay, broken_m
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.running = False                       # a fresh monitor is open: the emulator is paused
        self.log = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        c, _ = self.srv.accept()
        f = c.makefile("rb")
        for raw in f:
            cmd = raw.decode().strip()
            self.log.append(cmd)
            out = ""
            if self.running and cmd != "x":
                out += "(C:$c4a9) "                 # entry prompt: the emulator was running
            if cmd == "x":
                out += "(C:$a5bb) " if self.running else ""
                self.running = True
                c.sendall(out.encode())
                continue
            self.running = False
            time.sleep(self.delay)
            m = re.match(r"m ([0-9a-f]{4}) ([0-9a-f]{4})$", cmd)
            if m and not self.broken_m:
                a, b = int(m.group(1), 16), int(m.group(2), 16)
                for row in range(a, b + 1, 16):
                    chunk = self.ram[row:min(row + 16, b + 1)]
                    groups = ["  ".join(" ".join(f"{x:02x}" for x in chunk[i:i + 4]) for i in range(0, len(chunk), 4))]
                    text = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
                    out += f">C:{row:04x}  {groups[0]:<50}   {text}\n"
                out += f"(C:${b + 1:04x}) "
            elif cmd.startswith("keybuf"):
                out += "(C:$a3f0) "
            else:
                out += f"ERROR -- Wrong syntax:\n  {cmd}\n  {'^':>{len(cmd) + 1}}\n(C:$c4ad) "
            try:
                c.sendall(out.encode())
            except OSError:
                return                              # the client hung up


def vice_on(mon):
    v = vicetest.Vice.__new__(vicetest.Vice)      # no emulator: only the socket side
    v.sock = socket.create_connection(("127.0.0.1", mon.port), timeout=2)
    return v


class Monitor(unittest.TestCase):
    def test_answer_ends_on_its_prompt_not_after_a_timeout(self):
        mon = FakeMonitor(bytes(range(256)) * 8)
        v = vice_on(mon)
        v._cmd("x")                                 # the emulator runs: the answer starts with an entry prompt
        t = time.time()
        out = v._cmd("keybuf \\x0d")
        self.assertEqual(out, "(C:$c4a9) (C:$a3f0) ")
        self.assertLess(time.time() - t, 0.3)       # the old read always took 0.55 s

    def test_x_returns_at_once_and_sends_nothing_back(self):
        mon = FakeMonitor(bytes(256))
        v = vice_on(mon)
        t = time.time()
        self.assertEqual(v._cmd("x"), "")
        self.assertLess(time.time() - t, 0.1)
        t = time.time()
        v._cmd("x", wait=0.2)                        # the caller's pacing is honoured
        self.assertGreaterEqual(time.time() - t, 0.2)

    def test_second_x_is_not_sent_and_leaves_no_stale_prompt(self):
        mon = FakeMonitor(bytes(range(256)) * 8)
        v = vice_on(mon)
        v._cmd("x")
        v._cmd("x")
        v._cmd("x")
        time.sleep(0.1)
        self.assertEqual(mon.log, ["x"])
        self.assertEqual(v.mem(0, 15), list(range(16)))

    def test_slow_command_is_waited_for(self):
        mon = FakeMonitor(bytes(256), delay=0.6)     # slower than any fixed read window
        v = vice_on(mon)
        v._cmd("x")
        out = v._cmd("keybuf a")
        self.assertIn("(C:$a3f0)", out)
        self.assertEqual(v._cmd("keybuf b"), "(C:$a3f0) ")   # nothing left over for the next

    def test_mem_parses_m_rows(self):
        ram = bytes((i * 7 + 3) & 255 for i in range(0x800))
        mon = FakeMonitor(ram)
        v = vice_on(mon)
        for a, b in ((0x0400, 0x07e7), (0x0001, 0x0001), (0x0010, 0x0025), (0x0000, 0x000f)):
            self.assertEqual(v.mem(a, b), list(ram[a:b + 1]), (a, b))
        self.assertFalse(any(c.startswith("save") for c in mon.log))
        # each memory read leaves the monitor, so the emulator runs between reads
        time.sleep(0.1)                              # x is not answered, so give the fake time to log it
        self.assertEqual(mon.log[-1], "x")

    def test_text_column_that_looks_like_hex_is_not_taken_for_bytes(self):
        ram = b"ab cd ef 12" + bytes(5) + b"ee"          # text column starts with hex-like words
        mon = FakeMonitor(ram)
        v = vice_on(mon)
        self.assertEqual(v.mem(0, 12), list(ram[:13]))

    def test_mem_falls_back_to_save_when_m_does_not_parse(self):
        mon = FakeMonitor(bytes(64), broken_m=True)
        v = vice_on(mon)
        calls = []
        v._mem_save = lambda a, b: calls.append((a, b)) or [0] * (b - a + 1)
        self.assertEqual(v.mem(0, 3), [0, 0, 0, 0])
        self.assertEqual(calls, [(0, 3)])

    def test_dead_connection_is_an_error_not_a_hang(self):
        mon = FakeMonitor(bytes(16))
        v = vice_on(mon)
        v.sock.close()
        with self.assertRaises(OSError):
            v._cmd("r")


if __name__ == "__main__":
    unittest.main()
