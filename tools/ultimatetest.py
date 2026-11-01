#!/usr/bin/env python3
"""Drive a real Ultimate 64 (or C64 Ultimate) for the Breadbin tests.

Same interface as tools/vicetest.py's Vice, so a test can run on either:

    BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=192.168.1.64 \\
        python3 -m unittest tests.test_system.Boot.test_02_echo

    with UltimateTarget("build/breadbin.d64") as v:     # mounts, resets, boots
        v.wait_shell()
        print(v.run("echo hi"))

Two ways to type, as in Vice:
  type(text) / keybuf(bytes)   write PETSCII into the key buffer at $0277 by DMA
                               (what VICE's `keybuf` does; no key timing involved)
  xkey/xtype/xdown/xup         real key events through the Ultimate's keyboard
                               input (Ultimate 64 only), so the matrix scan runs

UNVERIFIED on hardware, to check first: that a "tap" is held long enough for the
60 Hz scan to see it; how DMA reads of $0001 behave; the upload encoding (see
tools/ultimate.py); the boot time. See docs/hardware-notes.md.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ultimate import KeyInjectionUnavailable, Ultimate  # noqa: E402
from vicetest import Target  # noqa: E402

KEYD, KEYCNT, KEYMAX = 0x0277, 0x00C6, 0x0289

# ASCII -> the keys to hold together (one tap) on a C64 keyboard
SHIFTED = {"!": "1", '"': "2", "#": "3", "$": "4", "%": "5", "&": "6", "'": "7", "(": "8",
           ")": "9", "<": "comma", ">": "period", "?": "slash", "[": "colon",
           "]": "semicolon", "|": "minus"}
PLAIN = {" ": "space", "\n": "return", "+": "plus", "-": "minus", ".": "period",
         ",": "comma", ":": "colon", ";": "semicolon", "=": "equals", "/": "slash",
         "*": "star", "@": "at", "\x08": "inst_del", "_": "arrow_left", "^": "arrow_up"}

# the X key names the keyboard tests use -> the keys to hold
XNAMES = {"Return": ["return"], "space": ["space"], "BackSpace": ["inst_del"],
          "Escape": ["run_stop"], "Tab": ["commodore"],
          "Shift_L": ["left_shift"], "Shift_R": ["right_shift"],
          "Control_L": ["ctrl"], "Control_R": ["ctrl"],
          "exclam": ["left_shift", "1"]}


def keys_for(ch):
    """The keys that type one ASCII character."""
    if ch in PLAIN:
        return [PLAIN[ch]]
    if ch in SHIFTED:
        return ["left_shift", SHIFTED[ch]]
    if ch.isdigit() or ("a" <= ch <= "z"):
        return [ch]
    if "A" <= ch <= "Z":
        return ["left_shift", ch.lower()]
    raise ValueError(f"no key for {ch!r}")


def petscii(ch):
    """The PETSCII code the keyboard driver produces for an ASCII character."""
    if ch == "\n":
        return 0x0D
    if ch == "\x08":
        return 0x14
    if ch == "|":
        return 0xDD
    if "a" <= ch <= "z":
        return ord(ch) - 0x20
    if "A" <= ch <= "Z":
        return ord(ch) + 0x80
    return ord(ch)


class UltimateTarget(Target):
    sees_cpu_port = False

    def __init__(self, image=None, host=None, password=None, persist=False,
                 boot_timeout=180, settle=2, client=None):
        """Mount `image` in drive A and boot it. persist=False mounts it so that
        writes are not written back to the file on the Ultimate ("unlinked")."""
        self.u = client or (Ultimate(host, password=password) if host else Ultimate.from_env())
        self.boot_timeout = boot_timeout
        self.settle = settle
        if image:
            self.boot(image, persist)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        try:
            self.u.release_all()
        except Exception:
            pass

    # ---- the interface Target needs
    def mem(self, start, end):
        return list(self.u.readmem(start, end - start + 1))

    def keybuf(self, data, timeout=30):
        """PETSCII bytes into the key buffer (waits for room). The machine is
        paused for the update so the keyboard driver cannot interleave."""
        data = bytes(data)
        deadline = time.time() + timeout
        while True:
            self.u.pause()
            try:
                n = self.u.readmem(KEYCNT, 1)[0]
                room = self.u.readmem(KEYMAX, 1)[0] - n
                if room >= len(data):
                    self.u.writemem(KEYD + n, data)
                    self.u.writemem(KEYCNT, bytes([n + len(data)]))
                    return
            finally:
                self.u.resume()
            if time.time() > deadline:
                raise TimeoutError("key buffer never drained")
            time.sleep(0.1)

    def type(self, text):
        """Like Vice.type: ASCII text into the key buffer, a few keys at a time."""
        codes = bytes(petscii(c) for c in text)
        for i in range(0, len(codes), 8):
            self.keybuf(codes[i:i + 8])

    # ---- real keystrokes
    def focus(self):
        """Nothing to focus; but real keystrokes must exist on this product."""
        try:
            self.u.release_all()
        except KeyInjectionUnavailable as e:
            raise unittest.SkipTest(str(e))

    def _keys(self, name):
        return XNAMES[name] if name in XNAMES else keys_for(name)

    def xkey(self, *names, delay=0.15):
        for name in names:
            self.u.keyboard(self._keys(name), "tap")
            time.sleep(delay)

    def xtype(self, text, delay=0.15):
        for ch in text:
            self.u.keyboard(keys_for(ch), "tap")
            time.sleep(delay)

    def xdown(self, name):
        self.u.keyboard(self._keys(name), "press")

    def xup(self, name):
        self.u.keyboard(self._keys(name), "release")

    # ---- booting
    def boot(self, image, persist=False):
        with open(image, "rb") as f:
            data = f.read()
        self.u.mount("a", data, type="d64", mode="readwrite" if persist else "unlinked",
                     name=os.path.basename(image))
        self.u.resume()          # a reset leaves a paused machine paused (seen on hardware)
        self.u.reset()
        time.sleep(self.settle)  # let the old screen go before waiting for the new one
        self.wait_for("ready.", timeout=60)
        self.type('load"*",8,1\n')
        self.wait_for("ready.", timeout=self.boot_timeout, after="load")
        self.type("run\n")


if __name__ == "__main__":
    img = sys.argv[1] if len(sys.argv) > 1 else "build/breadbin.d64"
    with UltimateTarget(img) as v:
        v.wait_shell()
        print(v.screen())
