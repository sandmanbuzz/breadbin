# L0: the p-code VM (E1, `docs/roadmap.md`)

Status: L0 decision draft, 2026-11-18. The owner's direction (roadmap E1): a compact p-code VM,
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
shared (E2) it pays from the first program. Speed has not been measured yet: that is L1.

The C64 VM (`src/vmsrc/c64/plvmc64.s`, upstream commit `f209e30`, 2026-11-03) has no KERNAL
calls in its core: the loader and `cmd` around it do. Opcodes are even, `$00–$C4`; `$C6–$FE`
(29 opcodes) are free.

## 4. Decision: PLASMA's ISA and VM, ported to ca65 and to Breadbin

Ported changes, each forced by §1:

1. **Zero page.** The eval stack drops from 16 to 12 entries and lives in `$08–$1F` (24 bytes,
   split low/high as upstream). It is kernel syscall scratch, so the syscall path (item 4) saves
   the live entries around the call. The VM's own state goes in `$23–$3F`: the self-modifying
   fetch routine (10 bytes, the instruction pointer is its operand), `IFP`, `PP`, `TMP`, `SRC`,
   `DST`. A p-code program does not link `lib.s`'s zero-page users; the runtime supplies what it
   needs. Nothing in `$60–$8F` is used.
2. **Return IPs on the frame stack**, not the 6502 stack. Recursion depth is then bounded by the
   frame stack (in the program's BSS), not by `STKSAVE`.
3. **Relocation.** Our front ends emit bytecode as ca65 `.byte` and `.word` lines in the program's
   source, linked with the VM as an ordinary CX program. No PLASMA module loader.
4. **Syscalls**: one opcode, `SYS n` (from the free range), with a table in the runtime saying how
   many eval-stack words go to `A`/`r0`/`r1`/`r2` and what comes back. One opcode instead of a
   native shim per call.
5. **Numbers.** Fixed point (format chosen at L3) as runtime calls first; opcodes in the free
   range only if L3 measures a need. FP reserves opcodes, nothing more.
6. **Licence record.** The ported file keeps the MIT notice and the upstream URL and commit in its
   header, and the adoption is recorded here and in `docs/design/fast-io.md` §4, as the licence
   policy asks.

Not adopted: the PLASMA module loader and `cmd`, the 6502 return-address convention (item 2),
and, for now, the PLASMA language. Its self-hosting compiler makes it a cheap third front end;
that is the owner's call, after L2.

## 5. Risks

- **Speed.** A bytecode VM is several times slower than native code; the I/O path is unaffected
  (syscalls are native). L1 measures it; hot routines can be `NATV` or library code.
- **Eval stack depth 12.** PLASMA's compiler assumes 16. The front ends we write can check depth
  at compile time; L1 confirms the VM traps overflow instead of wrapping into `r0–r2`.
- **Syscall scratch.** Any kernel change that starts using `$08–$1F` in the IRQ path breaks
  item 1. A note in `k.inc` keeps that visible.
- **Upstream drift.** The port is a fork of one file; upstream fixes are merged by hand.

## 6. Acceptance

- **L0** (this document): the owner's review, and a host simulator run (`tools/asim.py`, py65)
  of a loop, recursion 50 deep and a syscall (`write`) on the ported VM.
- **L1**: the ported VM as a CX program under VICE; size and speed of the §3 benchmark against
  `cc.py` and cc65 recorded here; the eval-stack overflow trap tested.

## 7. Sources

- PLASMA: <https://github.com/dschmenk/PLASMA>, MIT, Copyright David Schmenk. VM read at
  `f209e30` (2026-11-03).
- BASIC-M6502: <https://github.com/microsoft/BASIC-M6502>, MIT, Copyright Microsoft Corporation.
- UCSD p-System: the 2006 source release (non-commercial licence), and the published p-machine
  descriptions. Read for design only.
- SWEET16: Wozniak, "SWEET16: The 6502 Dream Machine", BYTE, November 1977. Ideas only.
- Lawless Legends: <https://github.com/badvision/lawless-legends>, Apache-2.0. Ideas only.
