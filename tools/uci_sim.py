"""Run the real Breadbin kernel image in a 6502 emulator (py65) with a fake Ultimate Command
Interface (UCI) at $DF1B-$DF1F, for testing UCI v1 without hardware (docs/design/next/uci-v1.md,
section 7). Used by tools/test_uci_sim.py.

What is real: the whole kernel image (build/breadbin.prg), its boot stub, kmain up to the point
where it would start /bin/init (BSS clear, memory, process and file tables, the root mount from
build/breadbin.d64), and every syscall, called through the jump table at $CF00.
What is faked: the IEC bus (iec_open/iec_read/iec_write are trapped and served from the disk
image in memory), the REU (reported absent), interrupts (none are raised: the scheduler never
runs, so a test is one process calling syscalls), and the Ultimate (FakeUCI below).

FakeUCI follows the measured behaviour in docs/hardware-notes.md ("UCI as measured", hw-bench)
and the firmware's DOS target (1541ultimate software/filemanager/dos.cc): Data More chains of
512-byte packets, an empty status past the end of a file, "85,NO FILE OPEN", text errors from the
file system ("FILE DOESN'T EXIST", "FILE EXISTS", "ACCESS DENIED", "PATH DOESN'T EXIST"),
FILE STAT that never works, two independent targets, directory commands that leave a target's
open file alone, ID $C9. It shares the documentation's gaps (see the uci-v1 addendum).

py65 (BSD licence) is a test dependency only, not vendored: pip install py65 into a venv.
"""
import os
import re
import stat as statmod

from py65.devices.mpu6502 import MPU

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")

CTL, CMD, DAT, STS = 0xDF1C, 0xDF1D, 0xDF1E, 0xDF1F

ERRNO = {1: "EPERM", 2: "ENOENT", 5: "EIO", 8: "ENOEXEC", 9: "EBADF", 16: "EBUSY", 17: "EEXIST",
         18: "EXDEV", 19: "ENODEV", 20: "ENOTDIR", 21: "EISDIR", 22: "EINVAL", 24: "EMFILE",
         36: "ENAMETOOLONG", 39: "ENOTEMPTY"}

OK = b"00,OK"


class Target:
    def __init__(self):
        self.path = "/"
        self.file = None        # [python file, readable, writable, host name]
        self.dirlist = []


class FakeUCI:
    """The Command Interface registers and the DOS targets 1 and 2, on a host directory."""

    BUSY = 3                    # reads of $DF1C that show "busy" before an answer

    def __init__(self, root):
        self.root = root
        self.state = 0          # 0 idle, 1 busy, 2 data last, 3 data more
        self.err = False
        self.cmd = bytearray()
        self.data, self.di = b"", 0
        self.status, self.si = b"", 0
        self.busy = 0
        self.packets = None
        self.pending = None
        self.targets = {1: Target(), 2: Target()}
        self.log = []           # (target, command, argument bytes)
        self.leaks = 0          # OPEN on a target that still had a file open (leaks a handle)
        self.writes_while_busy = 0

    # ---- registers
    def read(self, a):
        if a == CTL:
            if self.state == 1:
                self.busy -= 1
                if self.busy <= 0:
                    self._present(next(self.packets))
            v = (self.state << 4) | (0x08 if self.err else 0)
            if self.state >= 2 and self.di < len(self.data):
                v |= 0x80
            if self.state >= 2 and self.si < len(self.status):
                v |= 0x40
            return v
        if a == CMD:
            return 0xC9
        if a == DAT:
            if self.state >= 2 and self.di < len(self.data):
                self.di += 1
                return self.data[self.di - 1]
            return 0
        if a == STS:
            if self.state >= 2 and self.si < len(self.status):
                self.si += 1
                return self.status[self.si - 1]
            return 0
        return 0xFF

    def write(self, a, v):
        if a == CMD:
            if self.state != 0:
                self.err = True
                self.writes_while_busy += 1
            else:
                self.cmd.append(v)
        elif a == CTL:
            if v & 0x08:
                self.err = False
            if v & 0x04:                # ABORT
                self.state, self.cmd, self.packets = 0, bytearray(), None
                self.data, self.status = b"", b""
            if v & 0x01:                # PUSH_CMD
                if self.state != 0:
                    self.err = True
                else:
                    self.packets = iter(self._execute(bytes(self.cmd)))
                    self.cmd = bytearray()
                    self.state, self.busy = 1, self.BUSY
            if v & 0x02:                # DATA_ACC
                if self.state == 3:
                    self.state, self.busy = 1, self.BUSY
                elif self.state == 2:
                    self.state, self.packets = 0, None
                    self.data, self.status = b"", b""

    def _present(self, pkt):
        data, status, last = pkt
        self.data, self.di = data, 0
        self.status, self.si = status, 0
        self.state = 2 if last else 3

    # ---- the DOS target
    def host(self, t, name):
        p = name if name.startswith("/") else t.path.rstrip("/") + "/" + name
        parts = []
        for c in p.split("/"):
            if c in ("", "."):
                continue
            if c == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(c)
        return "/" + "/".join(parts), os.path.join(self.root, *parts)

    def is_open(self, h):
        return any(t.file and t.file[3] == h for t in self.targets.values())

    def _execute(self, c):
        if len(c) < 2:
            yield b"", b"99,FUNCTION NOT IMPLEMENTED", True
            return
        tn, op, arg = c[0], c[1], c[2:]
        self.log.append((tn, op, arg))
        if tn not in self.targets:
            yield b"", b"99,FUNCTION NOT IMPLEMENTED", True
            return
        t = self.targets[tn]
        name = arg.decode("latin1")
        if op == 0x01:                                  # IDENTIFY
            yield b"ULTIMATE-II DOS V1.2", OK, True
        elif op == 0x02:                                # OPEN FILE
            yield b"", self._open(t, arg[0], arg[1:].decode("latin1")), True
        elif op == 0x03:                                # CLOSE FILE
            if t.file:
                t.file[0].close()
                t.file = None
                yield b"", OK, True
            else:
                yield b"", b"84,NO FILE TO CLOSE", True
        elif op == 0x04:                                # READ DATA
            if not t.file:
                yield b"", b"85,NO FILE OPEN", True
                return
            remaining = arg[0] | arg[1] << 8
            while True:
                length = min(512, remaining)
                if not t.file[1]:
                    yield b"", b"ACCESS DENIED", True
                    return
                chunk = t.file[0].read(length)
                remaining -= len(chunk)
                last = len(chunk) != length or remaining == 0
                yield chunk, b"", last
                if last:
                    return
        elif op == 0x05:                                # WRITE DATA (2 dummy bytes first)
            if not t.file:
                yield b"", b"85,NO FILE OPEN", True
            elif not t.file[2]:
                yield b"", b"ACCESS DENIED", True
            else:
                t.file[0].write(arg[2:])
                yield b"", OK, True
        elif op == 0x06:                                # SEEK
            if not t.file:
                yield b"", b"85,NO FILE OPEN", True
                return
            pos = int.from_bytes(arg[:4], "little")
            if not t.file[2]:
                pos = min(pos, os.fstat(t.file[0].fileno()).st_size)
            t.file[0].seek(pos)
            yield b"", OK, True
        elif op == 0x07:                                # FILE INFO
            if not t.file:
                yield b"", b"85,NO FILE OPEN", True
                return
            t.file[0].flush()
            size = os.fstat(t.file[0].fileno()).st_size
            yield self._info(size, os.path.basename(t.file[3]), 0x20), OK, True
        elif op == 0x08:                                # FILE STAT: measured to fail always
            yield b"", b"82,FILE NOT FOUND", True
        elif op == 0x09:                                # DELETE
            _, h = self.host(t, name)
            if not os.path.lexists(h):
                yield b"", self._noent(h), True
            elif os.path.isdir(h):
                if os.listdir(h):
                    yield b"", b"ACCESS DENIED", True
                else:
                    os.rmdir(h)
                    yield b"", OK, True
            elif self.is_open(h):
                yield b"", b"ACCESS DENIED", True       # FatFs file lock
            else:
                os.unlink(h)
                yield b"", OK, True
        elif op == 0x0A:                                # RENAME old $00 new
            old, new = name.split("\0", 1)
            _, ho = self.host(t, old)
            _, hn = self.host(t, new)
            if not os.path.lexists(ho):
                yield b"", self._noent(ho), True
            elif os.path.lexists(hn):
                yield b"", b"FILE EXISTS", True
            elif not os.path.isdir(os.path.dirname(hn)):
                yield b"", b"PATH DOESN'T EXIST", True
            elif self.is_open(ho):
                yield b"", b"ACCESS DENIED", True
            else:
                os.rename(ho, hn)
                yield b"", OK, True
        elif op == 0x11:                                # CHANGE DIR
            p, h = self.host(t, name)
            if os.path.isdir(h):
                t.path = p
                yield b"", OK, True
            else:
                yield b"", b"83,NO SUCH DIRECTORY", True
        elif op == 0x12:                                # GET PATH
            yield t.path.encode(), OK, True
        elif op == 0x13:                                # OPEN DIR
            _, h = self.host(t, t.path)
            try:
                t.dirlist = sorted(os.listdir(h))
            except OSError:
                yield b"", b"86,CAN'T READ DIRECTORY", True
                return
            yield b"", (OK if t.dirlist else b"01,DIRECTORY EMPTY"), True
        elif op == 0x14:                                # READ DIR: one packet per entry
            _, h = self.host(t, t.path)
            if not t.dirlist:
                yield b"", b"87,INTERNAL ERROR", True
                return
            for i, n in enumerate(t.dirlist):
                attr = 0x10 if os.path.isdir(os.path.join(h, n)) else 0x20
                last = i == len(t.dirlist) - 1
                yield bytes([attr]) + n.encode("latin1"), (OK if last else b""), last
        elif op == 0x16:                                # CREATE DIR
            _, h = self.host(t, name)
            if os.path.lexists(h):
                yield b"", b"FILE EXISTS", True
            elif not os.path.isdir(os.path.dirname(h)):
                yield b"", b"PATH DOESN'T EXIST", True
            else:
                os.mkdir(h)
                yield b"", OK, True
        else:
            yield b"", b"99,FUNCTION NOT IMPLEMENTED", True

    @staticmethod
    def _info(size, name, attrib):
        base, _, ext = name.rpartition(".")
        ext = (ext if base else "")[:3].upper().ljust(3).encode()
        return size.to_bytes(4, "little") + bytes(4) + ext + bytes([attrib]) + name.encode("latin1")

    @staticmethod
    def _noent(h):
        return b"FILE DOESN'T EXIST" if os.path.isdir(os.path.dirname(h)) else b"PATH DOESN'T EXIST"

    def _open(self, t, flags, name):
        _, h = self.host(t, name)
        if t.file:
            self.leaks += 1                 # the firmware drops the old File object
            t.file[0].close()
            t.file = None
        rd, wr, new, always = flags & 1, flags & 2, flags & 4, flags & 8
        if not os.path.isdir(os.path.dirname(h)):
            return b"PATH DOESN'T EXIST"
        exists = os.path.lexists(h)
        if exists and os.path.isdir(h):
            return b"FILE DOESN'T EXIST"    # FatFs f_open on a directory: FR_NO_FILE
        if new and exists:
            return b"FILE EXISTS"
        if not exists and not (new or always):
            return b"FILE DOESN'T EXIST"
        if always or not exists:
            open(h, "wb").close()
        t.file = [open(h, "r+b"), bool(rd), bool(wr), h]
        return OK


class Mem:
    """64 KB of RAM; $DF1B-$DF1F go to the UCI (or count as open bus if there is none)."""

    def __init__(self, uci):
        self.b = bytearray(65536)
        self.uci = uci
        self.touch = []                     # (r/w, address) of every access to $DF1B-$DF1F

    def __getitem__(self, a):
        if 0xDF1B <= a <= 0xDF1F:
            self.touch.append(("r", a))
            if self.uci:
                return self.uci.read(a)
            return self.b[a]
        return self.b[a]

    def __setitem__(self, a, v):
        if 0xDF1B <= a <= 0xDF1F:
            self.touch.append(("w", a))
            if self.uci:
                self.uci.write(a, v)
                return
        self.b[a] = v

    def __len__(self):
        return 65536


class KernelError(Exception):
    pass


class Sim:
    TRAMP = 0x0340              # JSR SYS_x; the return lands on TRAMP + 3
    SCRATCH = 0x9000            # pages $90-$97: buffers for the tests (reserved in pg_used)

    def __init__(self, uci=None, image=None):
        with open(os.path.join(BUILD, "breadbin.prg"), "rb") as f:
            prg = f.read()
        self.lbl = {}
        with open(os.path.join(BUILD, "kernel.lbl")) as f:
            for line in f:
                m = re.match(r"al ([0-9A-F]+) \.(\S+)$", line.strip())
                if m:
                    self.lbl[m.group(2)] = int(m.group(1), 16)
        self.sysno = {}
        with open(os.path.join(ROOT, "include", "breadbin.inc")) as f:
            for line in f:
                m = re.match(r"SYS_(\w+)\s*=\s*SYS_BASE \+ 3\*(\d+)", line)
                if m:
                    self.sysno[m.group(1)] = 0xCF00 + 3 * int(m.group(2))
        with open(image or os.path.join(BUILD, "breadbin.d64"), "rb") as f:
            self.image = bytearray(f.read())
        self.uci = uci
        self.mem = Mem(uci)
        load = prg[0] | prg[1] << 8
        for i, b in enumerate(prg[2:]):
            self.mem.b[load + i] = b
        self.mpu = MPU(memory=self.mem, pc=0x080D)     # SYS 2061
        L = self.lbl
        self.hooks = {L["iec_open"]: self._ok, L["iec_close"]: self._ok, L["iec_read"]: self._rd,
                      L["iec_write"]: self._wr, L["reu_detect"]: self._noreu}
        self.steps = 0
        self.run(L["kmain_run"], 3_000_000)
        self._process()

    # ---- running
    def run(self, until, limit):
        mpu, hooks = self.mpu, self.hooks
        n = 0
        while mpu.pc != until:
            h = hooks.get(mpu.pc)
            if h:
                h()
                continue
            if self.mem.b[mpu.pc] == 0x00:
                raise KernelError("BRK at $%04X" % mpu.pc)
            mpu.step()
            n += 1
            if n > limit:
                raise KernelError("no return after %d steps, pc $%04X" % (n, mpu.pc))
        self.steps += n
        return n

    def _rts(self, carry=False):
        m, mpu = self.mem.b, self.mpu
        lo, hi = m[0x100 + ((mpu.sp + 1) & 0xFF)], m[0x100 + ((mpu.sp + 2) & 0xFF)]
        mpu.sp = (mpu.sp + 2) & 0xFF
        mpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF
        mpu.p = (mpu.p | 1) if carry else (mpu.p & ~1)

    def _ok(self):
        self._rts()

    def _noreu(self):
        self.mem.b[self.lbl["reu_banks"]] = 0
        self._rts()

    def _blk(self):
        m, L = self.mem.b, self.lbl
        assert m[L["rq_dev"]] == 0, "IEC read for device %d" % m[L["rq_dev"]]
        blk = m[L["rq_lo"]] | m[L["rq_hi"]] << 8
        bp = m[L["bp"]] | m[L["bp"] + 1] << 8
        return blk * 256, bp

    def _rd(self):
        off, bp = self._blk()
        self.mem.b[bp:bp + 256] = self.image[off:off + 256]
        self._rts()

    def _wr(self):
        off, bp = self._blk()
        self.image[off:off + 256] = self.mem.b[bp:bp + 256]
        self._rts()

    def _process(self):
        """One process in slot 0, cwd "/", fds 0-2 on the console; scratch pages reserved."""
        m, L = self.mem.b, self.lbl
        m[L["cur"]] = 0
        m[L["in_kernel"]] = 0
        m[L["p_state"]] = 1
        m[L["p_pid"]] = 200                       # out of the way of the pids spawn hands out
        m[L["p_uid"]] = 0
        m[L["p_cwddev"]] = 0
        m[L["p_cwdino"]] = 1
        con = m[L["con_file"]]
        for i in range(8):
            m[L["p_fd"] + i] = con if i < 3 else 0xFF
        m[L["p_cwd"]:L["p_cwd"] + 2] = b"/\0"
        for p in range(0x90, 0x98):
            m[L["pg_used"] + p - 8] = 1
        self.mpu.p &= ~0x04                         # (no interrupt will come anyway)

    # ---- syscalls
    def sys(self, name, a=0, x=0, y=0, r0=None, r1=None, limit=4_000_000):
        m, mpu = self.mem.b, self.mpu
        for reg, v in ((0x02, r0), (0x04, r1)):
            if v is not None:
                m[reg], m[reg + 1] = v & 0xFF, v >> 8
        addr = self.sysno[name]
        m[self.TRAMP:self.TRAMP + 3] = bytes([0x20, addr & 0xFF, addr >> 8])
        mpu.pc, mpu.sp, mpu.a, mpu.x, mpu.y = self.TRAMP, 0xFF, a, x, y
        self.run(self.TRAMP + 3, limit)
        return bool(mpu.p & 1), mpu.a, mpu.x

    def r1(self):
        return self.mem.b[4] | self.mem.b[5] << 8

    def put(self, addr, data):
        self.mem.b[addr:addr + len(data)] = data

    def cstr(self, s, addr=None):
        addr = addr or self.SCRATCH
        self.put(addr, s.encode() + b"\0")
        return addr

    def check(self, res, what=""):
        err, a, x = res
        if err:
            raise KernelError("%s: %s (%d)" % (what, ERRNO.get(a, "?"), a))
        return a

    def errno(self, res):
        err, a, _ = res
        return ERRNO.get(a, a) if err else None

    # convenience wrappers: paths at $9000, buffers at $9100-$97FF
    def open(self, path, flags=0):
        return self.sys("OPEN", a=flags, r0=self.cstr(path))

    def close(self, fd):
        return self.check(self.sys("CLOSE", a=fd), "close")

    def read(self, fd, n, buf=0x9100):
        res = self.sys("READ", a=fd, r0=buf, r1=n)
        self.check(res, "read")
        got = self.r1()
        return bytes(self.mem.b[buf:buf + got])

    def read_all(self, fd, chunk=1000):
        out = b""
        while True:
            d = self.read(fd, chunk)
            if not d:
                return out
            out += d

    def write(self, fd, data, buf=0x9100):
        self.put(buf, data)
        res = self.sys("WRITE", a=fd, r0=buf, r1=len(data))
        self.check(res, "write")
        return self.r1()

    def stat(self, path):
        res = self.sys("STAT", r0=self.cstr(path), r1=0x90F0)
        if res[0]:
            return res
        b = self.mem.b[0x90F0:0x90F8]
        return {"type": b[0], "nlink": b[1], "size": b[2] | b[3] << 8 | b[4] << 16, "ino": b[5], "dev": b[6]}

    def path_call(self, name, path, path2=None):
        if path2 is None:
            return self.sys(name, r0=self.cstr(path))
        return self.sys(name, r0=self.cstr(path), r1=self.cstr(path2, 0x9080))

    def mount_uci(self, path):
        return self.sys("MOUNT", a=ord("U"), x=ord("U"), r0=self.cstr(path))

    def listdir(self, path, chunk=16):
        fd = self.check(self.open(path), "open " + path)
        names = []
        while True:
            d = self.read(fd, chunk)
            if not d:
                break
            assert len(d) % 16 == 0, d
            for i in range(0, len(d), 16):
                rec = d[i:i + 16]
                if rec[0]:
                    names.append((rec[0], rec[1:].split(b"\0")[0].decode("latin1")))
        self.close(fd)
        return names

    def getcwd(self):
        self.check(self.sys("GETCWD", a=64, r0=0x9100), "getcwd")
        return bytes(self.mem.b[0x9100:0x9140]).split(b"\0")[0].decode()

    def mntinfo(self, i):
        res = self.sys("MNTINFO", a=i, r0=0x9100)
        if res[0]:
            return None
        b = self.mem.b[0x9100:0x9122]
        return b[0], b[1], bytes(b[2:]).split(b"\0")[0].decode()

    def spawn(self, path):
        """spawn(path) with stdin/stdout = fd 0/1; the child is made ready but never runs."""
        return self.sys("SPAWN", a=0, x=1, y=0, r0=self.cstr(path), r1=0)


def cx_image(data, base):
    """The memory image spawn should leave for a CX file loaded at page `base`."""
    assert data[:3] == b"CX\x01"
    img, bss, nrel = (int.from_bytes(data[3 + 2 * i:5 + 2 * i], "little") for i in range(3))
    out = bytearray(data[9:9 + img])
    rel = data[9 + img:9 + img + 2 * nrel]
    for i in range(nrel):
        off = rel[2 * i] | rel[2 * i + 1] << 8
        out[off] = (out[off] + base) & 0xFF
    return bytes(out), bss


__all__ = ["FakeUCI", "Sim", "KernelError", "cx_image", "statmod"]
