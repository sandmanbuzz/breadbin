"""Run a Breadbin CX program (build/root/bin/*) on the host under py65, with the few syscalls a
file-to-file tool needs answered in Python. For testing programs like `as` without VICE:
there is no kernel, no scheduler, no disk, only the program's own 6502 code and the library linked
into it. Syscalls handled: OPEN, CLOSE, READ, WRITE, UNLINK, RENAME, EXIT, CONMODE (recorded in r.conmodes); fds 1 and 2
collect output. Every syscall overwrites $08-$1F, the kernel's scratch. With stdin=bytes, fd 0 serves those bytes (EOF after them) and `r.marks` records len(r.out)
at every read of fd 0, so a test can see what one key made the program draw; without it fd 0 is EBADF.

    from asim import run
    r = run("as", ["/home/x.s", "/home/x"], {"/home/x.s": b"..."})
    r.exit, r.out, r.err, r.files["/home/x"], r.steps

Everything here is a model of the kernel's contract (include/breadbin.inc: A, r0, r1, carry), not
the kernel: use the VICE tests for what the kernel does. py65 is a test dependency (pip install py65).
"""
import os
import re

try:
    from py65.devices.mpu6502 import MPU
except ImportError:      # the tests skip
    MPU = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_PAGE = 0x08                  # where the pool starts: programs load at $0800 on the machine
SYS = {}
with open(os.path.join(ROOT, "include", "breadbin.inc")) as _f:
    for _line in _f:
        _m = re.match(r"SYS_(\w+)\s*=\s*SYS_BASE \+ 3\*(\d+)", _line)
        if _m:
            SYS[0xCF00 + 3 * int(_m.group(2))] = _m.group(1)
ENOENT = 2
EBADF = 9
ENOSPC = 28
ENAMETOOLONG = 36


def toolong(path):
    return any(len(c) > 14 for c in path.split("/"))


class Result:
    def __init__(self):
        self.exit = None
        self.mem = b""                 # the 64 KB at exit
        self.out = b""
        self.err = b""
        self.files = {}
        self.steps = 0
        self.cycles = 0
        self.conmodes = []            # the mode argument of each CONMODE call, in order
        self.marks = []               # len(out) at each read of fd 0 (stdin=...)
        self.header = None            # the CX header of the program's image, for inspection
        self.spawns = []              # SPAWN calls: (path, argv, pin, pout, flags), children are not run
        self.cwd = "/"               # CHDIR moves it; GETCWD answers it
        self.mem = None              # the 64 KB memory at exit, for tests that look at the program's variables


def cx_load(data, page):
    """(image bytes with relocations applied, bss size, header dict) of a CX file loaded at `page`."""
    assert data[:3] == b"CX\x01", "not a CX file"
    img, bss, nrel = (int.from_bytes(data[3 + 2 * i:5 + 2 * i], "little") for i in range(3))
    out = bytearray(data[9:9 + img])
    rel = data[9 + img:9 + img + 2 * nrel]
    for i in range(nrel):
        off = rel[2 * i] | rel[2 * i + 1] << 8
        out[off] = (out[off] + page) & 0xFF
    return bytes(out), bss, {"image": img, "bss": bss, "relocs": nrel}


def run(prog, args, files=None, limit=40_000_000, path=None, stdin=None, fail_write=None, fail_rename=None, fail_read_open=None, rename_noreplace=False, fail_create=None, tty=False, dirs=(), kbd=False, yield_jiffies=1, jiffy0=0, cooked=False, poke=None):
    """Run build/root/bin/<prog> (or `path`) with argv = [prog] + args. `files` maps path -> bytes.
    fail_write=n makes the n-th WRITE (1 is the first) fail with ENOSPC, as a full disk would;
    fail_rename=n makes the n-th RENAME fail; rename_noreplace=True models the CBM DOS path (cbm_rename sends R0:new=old, DOS answers 63 FILE EXISTS, the kernel returns EIO), asim only, not run on a drive; fail_create=path makes a write-open of that path fail with EIO; fail_read_open=(path, errno) makes a read-open of that path fail with errno. Names: a component over 14 characters is ENAMETOOLONG (c64fs).
    cooked=True makes a read of fd 0 stop after the first LF, as the console's cooked mode does (a read at the end of stdin returns 0 bytes).
    poke maps an offset in the program image (a link address, e.g. a label from build/p/<prog>.lbl) to bytes written there before the first instruction: a board or a table to start from.
    kbd=True models the keyboard and clock a game polls: KEYCNT ($C6) is 1 while stdin has bytes left, the jiffy clock ($A0-$A2, big-endian) starts at jiffy0 and each YIELD advances it by yield_jiffies, and TIME answers it (A/X/Y = lo/mid/hi)."""
    if MPU is None:
        raise RuntimeError("py65 not installed")
    with open(path or os.path.join(ROOT, "build", "root", "bin", prog), "rb") as f:
        image, bss, header = cx_load(f.read(), BASE_PAGE)
    res = Result()
    res.header = header
    res.files = dict(files or {})
    mem = [0] * 65536
    base = BASE_PAGE << 8
    mem[base:base + len(image)] = list(image)
    for off, b in (poke or {}).items():
        mem[base + off:base + off + len(b)] = list(b)
    # argv: strings and the pointer array well above the program (the real layout puts them at the
    # end of the process's run; only the pointers matter to the program)
    top = 0xC000
    ptrs = []
    for a in [prog] + list(args):
        b = a.encode() + b"\0"
        top -= len(b)
        mem[top:top + len(b)] = list(b)
        ptrs.append(top)
    top -= 2 * (len(ptrs) + 1)
    top &= 0xFFFE
    for i, p in enumerate(ptrs):
        mem[top + 2 * i] = p & 0xFF
        mem[top + 2 * i + 1] = p >> 8
    mem[0x20], mem[0x21], mem[0x22] = top & 0xFF, top >> 8, len(ptrs)
    cpu = MPU(memory=mem, pc=base)
    jf = [jiffy0]

    def sync():
        if kbd:
            mem[0xC6] = 1 if stdin else 0
            mem[0xA0], mem[0xA1], mem[0xA2] = (jf[0] >> 16) & 0xFF, (jf[0] >> 8) & 0xFF, jf[0] & 0xFF
    sync()
    fds = {}
    writes = [0]
    renames = [0]
    next_fd = [3]

    def cstr(addr):
        s = bytearray()
        while mem[addr]:
            s.append(mem[addr])
            addr += 1
        return s.decode("latin-1")

    def ret(carry, a=None):
        if a is not None:
            cpu.a = a & 0xFF
        if carry:
            cpu.p |= 1
        else:
            cpu.p &= ~1
        lo, hi = mem[0x100 + ((cpu.sp + 1) & 0xFF)], mem[0x100 + ((cpu.sp + 2) & 0xFF)]
        cpu.sp = (cpu.sp + 2) & 0xFF
        cpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF

    def r(n):
        return mem[n] | mem[n + 1] << 8

    n = 0
    while True:
        name = SYS.get(cpu.pc)
        if name:
            fd = cpu.a
            mem[0x08:0x20] = [0xA5] * 0x18   # $08-$1F is the kernel's syscall scratch: a syscall may change it
            if name == "EXIT":
                res.exit = cpu.a
                res.mem = bytes(mem)
                break
            elif name == "OPEN":
                path_, flags = cstr(r(2)), cpu.a
                if flags & 0x03 and toolong(path_):
                    ret(True, ENAMETOOLONG)
                    continue
                if flags & 0x03 == 0:             # read
                    if fail_read_open and path_ == fail_read_open[0]:
                        ret(True, fail_read_open[1])
                        continue
                    if path_ not in res.files:
                        ret(True, ENOENT)
                    else:
                        fds[next_fd[0]] = [path_, 0, False]
                        ret(False, next_fd[0])
                        next_fd[0] += 1
                elif fail_create and path_ == fail_create:
                    ret(True, 5)
                else:
                    res.files[path_] = b"" if flags & 0x20 or path_ not in res.files else res.files[path_]
                    fds[next_fd[0]] = [path_, len(res.files[path_]) if flags & 0x40 else 0, True]
                    ret(False, next_fd[0])
                    next_fd[0] += 1
            elif name == "CLOSE":
                if fd in fds:
                    del fds[fd]
                    ret(False, 0)
                else:
                    ret(True, EBADF)
            elif name == "CONMODE":
                res.conmodes.append(cpu.a)
                ret(False, 0)
            elif name == "READ":
                if fd == 0 and stdin is not None:
                    res.marks.append(len(res.out))
                    n_ = r(4)
                    if cooked and b"\n" in stdin[:n_]:
                        n_ = stdin.index(b"\n") + 1
                    data, stdin = stdin[:n_], stdin[n_:]
                    addr = r(2)
                    mem[addr:addr + len(data)] = list(data)
                    mem[4], mem[5] = len(data) & 0xFF, len(data) >> 8
                    sync()
                    ret(False, 0)
                elif fd not in fds or fds[fd][2]:
                    ret(True, EBADF)
                else:
                    f = fds[fd]
                    data = res.files[f[0]][f[1]:f[1] + r(4)]
                    addr = r(2)
                    mem[addr:addr + len(data)] = list(data)
                    f[1] += len(data)
                    mem[4], mem[5] = len(data) & 0xFF, len(data) >> 8
                    ret(False, 0)
            elif name == "WRITE":
                writes[0] += 1
                if writes[0] == fail_write:
                    ret(True, ENOSPC)
                    continue
                addr, cnt = r(2), r(4)
                data = bytes(mem[addr:addr + cnt])
                if fd == 1:
                    res.out += data
                elif fd == 2:
                    res.err += data
                elif fd in fds and fds[fd][2]:
                    f = fds[fd]
                    cur = res.files[f[0]]
                    res.files[f[0]] = cur[:f[1]] + data + cur[f[1] + len(data):]
                    f[1] += len(data)
                else:
                    ret(True, EBADF)
                    continue
                ret(False, 0)
            elif name == "UNLINK":            # r0 = path
                p = cstr(r(2))
                if p in res.files:
                    del res.files[p]
                    ret(False, 0)
                else:
                    ret(True, ENOENT)
            elif name == "RENAME":            # r0 = old, r1 = new; replaces an existing new
                old_, new_ = cstr(r(2)), cstr(r(4))
                renames[0] += 1
                if renames[0] == fail_rename or toolong(new_) or toolong(old_):
                    ret(True, ENAMETOOLONG if toolong(new_) or toolong(old_) else ENOENT)
                elif rename_noreplace and new_ in res.files and old_ in res.files:
                    ret(True, 5)              # EIO, as cbm_rename maps any DOS error; nothing is touched
                elif old_ in res.files:
                    res.files[new_] = res.files.pop(old_)
                    ret(False, 0)
                else:
                    ret(True, ENOENT)
            elif name == "ISATTY":            # fd 0 is the console when tty=True
                ret(not (fd == 0 and tty), 0)
            elif name == "GETCWD":            # r0 = buffer, A = its size
                cwd_b = res.cwd.encode() + b"\0"
                if len(cwd_b) > fd:
                    ret(True, ENOENT)
                else:
                    mem[r(2):r(2) + len(cwd_b)] = list(cwd_b)
                    ret(False, 0)
            elif name == "CHDIR":             # r0 = path; only the directories given in dirs= exist
                p = cstr(r(2))
                if p in dirs or p == "/":
                    res.cwd = p
                    ret(False, 0)
                else:
                    ret(True, ENOENT)
            elif name == "STAT":              # r0 = path, r1 = 16-byte buffer: type, nlink, size(3), ...
                p, buf = cstr(r(2)), r(4)
                if p in res.files or p in dirs or p == "/":
                    isdir = p in dirs or p == "/"
                    size = 0 if isdir else len(res.files[p])
                    mem[buf:buf + 16] = [2 if isdir else 1, 1, size & 0xFF, size >> 8, 0, 0] + [0] * 10
                    ret(False, 0)
                else:
                    ret(True, ENOENT)
            elif name == "SPAWN":            # r0 = path, r1 = argv pointers (NUL-ended), A = pin, X = pout, Y = flags
                argv, ap = [], r(4)
                while r(ap):
                    argv.append(cstr(r(ap)))
                    ap += 2
                res.spawns.append((cstr(r(2)), argv, cpu.a, cpu.x, cpu.y))
                ret(False, 2 + len(res.spawns))  # a fake pid; the child is recorded, not run
            elif name == "WAIT":             # A = pid ($FF: any), nothing is ever reaped
                # All spawns succeed in the host sim: return exit code 0 in X
                cpu.x = 0
                ret(True)
            elif name == "KILL":
                ret(False, 0)
            elif name == "GETPID":
                ret(False, 1)
            elif name == "PROCINFO":         # no process table: the list is empty
                ret(True)
            elif name == "YIELD":
                jf[0] = (jf[0] + yield_jiffies) & 0xFFFFFF
                sync()
                ret(False, 0)
            elif name == "TIME":             # A/X/Y = jiffies lo/mid/hi
                ret(False, jf[0])
                cpu.x, cpu.y = (jf[0] >> 8) & 0xFF, (jf[0] >> 16) & 0xFF
            elif name == "PIPE":             # not modelled: a pipeline is refused, not faked
                ret(True, 38)                # ENOSYS
            else:
                raise RuntimeError("syscall %s not modelled (pc $%04X)" % (name, cpu.pc))
            continue
        if mem[cpu.pc] == 0:
            raise RuntimeError("BRK at $%04X after %d steps" % (cpu.pc, n))
        cpu.step()
        n += 1
        if n > limit:
            raise RuntimeError("no exit after %d steps, pc $%04X" % (n, cpu.pc))
    res.steps = n
    res.cycles = cpu.processorCycles  # 6502 cycles, the modelled syscalls excluded
    res.mem = mem
    return res
