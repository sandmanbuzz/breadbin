#!/usr/bin/env python3
"""Drive VICE (x64sc) through its remote monitor for automated tests.

    with Vice("build/breadbin.d64") as v:
        v.wait_for("/ $ ")
        v.type("ls\\n")
        print(v.screen())
"""
import os
import re
import shlex
import shutil
import socket
import sys
import subprocess
import tempfile
import time

X64 = os.environ.get("X64SC", "x64sc")


def _install_profile():
    """BREADBIN_VICE_PROFILE=1: at exit, one stderr line `vice-profile {json}` with call counts
    and wall seconds per harness method (inclusive: type() contains its _cmd calls), the
    monitor commands one by one, and every time.sleep by caller line. Read with
    .blocks/vice-prof. Off by default; costs nothing then."""
    import atexit
    import json
    acc, slept = {}, {}
    real_sleep = time.sleep

    def add(table, key, dt):
        e = table.setdefault(key, [0, 0.0])
        e[0] += 1
        e[1] += dt

    def sleep(sec):
        f = sys._getframe(1)
        t = time.perf_counter()
        real_sleep(sec)
        add(slept, f"{os.path.basename(f.f_code.co_filename)}:{f.f_lineno}", time.perf_counter() - t)

    def wrap(cls, name):
        fn = getattr(cls, name)

        def w(self, *a, **k):
            t = time.perf_counter()
            try:
                return fn(self, *a, **k)
            finally:
                key = name
                if name == "_cmd":
                    words = a[0].split() if a else [""]
                    key = "_cmd:" + (words[0] if words else "")
                add(acc, key, time.perf_counter() - t)
        setattr(cls, name, w)

    time.sleep = sleep
    t0 = time.perf_counter()

    def dump():
        print("vice-profile " + json.dumps({
            "wall": round(time.perf_counter() - t0, 3),
            "methods": {k: [n, round(v, 3)] for k, (n, v) in acc.items()},
            "sleeps": {k: [n, round(v, 3)] for k, (n, v) in slept.items()}}), file=sys.stderr)
    atexit.register(dump)
    return wrap


def _free_port():
    """A TCP port nothing listens on now, for the VICE monitor (a fixed or pid-derived
    port can land on another run's emulator, and the harness would drive that one)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def screen_to_text(codes):
    out = []
    for c in codes:
        c &= 0x7f
        if c == 0:
            out.append("@")
        elif 1 <= c <= 26:
            out.append(chr(ord("a") + c - 1))
        elif c == 27:
            out.append("[")
        elif c == 28:
            out.append("\\")
        elif c == 29:
            out.append("]")
        elif c == 30:
            out.append("^")
        elif c == 31:
            out.append("<")
        elif 32 <= c <= 63:
            out.append(chr(c))
        elif 65 <= c <= 90:
            out.append(chr(c))
        elif c == 0x5d:
            out.append("|")
        elif c == 0x64:
            out.append("_")
        else:
            out.append("?")
    return "".join(out)


def real_keys_available():
    """True if keystrokes can go through the emulated keyboard matrix: needs
    xdotool and an X display (xvfb-run provides one)."""
    return bool(shutil.which("xdotool") and os.environ.get("DISPLAY"))


class Target:
    """What the tests use: screen reading and waiting, over a backend that
    provides mem(start, end) and type(text). Vice drives the VICE emulator;
    tools/ultimatetest.py drives a real Ultimate."""

    # False where mem() reads the RAM under the CPU port at $0000/$0001 instead of
    # the port itself (a DMA read on the Ultimate returns $00 for $0001)
    sees_cpu_port = True

    # seconds between screen polls in wait_for/wait_shell/_wait: the Ultimate reads the screen
    # by DMA over the network, VICE through a socket (Vice sets a shorter one)
    POLL = 0.5

    # clock hooks: the Ultimate backend's host tests substitute a fake clock
    def _time(self):
        return time.time()

    def _pause(self, seconds):
        time.sleep(seconds)

    def screen_lines(self):
        codes = self.mem(0x0400, 0x07e7)
        text = screen_to_text(codes)
        return [text[i:i + 40].rstrip() for i in range(0, len(text), 40)]

    def screen(self):
        return "\n".join(self.screen_lines())

    def wait_shell(self, user="root", timeout=90):
        """Boot to a shell prompt, logging in as `user` if asked."""
        deadline = self._time() + timeout
        while self._time() < deadline:
            s = self.screen()
            if "login:" in s:
                self.type(user + "\n")
                return self.wait_for(" $", timeout=timeout)
            if s.rstrip().endswith("/ $"):
                return s
            self._pause(self.POLL)
        raise TimeoutError("no login or shell prompt:\n" + self.screen())

    def wait_for(self, text, timeout=60, after=None):
        """Wait until `text` is on screen; return the screen."""
        deadline = self._time() + timeout
        while self._time() < deadline:
            s = self.screen()
            if text in s if after is None else text in s.split(after)[-1]:
                return s
            self._pause(self.POLL)
        raise TimeoutError(f"{text!r} not on screen:\n{self.screen()}")

    PROMPT = re.compile(r"^\S+ \$$")

    def run(self, command, timeout=90, clear=True):
        """Run a command line and return its output (the lines between the
        command and the next prompt). Commands must fit on one screen line."""
        if clear:
            self.type("clear\n")
            # job notices ("[5] done") may print above the prompt
            def cleared(ls):
                body = [l for l in ls if l]
                return (bool(body) and self.PROMPT.match(body[-1]) is not None
                        and all(re.match(r"^\[\d+\] done$", l) for l in body[:-1])
                        and not any(ls[ls.index(body[-1]) + 1:]))
            self._wait(cleared, timeout)
        self.type(command + "\n")
        want = "$ " + command.strip()
        result = []

        def done(lines):
            idx = command_end_row(lines, want)
            if idx is None:
                return False
            for j in range(idx + 1, len(lines)):
                if self.PROMPT.match(lines[j]):
                    result[:] = lines[idx + 1:j]
                    return True
            return False
        self._wait(done, timeout, what=command)
        return "\n".join(result)

    def _wait(self, pred, timeout, what="condition"):
        deadline = self._time() + timeout
        while self._time() < deadline:
            if pred(self.screen_lines()):
                return
            self._pause(self.POLL)
        raise TimeoutError(f"timeout waiting for {what}:\n{self.screen()}")


def command_end_row(lines, want):
    """Row index where the echoed command `want` ("$ " + command) ends, or None.

    The screen is 40 columns: a typed line longer than that wraps onto the next
    row, so the echo can span several rows. Rows are joined and compared with
    spaces removed (a wrap can fall on a space, and the screen drops trailing
    spaces). The search runs from the bottom up, so the newest echo wins.
    """
    target = want.replace(" ", "")
    for i in range(len(lines) - 1, -1, -1):
        joined = ""
        for k in range(i, min(len(lines), i + 8)):
            joined += lines[k].replace(" ", "")
            if joined.endswith(target):
                return k
    return None


class Vice(Target):
    POLL = 0.1
    # The remote monitor answers in about a millisecond and ends every answer with a prompt
    # like "(C:$a5bb) ", but never closes the connection. A command sent while the emulator runs
    # is answered with an entry prompt first, so _cmd counts prompts (2 running, 1 in the monitor)
    # and then waits SETTLE for stragglers. (A trailing sentinel command does not work: VICE
    # handles the second line only when the next command arrives.) `x` is never answered, which
    # is why _running is tracked and a second x to a running emulator is not sent.
    _MON_PROMPT = re.compile(r"\(C:\$[0-9a-f]{4}\) $")
    _MON_ROW = re.compile(r">C:([0-9a-f]{4})  ")
    _MON_ANY = re.compile(r"\(C:\$[0-9a-f]{4}\) ")
    SETTLE = 0.03       # quiet time after the last prompt that confirms the answer is complete
    _running = False    # class level: some tests build a Vice without running __init__; a fresh monitor is open

    def __init__(self, image, reu=False, port=None, warp=True, extra=(), boot_device=8, reu_image=None):
        self.image = image
        self.port = port or _free_port()
        args = [X64, "-default", "+sound", "-minimized",
                "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{self.port}"]
        if warp:
            args.append("-warp")
        if reu:
            args += ["-reu", "-reusize", str(512 if reu is True else reu)]
            if reu_image:       # keep the REU contents across runs (the emulator saves it on exit)
                args += ["-reuimage", reu_image, "-reuimagerw"]
        args += list(extra)
        # extra emulator options for a whole run, e.g. other ROM images kept outside
        # the repo: BREADBIN_VICE_ARGS="-kernal /path/kernal.bin -dos1541II /path/drive.bin"
        args += shlex.split(os.environ.get("BREADBIN_VICE_ARGS", ""))
        if boot_device == 8:
            args += ["-autostart", image]
        else:       # attach to that drive and LOAD from it ourselves once BASIC is up
            args += [f"-drive{boot_device}type", "1541", f"-{boot_device}", image]
        self.log = tempfile.NamedTemporaryFile(prefix="vice", suffix=".log", delete=False)
        if os.environ.get("BREADBIN_VICE_PRINT_ARGS"):    # debug: the emulator's command line, to check the ROM wiring
            print("vice argv:", " ".join(shlex.quote(a) for a in args), file=sys.stderr)
        self.proc = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT)
        self.sock = None
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                break
            except OSError:
                time.sleep(0.3)
        if not self.sock:
            raise RuntimeError("could not connect to VICE monitor")
        self._cmd("x")
        if boot_device != 8:
            self.wait_for("ready.", timeout=30)
            self.type(f'load"*",{boot_device},1\n')
            self.wait_for("ready.", timeout=120, after="load")
            self.type("run\n")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _stkwatch(self):
        # local measurement hook: append the stack high-water mark to $STKWATCH_LOG
        lbl = {}
        for ln in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "kernel.lbl")):
            f = ln.split()
            if len(f) == 3 and f[2].startswith(".stk_hwm"):
                lbl[f[2]] = int(f[1], 16)
        a = lbl[".stk_hwm"]
        d = self.mem(a, a + 12)
        nm = bytes(d[2:13]).split(b"\0")[0].decode(errors="replace")
        with open(os.environ["STKWATCH_LOG"], "a") as f:
            f.write(f"{os.environ.get('STKWATCH_TAG', '')}\t{os.path.basename(self.image)}\thwm={d[0]}\tslot={d[1]}\tname={nm}\n")

    def close(self):
        if os.environ.get("STKWATCH_LOG"):
            try:
                self._stkwatch()
            except Exception as e:
                print("stkwatch failed:", e, file=sys.stderr)
        try:
            self.sock.sendall(b"quit\n")
            time.sleep(0.3)
            self.sock.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def _cmd(self, c, wait=0.0, timeout=30):
        """Send one monitor command; return its output, prompts included, once the answer is
        complete (not after a fixed time). The monitor ends every answer with a prompt, and
        a command that arrives while the emulator runs is answered with an entry prompt
        first, so that case needs two prompts. `x` leaves the monitor, so nothing comes back
        and the emulator runs from here: `wait` is how long to let it run before returning
        (the caller's pacing, e.g. for the key buffer to drain); other commands ignore it."""
        if c.strip() in ("x", "exit"):
            if not self._running:       # an x sent to a running emulator is a no-op that leaves an unread prompt
                self.sock.sendall((c + "\n").encode())
                self._running = True
            if wait:
                time.sleep(wait)
            return ""
        need = 2 if self._running else 1
        self._running = False
        self.sock.sendall((c + "\n").encode())
        out = ""
        deadline = time.time() + timeout
        settle = None                     # when the answer looked complete; a straggler resets it
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise TimeoutError(f"monitor answer to {c!r} did not end:\n{out[-300:]}")
            self.sock.settimeout(self.SETTLE if settle else left)
            try:
                d = self.sock.recv(65536)
            except socket.timeout:
                if settle:
                    return out
                continue
            if not d:
                raise RuntimeError(f"monitor closed the connection during {c!r}:\n{out[-300:]}")
            out += d.decode(errors="replace")
            settle = self._MON_PROMPT.search(out) and len(self._MON_ANY.findall(out)) >= need

    def keybuf(self, data):
        """Put raw key codes (bytes) in the keyboard buffer, as `type` does."""
        self._cmd("keybuf " + "".join(f"\\x{b:02x}" for b in data))
        self._cmd("x")

    def _mem_m(self, start, end):
        """The bytes through the monitor's m command (rows of 16 in groups of four, then
        the text column), or None when the answer does not parse."""
        out = self._cmd(f"m {start:04x} {end:04x}")
        data = []
        for ln in out.splitlines():
            m = self._MON_ROW.search(ln)
            if not m:
                continue
            addr = int(m.group(1), 16)
            want = min(16, end - addr + 1)
            toks = ln[m.end():].split()[:want]
            if len(toks) != want or not all(re.fullmatch(r"[0-9a-f]{2}", t) for t in toks):
                return None
            data += [int(t, 16) for t in toks]
        return data if len(data) == end - start + 1 else None

    def mem(self, start, end):
        """Read memory. The monitor's m command answers over the socket; when that does not
        parse, the save command writes a file."""
        try:
            data = self._mem_m(start, end)
        except (TimeoutError, RuntimeError):
            data = None
        self._cmd("x")
        if data is None:
            # the save path is correct but slow: say so, so a slow run shows why
            print(f"vicetest: monitor m did not answer {start:04x}-{end:04x}; reading by save", file=sys.stderr)
            return self._mem_save(start, end)
        return data

    def _mem_save(self, start, end):
        """Memory through the monitor's save command and a file (retried while VICE is still
        starting up). Subclasses whose _cmd is not the plain one above use this directly."""
        for attempt in range(5):
            fd, path = tempfile.mkstemp(suffix=".bin")
            os.close(fd)
            os.unlink(path)
            self._cmd(f'save "{path}" 0 {start:04x} {end:04x}', wait=0.2)
            self._cmd("x")
            for _ in range(50):
                if os.path.exists(path) and os.path.getsize(path) >= end - start + 3:
                    break
                time.sleep(0.05)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()[2:]
                os.unlink(path)
                return list(data[:end - start + 1])
            time.sleep(1)
        raise RuntimeError("VICE monitor did not save memory")

    def type(self, text):
        """Type text; '\\n' is RETURN, '|' is sent as SHIFT+'-' (PETSCII $dd).
        Fed in small pieces so the 10-key KERNAL buffer never overflows."""
        for chunk in re.findall(r"[^\n]{1,8}|\n", text):
            if chunk == "\n":
                esc = "\\x0d"
            else:
                esc = chunk.replace("\\", "\\\\").replace("|", "\\xdd").replace(" ", "\\x20").replace('"', "\\x22")
            self._cmd("keybuf " + esc)
            self._cmd("x", wait=0.25)

    # ---- real keystrokes: X events -> VICE's emulated keyboard matrix. Unlike
    # type(), which writes into the KERNAL-style key buffer, these exercise
    # the matrix scan, the decode tables, modifiers and key repeat.
    def _x(self, *args):
        return subprocess.run(["xdotool", *args], capture_output=True, text=True).stdout

    def focus(self):
        wins = [w for w in self._x("search", "--class", "x64sc").split()
                if "VICE" in self._x("getwindowname", w)]
        if not wins:
            raise RuntimeError("VICE window not found")
        self._x("windowmove", wins[0], "0", "0")
        self._x("mousemove", "300", "300")
        self._x("windowfocus", wins[0])
        time.sleep(1)

    def xkey(self, *keys, delay=0.15, hold=0.06):
        """Tap X key names, e.g. xkey('a', 'Return', 'space', 'exclam'). Each key
        is held for `hold` seconds of wall time: `xdotool key` presses and
        releases within a few milliseconds, and when VICE runs in warp mode both
        events can reach the emulator in one batch, before the emulated machine
        has had a chance to scan the keyboard, so the key is lost."""
        for k in keys:
            self._x("keydown", k)
            time.sleep(hold)
            self._x("keyup", k)
            time.sleep(delay)

    def xtype(self, text, delay=0.15):
        names = {" ": "space", "\n": "Return"}
        self.xkey(*[names.get(c, c) for c in text], delay=delay)

    def xdown(self, key):
        self._x("keydown", key)

    def xup(self, key):
        self._x("keyup", key)







if os.environ.get("BREADBIN_VICE_PROFILE"):
    _wrap = _install_profile()
    for _n in ("_cmd", "mem", "screen_lines", "type", "wait_for", "wait_shell", "run", "_wait", "xkey"):
        _wrap(Vice if _n in ("_cmd", "mem", "type", "xkey") else Target, _n)


def make_target(image, **kw):
    """The emulator by default; BREADBIN_TARGET=ultimate runs the same tests on
    a real Ultimate (BREADBIN_ULTIMATE=host[:port], see tools/ultimatetest.py).
    VICE-only options (reu=, extra=, warp=) are for tests that need the emulator."""
    if os.environ.get("BREADBIN_TARGET", "vice") == "ultimate":
        from ultimatetest import UltimateTarget
        return UltimateTarget(image)
    return Vice(image, **kw)


if __name__ == "__main__":
    import sys
    with Vice(sys.argv[1] if len(sys.argv) > 1 else "build/breadbin.d64") as v:
        time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 15)
        print(v.screen())
