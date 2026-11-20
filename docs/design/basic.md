# L3: a compiled BASIC on the p-code VM

Status: accepted by the owner, 2026-11-19; L3a and L3b done. Story L3 in `docs/roadmap.md`
(E1); the VM is `docs/design/pvm.md`. Numbers marked *estimate* are
guesses to be replaced by measurements.

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

**Done (2026-11-19):** all of it, in `cc.py --pcode` (the module docstring of
`tools/cc_pcode.py` has the contract: syscall results, the `extern` calling convention).
String literals were already `char *` values in L2. Tests: `tools/test_cc_pcode.py`, classes
`L3a` and `L3aRefused`, including random expressions over every operator checked against a
model in both value and branch contexts.

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

  **Done (2026-11-19):** `src/pc/bas.c` is `/bin/bas` until L3e replaces `/bin/basic` (3,813
  bytes; `mk/pvm.mk` builds every `src/pc/*.c` to `/bin`). Besides the slice it has `?` for
  `PRINT`, `;`, `REM` (its text kept as typed), `LIST` ranges, immediate mode, `BYE`/`SYSTEM`,
  and `READY.` only on a terminal, so piped use stays clean. The code generator needed from the
  mini C: `&`, `|`, `^`, `~`, `<<`, `>>`, pointer difference, `&f`, `icall` and `isatty`
  (`docs/design/s14-compiler.md`). Line numbers go to 63999, compared unsigned. Tests:
  `tools/test_bas.py` (py65) and `tests.test_pvm_machine.Basic` (typed at the shell on VICE).
  Open for L3c: the branch that resets the VM's Y past 240 straight-line bytes (`room()`) cannot
  fire yet, since every `PRINT` item ends in a `CALL`; its test comes with expressions.
- **L3c. Numbers and control flow:**
  - the fixed-point runtime and `%` variables;
  - `LET` and expressions;
  - `PRINT` of numbers with MS spacing;
  - `IF`/`THEN`, `GOTO`, `GOSUB`/`RETURN`, `FOR`/`NEXT` (`STEP`), `END`/`STOP`.
  **Landed (L3c), as built:**
  - *Program text is tokenised* at store time, MS-crunch style: a keyword outside strings and
    REM text becomes one byte (128 + its place in `kwt`), `?` is PRINT, and `LIST` spells them
    out. The first keyword in the table that matches wins, so `TOTAL` is `TO TAL`, as MS.
    Spaces are kept as typed (runs collapse), so `LIST` shows `PRINT "A"` if the user typed a
    space and `PRINT"A"` if not. A byte above 127 outside quotes is a syntax error.
  - *Errors:* compile errors carry the line; a runtime error reports the line of the code
    that raised it. `UNDEF'D STATEMENT` is raised at compile time (MS raises it when the
    GOTO runs): a difference to document. The first error is kept. Parentheses and unary
    operators nest 14 deep, and `ABS(`/`INT(`/`SGN(` count as two levels (`FORMULA TOO
    COMPLEX`; the compiler's own frames bound it). `^` takes a whole-number exponent, else `ILLEGAL QUANTITY`.
    `NEXT` of a variable whose `FOR` was replaced by another `FOR` on it is `NEXT WITHOUT
    FOR`, as MS. Deferred: Ctrl-C during a run (an endless loop needs a reset), `ON..GOTO`, `CLR`.
    Known divergences: after a `RUN` that ran out of memory compiling, an immediate `GOTO n`
    says `UNDEF'D STATEMENT` (the compile error is dropped); `RUN`, `LIST` and `NEW` are
    immediate-only, so `PRINT 1:RUN` is a syntax error.
  - *What `BYTES FREE` means:* it is the arena minus the program text. `RUN` compiles into the
    same arena, and code is about twice the text, plus variables, so a program of about a
    third of the figure (measured: 221 lines, 5.4 KB of text) is the largest that runs. The
    gate below is met to the letter and not in spirit: the owner decides before L3d between
    freeing the source while running, a second arena for code, and a resident runtime.
  - *Native helpers* (`src/pc/bas-rt.s`): the number core, `c_crunch`, `c_find`, and the
    scanner and code emitter (`c_sp`, `c_digit`, `c_letter`, `c_tok`, `c_ult`, `c_emit`,
    `c_room`, `c_op1`, `c_opw`, `c_ncall`), which work on the mini C's globals: a program with
    an `extern` exports them as `g_NAME`. Expressions are one precedence-climbing function.
  - *Measured* (`.blocks/pvm-prof.py`, py65, a 102-line, 2,714-byte program, store plus `RUN`
    to the end): 41.4M cycles (about 42 s on a PAL machine) with the compiler all in p-code
    and text stored as typed; 27.4M after tokenising, the native helpers and the climb. The
    store alone went from 40M to 9.6M. Still far from the estimate of about a second per 100
    lines in §7; what remains is spread over `getline` (4.3M), `cline`, `var` and `constant`,
    each next in line to go native.
  - *Memory:* `bas` is about 10 KB of code and 29 KB with its 16,384-byte arena, 1 KB of VM
    frames and the 2.5 KB VM library, against the 31 KB `free` shows at the shell. The first
    build with the full arena **did not load** (`sh: bas: out of memory`); 15,872 did. Fitting
    16,384 took a 768-byte frame stack (a `/* fstack N */` directive in the source, read by
    `cc_pcode`), 32 forward-GOTO fixups, a 192-byte GOSUB/FOR stack and 64-byte I/O buffers. It
    fits by about 500 bytes: the 16 KB gate is met, barely, and L3d (strings) will not fit
    without one of the options in §6.
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
- **L3f. The manuals** (owner, 2026-11-19: required, "SDK docs, basically, with a nice user
  manual and reference manual"). Compiled code may come from end users, developers, or people
  in between, and the feature does not look good to anyone until they are told about it. In
  `docs/manual/`, written as the books that came with a computer or a small Unix:
  - a **user manual**: a tutorial from `bas` to a working program, editing, running, saving,
    the immediate mode, and what is different from the C64's BASIC;
  - a **reference manual**: every statement, function, operator and error message, number
    formats and limits, one entry each, with an example that is run by a test;
  - a **developer guide (the SDK)**: the mini C (`cc.py --pcode`) and its builtins, building a
    p-code program (`src/pc/`, the Makefile rule), the VM and its calling convention, how
    BASIC's compiled code calls its runtime, `/lib/pvm`, and the tools (`asim`, `pvmlink`).

  Examples in the manuals are extracted and run by the host tests, so the books cannot drift
  from the program. Each slice from L3c on adds its reference entries as it lands; L3f is the
  user manual, the developer guide and the pass that makes the three read as one set.

## 6. Budget and gate

The user pool is 39,680 bytes; the VM is 2,544, shared. *Estimate:* the compiler and runtime
come to 10 to 14 KB of p-code.

**Gate:** at the end of L3c, measure the size on disk and the free memory a program gets
(`BYTES FREE` on start, as MS prints it). If that leaves less than 16 KB for program text,
compiled code, variables and strings, stop and rethink before L3d. The options then are
tokenised text, freeing the source while running, or a resident runtime library on E2's
loader.

**Hardware gate (owner, 2026-11-19):** at the end of L3, a run on the real Ultimate (under the
`ultimate` lock, when it is free) of `bas` typed at the shell and the acceptance listings,
to catch assumptions VICE and py65 share. Not a per-slice gate.

## 7. Open questions

- **Compile speed.** The compiler is p-code, at the VM's speed. *Estimate:* a 100-line
  program compiles in about a second. *Measured in L3c: about 27 s* after tokenising and the
  first native helpers (see L3c in §5); more of the lexer and the variable and constant code
  go native next. Measure it in L3c. If it is slow, the lexer and
  line-table helpers become native first.
- **Where the compiled code goes during an edit-run cycle.** It is rebuilt on each `RUN`; a
  `CONT` after `STOP` must not survive an edit (MS's rule).
- **Variable names.** MS keeps two significant characters; BBC-style long names are L4. The
  L3 symbol table should store full names and compare two characters, so that L4 is a switch
  rather than a rewrite.
