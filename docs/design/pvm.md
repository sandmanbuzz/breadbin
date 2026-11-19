# L0: the p-code VM (E1, `docs/roadmap.md`)

Status: L0 landed 2026-11-18 (decision, and the port running under the host simulator); L1 in
progress: speed measured, frame stack bounded (§3, §6). The owner's direction (roadmap E1): a compact p-code VM,
not an LLVM-like toolchain scaled down; the BASIC and the mini C compile to it; memory is king,
I/O second; fixed point in the MVP, floating point allowed for and not committed.

## 1. Constraints the VM must live inside

- **Zero page.** A program owns `$23–$2F` (13 bytes, `src/prog.cfg`); `$30–$3F` belongs to the
  user library (`src/lib/lib.inc`) only when the program links it; `$02–$07` are `r0–r2`, the
  syscall arguments; `$08–$1F` is kernel syscall scratch, saved per process, clobbered only by
  this process's own syscalls (the IRQ path does not touch it). All of `$02–$3F` is saved per
  process (`ZPSAVE`). `$40–$5F` is the kernel's; `$60–$8F` is free but **not** saved per process,
  so a second VM process would trample it. Extending the save is not free: the slot page holds
  `SAVESZ` = 190 bytes of zero page and stack, the cwd at 192 and the name at 240 (2 spare
  bytes), and the owner has ruled out zero page as kernel room.
- **Stack.** 128 bytes are saved per process (`STKSAVE`). A VM that keeps a return address per
  bytecode call level on the 6502 stack runs out at about 30 levels, less with native calls.
- **Programs are CX images**, linked twice (`%S` = `$0000` and `$0100`) and turned into a
  relocatable file by `tools/cx.py`. Anything the VM's bytecode contains that is an address must
  be emitted as a ca65 `.word` so the relocation sees it.
- **Syscalls** are `jsr SYS_name` at `$CF00 + 3n`, arguments in A, X, Y and `r0–r2`.
- **Space.** The pool is 155 pages and stays there; per-program VM copies are acceptable for L1,
  a shared copy is E2's job (SL1–SL3).

## 2. Candidates

| | What it is | Licence | Verdict |
|---|---|---|---|
| SWEET16 (Wozniak, 1977) | 16 registers in zero page, ~300-byte interpreter | Apple; unclear | ideas only. Register machine: 32 ZP bytes we do not have, and expression code is longer than on a stack machine. |
| UCSD p-System (I.5 / II / Apple Pascal) | stack machine, byte-coded, segments, reals, sets, strings | the 2006 source release is non-commercial only; the Apple interpreter is proprietary | **design reference only.** Proven and documented to the last opcode, but a usable interpreter would be a clean-room write, and the ISA brings the p-System's segment, set and string machinery with it. Worth keeping: code segments loaded on demand (an overlay model for E2), and its opcode list as a coverage check. |
| PLASMA (David Schmenk) | stack machine, even-numbered byte opcodes, split 16-deep eval stack in ZP, frame stack, `NATV` escape to native code; compiler in C and self-hosted | MIT | **adopt the ISA and the VM, ported** (§4). |
| Lawless Legends (extended PLASMA) | PLASMA plus game-specific extensions | Apache-2.0 | ideas only; code only if backed into a corner, the owner's call. |
| MS BASIC-M6502 v1.1 (Microsoft, 1978) | the BASIC interpreter, with its tokenizer, number I/O and FP package | MIT | **the L3 source**: tokenizer, `PRINT`/`INPUT` number formatting, and the FP package when floating point comes. Not a VM. |

UCSD was the owner's addition and gets a fair hearing: the reason to throw it back out is not
quality but cost. Its value is the interpreter plus the p-System around it; we would get neither
(licence), and a clean-room interpreter for its ISA would be larger than PLASMA's 2.2 KB for no
measured gain in density. If L1 turns up a density or speed problem PLASMA cannot fix, the UCSD
opcode set is the first place to look.

## 3. Measurements (the same benchmark through each compiler, 2026-11-18)

Sieve of 1,000, recursive gcd, a sum loop, and a `main` that calls them. Code bytes, excluding
each runtime unless said:

| Compiler | sieve | gcd | sum | main | total | runtime |
|---|---|---|---|---|---|---|
| PLASMA (`xplasm -AO`, bytecode) | 83 | 42 | 51 | 47 | **223** | VM 2,226 bytes; +3 bytes per function entry |
| cc65 `-Oirs` (native) | 247 | 106 | 188 | 106 | 647 | cc65 runtime not counted |
| `tools/cc.py` (native, ours) | 699 | 212 | 494 | 300 | 1,705 | 421 |

PLASMA bytecode is 2.9 times as dense as cc65 and 7.6 times as dense as `cc.py`. The VM pays for
itself after about 2 KB of `cc.py` output, which the shell's own utilities exceed; once it is
shared (E2) it pays from the first program.

**Speed** (L1), 6502 cycles for the whole benchmark, each less an empty program's under the same
harness (`python3 tools/pvm_bench.py`, which prints these and checks every result is 469, for
cc65 only its low byte, the exit status being 8 bits; C
source `src/pvm/test/bench.c`):

| | cycles | speed relative to the VM |
|---|---|---|
| PLASMA bytecode on the port (`tools/asim.py`) | 472,875 | 1 |
| `tools/cc.py` native (py65, `tools/test_cc_run.py`'s harness) | 609,107 | 0.78 |
| cc65 `-Oirs` native (`sim65 -c`) | 146,347 | 3.23 |

The VM runs this benchmark faster than our own native compiler and at about a third of cc65's
speed; its bytecode is a third of cc65's code size (above), the 2,533-byte VM not counted, which
pays for itself only across programs once it is shared (E2). It executes 8,358 ops, about 57 cycles an op on
average. The simulators count documented cycles and do not model badlines, so these are CPU
ratios: on a C64 the badlines and the interrupt slow all three alike. cc65's start-up clears the
program's BSS (220 bytes here, not in the empty program), so its figure carries a few thousand
cycles the others do not, under 2 %. The VM figure was 463,755 before the frame-stack check
(§5), 471,285 before the push guards (§4 item 2) and 472,248 before `LEAVE`'s checks.

The port (§4) is 2,533 bytes (`src/pvm/pvm.s`, segment `PVM`, the opcode table at offset `$100`
with no alignment padding left, an assert keeping it under 8) plus 25 bytes of BSS.

The C64 VM (`src/vmsrc/c64/plvmc64.s`, upstream commit `f209e30`, 2026-11-03) has no KERNAL
calls in its core: the loader and `cmd` around it do. Opcodes are even, `$00–$C4`; `$C6–$FE`
(29 opcodes) are free.

## 4. Decision: PLASMA's ISA and VM, ported to ca65 and to Breadbin

Ported changes, each forced by §1:

1. **Zero page.** The eval stack drops from 16 to 11 entries and lives in `$08–$1F`, split
   low/high as upstream (`ESTKH` `$0A–$14`, `ESTKL` `$15–$1F`; `$08–$09` are a guard that the
   byte loads, which write one slot below TOS, may touch). It is kernel syscall scratch, so the
   syscall path (item 4) saves the stack around the call. The VM's own state is `$23–$36`: the
   self-modifying fetch routine (10 bytes at `$23`, the instruction pointer is its operand),
   `IFP`, `ESP`, a `JMP` trampoline, `TMP`, `DVSIGN`, `SRC`. The program keeps `$39–$3F`
   (`src/pvm/pvm.cfg`). A p-code program does not link `lib.s`'s zero-page users. Nothing in
   `$60–$8F` is used.
2. **Return IPs on the frame stack**, not the 6502 stack. Recursion depth is then bounded by the
   frame stack (in the program's BSS), not by `STKSAVE`. A function that starts with
   `JSR pvm_interp` is entered without that `JSR` running: `CALL` pushes the return IP and jumps
   to the bytecode after it. Native code that calls bytecode pushes a marker the matching `RET`
   turns back into an `RTS`; bytecode calling native code uses the 6502 stack, as upstream.
   `NATV` pushes `RET`'s address, so a native tail's `RTS` returns from the function as it does
   upstream (where the call was a `JSR`). Frameless functions only: `RET` does not undo
   `ENTER`'s frame and spill.
   **Spilling:** PLASMA's compiler leaves a caller's pending values on the eval stack across a
   call (`n + f(n - 1)` is `LLW; DUP; DECR; CALL; ADD`), which upstream's 16 entries absorb to
   about 15 levels. Here `ENTER` moves the caller's pending entries to the frame stack when fewer
   than 8 would be free, and `LEAVE` puts them back under the results (none for `#0`, two for
   `#2`), so that code recurses as deep as the frame stack allows (about 7 bytes a level for
   that function). Frameless functions (no `ENTER`) do not spill. The eval stack index is
   checked at every call and return, and **every push is guarded** (`dex; bmi`, the owner's
   decision of 2026-11-18): a 12th entry exits with status 12 (`ENOMEM`) before it is written,
   instead of wrapping and coming back into range with wrong values. Twelve push sites are
   guarded (the pushes in `DIVMOD`, `_DIV` and `SYS` follow at least as many pops), through four
   `jmp pvm_overflow` stubs within branch range: 36 bytes, less the 5 bytes of table padding
   they absorbed. The §3 benchmark makes 3,336 guarded pushes, 6,672 cycles (1.4 %); the
   measured net change was +963 cycles, as the moved code crosses pages differently, so the
   net figure is layout luck. `LEAVE` checks both limits before it puts spilled entries back
   under the results (9 bytes): more results than fit above them would be a 12th entry, which
   the shift wrote into page 1, and an index past empty (the callee popped more than it pushed)
   less the spill count could land back in range, where `RET` would not see it. Pops are not
   guarded: a pop past empty is caught at the next call or return, but a push before then
   writes `$20`, the low byte of argv. A native callee may return any
   index; the next push, call or return catches it.
   Cheaper guards are open for later.
3. **Relocation.** Our front ends emit bytecode as ca65 `.byte` and `.word` lines in the program's
   source, linked with the VM as an ordinary CX program. No PLASMA module loader.
4. **Syscalls**: one opcode, `SYS n` (`$C6`, the first free one), instead of a native shim per
   call. Bits 0–4 of `n` are the syscall number; TOS goes to `A` (low) and `X` (high), and with
   bit 7 set the low byte of the next entry goes to `Y`. `r0–r2` are stored beforehand with
   `SAW`. The result `A | X << 8` is pushed, or -1 with the errno in `pvm_errno` when carry is
   set; `pvm_errno` is 0 after a successful call. The eval stack is copied out and back around the call (`tools/asim.py` now trashes
   `$08–$1F` on every syscall, so the simulator checks this).
5. **Numbers.** Fixed point (format chosen at L3) as runtime calls first; opcodes in the free
   range only if L3 measures a need. FP reserves opcodes, nothing more.
6. **Licence record.** The ported file keeps the MIT notice and the upstream URL and commit in its
   header, and the adoption is recorded here and in `docs/design/fast-io.md` §4, as the licence
   policy asks.

Not adopted: the PLASMA module loader and `cmd`, the 6502 return-address convention (item 2),
and, for now, the PLASMA language. Its self-hosting compiler makes it a cheap third front end;
that is the owner's call, after L2.

Rules for our front ends, found while porting:

- **Expression depth.** One function's own expression, with the arguments of a call inside it,
  must fit in 8 entries (what `ENTER` guarantees); pending values across calls are the VM's
  job (spilling, above), except across frameless calls. Front ends check depth at compile time.
- **IP offset wrap.** The VM keeps the IP as a base plus `Y`; ops that cross page boundaries
  renormalise. Straight-line code longer than about 250 bytes without a branch, call or
  `LA`/`LLA` must get a renormalising op from the front end (upstream has the same limit).
- **`SEL` tables:** a count byte, then (value, offset) word pairs sorted by value, each offset
  relative to its own offset word; the default case follows the table.

## 5. Risks

- **Speed.** A bytecode VM is several times slower than native code; the I/O path is unaffected
  (syscalls are native). L1 measures it; hot routines can be `NATV` or library code.
- **Eval stack depth 11.** PLASMA's compiler assumes 16. Spilling covers recursion; a single
  expression deeper than the free entries (8 at a framed function's entry) exits with `ENOMEM`
  where upstream's 16 would run (the push guards, §4 item 2). Our front ends check depth at
  compile time; PLASMA's compiler does not.
- **Frame stack size.** The program sizes its frame stack: `pvm_init` takes the top in `A/Y`
  and the bottom in `r0` (at least `$0100`). Every allocation (a return IP, `ENTER`'s spill,
  count and frame) goes through `fsalloc`, which exits with `ENOMEM` before writing below the
  bottom; upstream does not check. Cost: 1.6 % on the §3 benchmark, 3 code bytes (the five
  inline allocations became one routine; `pvm_init` copies `r0`) and 2 of BSS. Nothing checks
  the caller's `r0`: a caller that forgets it gets an arbitrary bound.
- **Zero page shared with `lib.s`.** The VM's `$34–$35` and the program's `$39–$3B` are also the
  user library's `lp3`, `lt3` and `lval`; a p-code program must not link those users. Nothing
  enforces it yet (`src/pvm/pvm.cfg` says so).
- **Syscall scratch.** Any kernel change that starts using `$08–$1F` in the IRQ path breaks
  item 1. A note in `k.inc` keeps that visible.
- **Upstream drift.** The port is a fork of one file; upstream fixes are merged by hand.

## 6. Acceptance

- **L0** (this document): the owner's review, and a host simulator run (`tools/asim.py`, py65)
  of a loop, recursion 50 deep and a syscall (`write`) on the ported VM. Met by
  `tools/test_pvm.py`: a loop, recursion 200 deep with the 6502 stack balanced afterwards,
  arithmetic and compares, `write` with a value surviving under it and a bad descriptor giving
  -1 and `EBADF`, a native call, `SEL`, compiler-shaped recursion 120 deep with a pending value
  at every level (spilling), spills under `#0` and `#2` functions, the overflow trap, `NATV` from a called function, and the benchmark
  as upstream's compiler emits it (`src/pvm/test/bench.s`, result 469, checked independently).
- **L1**: the ported VM as a CX program under VICE; size and speed of the §3 benchmark against
  `cc.py` and cc65 recorded here (done); the eval-stack overflow trap tested (done in L0), and
  the push guards, through every guarded op, each guard's removal failing the test (done); the
  frame stack bounded and its trap tested at the boundary (204 levels of plain recursion fit the
  test's 1 KB, 205 trap), with nothing written below it, and under VICE (`tests/test_pvm_machine.py`) (done). No Makefile
  rule builds p-code programs yet: with no front end there is nothing to build but tests; L2
  adds one with the first compiler.

## 7. Sources

- PLASMA: <https://github.com/dschmenk/PLASMA>, MIT, Copyright David Schmenk. VM read at
  `f209e30` (2026-11-03).
- BASIC-M6502: <https://github.com/microsoft/BASIC-M6502>, MIT, Copyright Microsoft Corporation.
- UCSD p-System: the 2006 source release (non-commercial licence), and the published p-machine
  descriptions. Read for design only.
- SWEET16: Wozniak, "SWEET16: The 6502 Dream Machine", BYTE, November 1977. Ideas only.
- Lawless Legends: <https://github.com/badvision/lawless-legends>, Apache-2.0. Ideas only.
