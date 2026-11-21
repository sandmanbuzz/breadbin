"""Run single routines of the user library (src/lib) under py65, to test them one by one.

A `Lib` assembles the library of a source tree (this one, or an older commit checked out elsewhere) and
links it flat at $2000 with every export reachable. `Lib.call` then runs one routine to its RTS with the
registers, memory, argv and the files you give it, answers the syscalls in Python (a model of the contract in
include/breadbin.inc, like tools/asim.py, not the kernel) and returns what the caller could see:
A/X/Y, the flags, the zero page the routine changed, the bytes written to each fd, the syscalls it made and
how deep it went on the stack. Zero page is filled with a pattern first, so a routine that depends on a
stale byte there gives a different answer under a different `fill`.

    lib = Lib(ROOT, workdir)
    r = lib.call("strlen", a=lo, x=hi, mem={0x8000: b"abc\\0"})
    r.a, r.x, r.y, r.c, r.z, r.clobbered, r.out[1], r.trace, r.depth
"""
import glob
import os
import re
import subprocess

try:
    from py65.devices.mpu6502 import MPU
except ImportError:      # the tests skip
    MPU = None

import asim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x2000                    # where the flat image is linked
SENT = 0xBFF0                    # the address a routine returns to
ARGV = 0xC000                    # argv strings and the pointer array (as tools/asim.py does)
STACK0 = 0xF0                    # SP at the call, below the return address pushed for SENT
EIO, ENOENT, EBADF = 5, 2, 9


class Result:
    exit = None                  # the status of SYS_EXIT, or None if the routine returned
    out = None                   # fd -> bytes written
    trace = None                 # (syscall, A, r0, r1) in order
    clobbered = None             # zero-page addresses ($02-$FF) whose value changed
    depth = 0                    # stack bytes used beyond the return address
    steps = 0
    mem = None                   # the 64 KB afterwards, for looking at a result buffer
    a = x = y = 0
    p = 0

    c = property(lambda s: s.p & 1)
    z = property(lambda s: (s.p >> 1) & 1)
    n = property(lambda s: (s.p >> 7) & 1)

    def cstr(self, addr, limit=4096):
        out = bytearray()
        while self.mem[addr] and len(out) < limit:
            out.append(self.mem[addr])
            addr += 1
        return bytes(out)


class Lib:
    """The library of the source tree `tree` (it has src/lib and include), built in `work`."""

    def __init__(self, tree, work):
        if MPU is None:
            raise RuntimeError("py65 not installed")
        os.makedirs(work, exist_ok=True)
        srcs = sorted(glob.glob(os.path.join(tree, "src", "lib", "*.s")))
        objs, exports = [], []
        for s in srcs:
            o = os.path.join(work, os.path.basename(s)[:-2] + ".o")
            subprocess.run(["ca65", s, "-o", o], check=True, capture_output=True)
            objs.append(o)
            with open(s) as f:
                text = f.read()
            for m in re.finditer(r"^\s*\.export\s+([^;\n]+)", text, re.M):
                exports += [n.strip() for n in m.group(1).split(",")]
        arc = os.path.join(work, "lib.a")
        if os.path.exists(arc):
            os.remove(arc)
        subprocess.run(["ar65", "a", arc] + objs, check=True, capture_output=True)
        stub = os.path.join(work, "stub.s")
        with open(stub, "w") as f:
            f.write('.segment "CODE"\n' + "".join(".import %s\n.word %s\n" % (n, n) for n in exports))
        so = os.path.join(work, "stub.o")
        subprocess.run(["ca65", stub, "-o", so], check=True, capture_output=True)
        img, lbl = os.path.join(work, "img"), os.path.join(work, "img.lbl")
        subprocess.run(["ld65", "-C", os.path.join(ROOT, "src", "prog.cfg"), "-S", str(BASE), "-Ln", lbl, "-o", img, so, arc],
                       check=True, capture_output=True)
        with open(img, "rb") as f:
            self.image = f.read()
        self.syms = {}
        with open(lbl) as f:
            for line in f:
                m = re.match(r"al ([0-9A-Fa-f]+) \.(\w+)", line)
                if m:
                    self.syms[m.group(2)] = int(m.group(1), 16)
        self.exports = exports

    def call(self, name, a=0, x=0, y=0, c=0, mem=None, argv=("prog",), files=None, fill=0xA5, limit=3_000_000,
             open_fail=None, read_fail=None, write_fail=None, chunk=None, stdin=None):
        """Run routine `name` and return a Result.

        mem        {address: bytes} written before the call (inputs go at $8000 and up)
        argv       the argument strings: argv[0] is the program name perr prints
        files      {path: bytes} for SYS_OPEN (read-only); open_fail {path: errno} makes an open fail
        read_fail  n: the n-th READ (from 1) fails with EIO; write_fail likewise for WRITE
        chunk      at most this many bytes per READ (a short read), None for all that was asked for
        stdin      bytes served to fd 0"""
        if name not in self.syms:
            raise KeyError(name)
        files = dict(files or {})
        mem_ = bytearray(65536)
        mem_[BASE:BASE + len(self.image)] = self.image
        for i in range(2, 0x100):
            mem_[i] = fill
        for addr, data in (mem or {}).items():
            mem_[addr:addr + len(data)] = data
        top, ptrs = ARGV, []
        for s in argv:
            b = s.encode() + b"\0"
            mem_[top:top + len(b)] = b
            ptrs.append(top)
            top += len(b)
        top = (top + 1) & ~1
        for i, p in enumerate(ptrs + [0]):
            mem_[top + 2 * i] = p & 0xFF
            mem_[top + 2 * i + 1] = p >> 8
        mem_[0x20], mem_[0x21], mem_[0x22] = top & 0xFF, top >> 8, len(ptrs)
        before = bytes(mem_[:0x100])
        cpu = MPU(memory=mem_)
        cpu.a, cpu.x, cpu.y = a, x, y
        cpu.p = (cpu.p & ~1) | (c & 1)
        cpu.sp = STACK0
        for byte in ((SENT - 1) >> 8, (SENT - 1) & 0xFF):      # what a JSR to the routine would have pushed
            mem_[0x100 + cpu.sp] = byte
            cpu.sp -= 1
        cpu.pc = self.syms[name]
        sp0 = cpu.sp
        res = Result()
        res.out, res.trace = {}, []
        fds, nread, nwrite = {}, [0], [0]
        minsp = sp0
        stdin = [stdin or b""]

        def r(n):
            return mem_[n] | mem_[n + 1] << 8

        def ret(carry, aval=None):
            if aval is not None:
                cpu.a = aval & 0xFF
            cpu.p = (cpu.p | 1) if carry else (cpu.p & ~1)
            lo, hi = mem_[0x100 + ((cpu.sp + 1) & 0xFF)], mem_[0x100 + ((cpu.sp + 2) & 0xFF)]
            cpu.sp = (cpu.sp + 2) & 0xFF
            cpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF

        def cstr(addr):
            s = bytearray()
            while mem_[addr]:
                s.append(mem_[addr])
                addr += 1
            return s.decode("latin-1")

        steps = 0
        while cpu.pc != SENT:
            sysname = asim.SYS.get(cpu.pc)
            if sysname:
                res.trace.append((sysname, cpu.a, r(2), r(4)))
                fd = cpu.a
                mem_[0x08:0x20] = [0xA5] * 0x18           # the kernel's syscall scratch
                if sysname == "EXIT":
                    res.exit = fd
                    break
                elif sysname == "OPEN":
                    path, flags = cstr(r(2)), cpu.a
                    if open_fail and path in open_fail:
                        ret(True, open_fail[path])
                    elif flags & 3 == 0 and path in files:
                        fds[len(fds) + 3] = [path, 0]
                        ret(False, len(fds) + 2)
                    else:
                        ret(True, ENOENT)
                elif sysname == "CLOSE":
                    if fd in fds:
                        del fds[fd]
                        ret(False, 0)
                    else:
                        ret(True, EBADF)
                elif sysname == "READ":
                    nread[0] += 1
                    if read_fail == nread[0]:
                        ret(True, EIO)
                        continue
                    n_ = r(4) if chunk is None else min(r(4), chunk)
                    if fd == 0:
                        data, stdin[0] = stdin[0][:n_], stdin[0][n_:]
                    elif fd in fds:
                        f = fds[fd]
                        data = files[f[0]][f[1]:f[1] + n_]
                        f[1] += len(data)
                    else:
                        ret(True, EBADF)
                        continue
                    addr = r(2)
                    mem_[addr:addr + len(data)] = data
                    mem_[4], mem_[5] = len(data) & 0xFF, len(data) >> 8
                    ret(False, 0)
                elif sysname == "WRITE":
                    nwrite[0] += 1
                    if write_fail == nwrite[0]:
                        ret(True, 28)
                        continue
                    addr, cnt = r(2), r(4)
                    res.out[fd] = res.out.get(fd, b"") + bytes(mem_[addr:addr + cnt])
                    ret(False, 0)
                else:
                    raise NotImplementedError(sysname)
                continue
            cpu.step()
            steps += 1
            minsp = min(minsp, cpu.sp)
            if steps > limit:
                raise RuntimeError("%s: no return after %d steps" % (name, limit))
        res.steps = steps
        res.a, res.x, res.y, res.p = cpu.a, cpu.x, cpu.y, cpu.p
        res.depth = sp0 - minsp
        if res.exit is None:
            assert cpu.sp == sp0 + 2, "%s left the stack unbalanced (sp %02x, expected %02x)" % (name, cpu.sp, sp0 + 2)
        res.clobbered = sorted(i for i in range(2, 0x100) if mem_[i] != before[i] and not 0x08 <= i < 0x20)
        res.mem = bytes(mem_)
        return res
