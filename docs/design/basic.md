# L3: a compiled BASIC on the p-code VM

Status: design draft, 2026-11-19. Story L3 in `docs/roadmap.md` (E1); the VM is
`docs/design/pvm.md`. Nothing here is built yet; numbers marked *estimate* are guesses to be
replaced by measurements.

## 1. Decisions (owner, 2026-11-19)

- **The compiler runs on the machine, written in the mini C** (`tools/cc.py`'s language),
  compiled to p-code by `cc.py --pcode` and run on the shared VM. It is the first real program
  in the mini C and a step toward a self-hosted kit: an on-system mini-C compiler is planned
  (L5), and the mini C justifies its small size by fitting on the machine. The language grows
  only by what the BASIC compiler needs, and stays small enough to self-host.
- **Numbers are decimal fixed point**, with one eye on a BCD mode (the 6502's decimal mode).
- **The integer type is signed** (the mini C's `int`, landing separately).
- From E1: the dialect is congruent with Microsoft BASIC (2.0 is the floor), the BASIC is
  compiled even when used as an interpreter, and `basic.s` is replaced, not grown.

## 2. Shape

One p-code program, `/bin/basic`: the editor, the compiler and the runtime, in one process
on `/lib/pvm`.

- **The program is kept as text.** Each numbered line is stored as typed (lightly normalised:
  upper-case keywords, single spaces), sorted by line number. `LIST` prints it. `SAVE` writes a
  plain text file and `LOAD` reads one, so a listing can be edited with `edit`, piped,
  `grep`ped and diffed: least surprise on a Unix-like system. Tokenising in memory is a later
  size optimisation, if text measures too big.
- **`RUN` compiles, then runs.** The whole program is compiled to bytecode in a buffer in the
  same process, then called. It is not exec'd, so there is no second process, no second load,
  and the runtime is shared. Compile errors stop before anything runs, reported as MS does
  (`?SYNTAX ERROR IN 20`).
- **Immediate mode** compiles the one line into a scratch buffer and runs it against the
  variables left by the last `RUN`. As in MS BASIC, editing a line clears the variables.
- **Running a file.** `basic prog.bas` loads, compiles and runs a file, then exits with its
  status, so BASIC programs work as commands in pipelines.
- **The runtime** (number formatting, fixed point, strings, I/O) is p-code functions plus
  small native helpers, as `cc.py --pcode`'s helpers are. The compiled program `CALL`s it.
  The VM gains no opcodes unless a measurement asks for one (`pvm.md` §4 item 5).

## 3. Numbers

- `A%`: a 16-bit signed integer, one VM cell. Integer loops can use it for speed.
- `A`: decimal fixed point, a 32-bit signed binary integer scaled by 10,000. That gives
  ±214,748.3647 to 4 decimal places. `0.1 + 0.2` prints `.3`; money works; `PRINT`, `STR$`
  and `VAL` convert without binary-fraction rounding. Multiply and divide go through a 64-bit
  intermediate. Overflow is `?OVERFLOW ERROR`, as in MS.
- **Numbers live on a number stack of their own,** in the runtime's memory, not the VM's eval
  stack. A 4-byte value would take two of the 8 entries an expression may use, and every
  operation is a runtime call anyway. The compiler emits `CALL`s (push a variable or a
  constant, add, multiply, compare, store). If the calls dominate code size or time, that is
  the measurement that would justify VM opcodes.
- **BCD, later.** Only the runtime touches a number's bytes; the compiler sees an opaque slot
  of `NUMSIZE` bytes. A BCD representation (add and subtract under `SED`, printing by nibbles)
  can then replace the binary one behind the same calls, or sit beside it as a mode. The same
  decimal scale keeps the user-visible behaviour unchanged. A 4-byte packed BCD would hold
  only ±9999.9999, so a BCD mode probably wants 5 or 6 bytes; `NUMSIZE` is a constant so that
  stays open.

## 4. What the mini C needs first (L3a)

The BASIC compiler needs more than `cc.py` has today:

- character literals (`'A'`);
- `&&`, `||`, `!`;
- `break` and `continue`;
- `%`;
- string literals as `char *` values, not only inside `puts`;
- syscalls from C: `read`, `write`, `open`, `close` and `exit`, as builtins that become `SYS`
  ops;
- a way to call native runtime helpers, declared `extern`.

Nothing more until the compiler asks. **The native back end is frozen at the L2 language:**
new features are p-code only, and the native back end refuses them by name. The p-code back
end is the mini C's future; the native one stays as a reference and as the benchmark row.

## 5. Slices

The lesson of the earlier attempts at a compiled BASIC, which produced nothing, still stands:
prove the whole path with one tiny program end to end before widening anything.

- **L3a. The mini C grows** (§4). Each feature is tested on the host under py65.
- **L3b. Hello, end to end.** `/bin/basic` (p-code, from mini-C source in the repo, built by
  the Makefile) gets the line store, `LIST`, `NEW`, `RUN`, and `PRINT` of a string literal. It
  runs on the host (py65) and on the machine under VICE, typed at the shell. This slice also
  adds the Makefile rule that builds p-code programs.
- **L3c. Numbers and control flow:**
  - the fixed-point runtime and `%` variables;
  - `LET` and expressions;
  - `PRINT` of numbers with MS spacing;
  - `IF`/`THEN`, `GOTO`, `GOSUB`/`RETURN`, `FOR`/`NEXT` (`STEP`), `END`/`STOP`.
- **L3d. Strings and arrays:**
  - string variables and a string heap with garbage collection;
  - `LEFT$`, `MID$`, `RIGHT$`, `LEN`, `CHR$`, `ASC`, `STR$`, `VAL`;
  - `DIM`;
  - `INPUT`.
- **L3e. Files and acceptance:**
  - `SAVE`, `LOAD` and `basic FILE`;
  - error messages;
  - the period-style listings (written for this, not copied) that the roadmap's acceptance
    names;
  - `/bin/basic` replaced; `basic.s` retired.

## 6. Budget and gate

The user pool is 39,680 bytes; the VM is 2,544, shared. *Estimate:* the compiler and runtime
come to 10 to 14 KB of p-code.

**Gate:** at the end of L3c, measure the size on disk and the free memory a program gets
(`BYTES FREE` on start, as MS prints it). If that leaves less than 16 KB for program text,
compiled code, variables and strings, stop and rethink before L3d. The options then are
tokenised text, freeing the source while running, or a resident runtime library on E2's
loader.

## 7. Open questions

- **Compile speed.** The compiler is p-code, at the VM's speed. *Estimate:* a 100-line
  program compiles in about a second. Measure it in L3c. If it is slow, the lexer and
  line-table helpers become native first.
- **Where the compiled code goes during an edit-run cycle.** It is rebuilt on each `RUN`; a
  `CONT` after `STOP` must not survive an edit (MS's rule).
- **Variable names.** MS keeps two significant characters; BBC-style long names are L4. The
  L3 symbol table should store full names and compare two characters, so that L4 is a switch
  rather than a rewrite.
