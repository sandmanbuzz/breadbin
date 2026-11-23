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

### 6.1 Runnable size: the plan (owner direction 2026-11-20)

A `16384 BYTES FREE` that runs a third of that is not acceptable; the shell leaves about 31 KB.
Options the owner listed: a separate code arena, a resident runtime, the compiler as a child that
is released when done, immediate mode split from the compiler.

*Where the bytes are* (L3c tip, from the object sizes): the compiler and editor about 7.5 KB
(p-code 7.1 KB and natives 2.5 KB, less the 2 KB the running program needs: the number core,
`rt_*`, `c_fmt`); runtime about 2 KB; buffers and stacks about 1.5 KB; the VM library 2.5 KB
(shared); the arena 16 KB. At `RUN` three things are live: the text T, the code C (about 2 T
today) and the compiler K. **The peak is T + C + K, and only the peak limits a program.** So:

- A separate code arena adds nothing alone (T + C shares one pool either way).
- A resident runtime or a compiler child frees K (7.5 KB) *after* compiling: room for variables,
  arrays and strings at run time, but not for a larger program. A child gains about 2 KB at the
  peak (the runtime is not needed while compiling); it pays a load per `RUN`, instant with the
  REU cache or UCI, seconds on a bare 1541.
- Splitting immediate mode out of the compiler does not shrink K (a line is compiled the same way).

*Levers on the peak, in order of return:*
1. **Denser code (C about 1.1 T).** Every number operation is a 3-byte `CALL` today and a
   variable access 6; `A=A+B*2` is about 30 bytes of code for 8 of text. One-byte opcodes for the
   numeric operations (the VM's free opcode range, a native table behind them) and a 2-byte
   variable load halve C. At the same arena T + C = 16 KB gives T about 7.5 KB (5.4 KB today), and
   the compiler emits and the VM runs fewer bytes, which is also the compile-speed lever.
   *Landed (2026-11-20, XOPs, `pvm.md` section 4 item 5):* 289 lines of a mixed test program
   fit where 208 did (+39%). It cost about 350 bytes (the VM table and handler, the routines, a
   56-byte vector table) and a library page, so the arena went to 16,128 bytes.
   *Landed (XOP calls):* the 12 hottest compiler externs (`c_sp`, `c_tok`, `c_emit`, `c_op1`,
   `c_ldv`, `c_digit`, `c_ncall`, `c_stv`, `c_room`, `c_opw`, `c_letter`, `c_ult`) are called by a
   one-byte XOP (`extern ... /* xop N */`; the 12 free slots E8-FE) instead of a 3-byte CALL:
   the image is 648 bytes smaller on disk, and the arena is back at 16,384. At the shell the
   arena fits to between 16,640 and 16,896 (measured: 16,640 loads, 16,896 is "out of memory"),
   so the margin at 16,384 is 256 to 512 bytes. The code is still well above 1.1 T: the next
   gain is in what is left (`PRINT` strings, `FOR`/`GOSUB` as calls, `IF` branches) and in K.

   *Landed (BRK, 2026-11-20):* the arena is no longer BSS. The kernel's `meminfo` call with A not
   0 is `BRK` (`mem.s`, 45 bytes; `SYS_BRK` in `breadbin.inc`): it grows the caller's run by as
   many of the pages directly after it as are free (A = first, X = count), and exit frees them
   with the rest. `bas` asks for up to 120 pages (30,720 bytes, so an `int` offset stays
   positive), keeps what it is given, and says `bas: out of memory` below 4,096 bytes. So
   `BYTES FREE` is what the machine has: a smaller pool (the opt-in 80-column mode may take it
   to about 115 pages) gives a smaller number, never a failed start, and every byte the image
   loses is a byte of arena. Measured at the shell: the pool is 155 pages; 27 are the system, 11
   the VM library, `bas` is 47 pages (10 KB of code and data, 1.7 KB of other BSS) and the arena
   takes the 64 after it: 16,384, so the stock figure has not moved (the static arena was already
   the last page that fit); the 7 free pages below `bas` are a hole no 47-page image fits. The
   next gains are therefore all in the image, 256 bytes of arena per page saved.

   *Landed (image pass 1, 2026-11-20):* 47 pages to 42 (code 9,206 bytes, BSS 1,266): 17,664 bytes
   free at the shell (the arena takes 69 pages; measured on VICE). What paid, in bytes: the
   implicit `return 0` after a final `return` (cc_pcode; 198), `fail` as an XOP (72), the
   forward-GOTO tables sharing `ctl` (the compiler's and the run's state are never live together;
   192), output and input unbuffered (a write per character, a read per byte: 66 + 66 of BSS and
   the flush code), `need`/`c_tok` for expected tokens in place of `src[si]` compares (190), the
   frame stack 768 to 640 (`climb` split so its frames are smaller: `tools/test_bas.py` pins the
   every IF depth against the formula limit, never a frame overflow), `outn` shared by `report` and `LIST`,
   and small dedups. The p-code VM itself (11 library pages) is the next big block: the squish.

   *Landed (VM squish, 2026-11-22, `ee06ae8`):* the VM library 11 pages to 8 (2,660 to 1,992 bytes,
   `docs/design/pvm.md` §4): 18,688 bytes free at the shell (VICE), from 17,920. Paid: a `char`
   variable load or store takes one more op (`LLA`/`LA` then `LB`/`SB`), so the image grew a little
   and byte-heavy code runs a little slower. Not yet run: the full suite, JiffyDOS, hardware.
   A second pass the same day took the VM to 7 pages (1,789 bytes; `pvm.md` §4): one more page for the
   BASIC arena, with the image at 10,202 bytes (40 pages, unchanged). The banner figure was not re-read.

   *Landed (image pass 2, 2026-11-20):* 42 pages to 41 (code 9,161 bytes, BSS 1,006): 17,920 bytes
   free at the shell (VICE). Paid: `c_const`, the number reader, in assembly (about 35 bytes); the
   frame stack 640 to 416 with the nesting limit now counted in `climb` itself (2 units a call, `fn`
   2 more; budget 24); the line buffer 162 to 126 (lines to 124 characters; stock BASIC has 80). The
   trade: 11 nested parentheses and 5 levels of `ABS(` or `1+(` (was 14 and 13), and a bare `.` is
   the number 0, as MS. The frame stack is sized by measurement: a sweep of IF depth by body shape
   (including every precedence before a `(`) and a fuzz pass at 416 and 384 bytes, overflowing at 320;
   the first cut, sized by parentheses alone, overflowed on a mixed-precedence formula, and that
   formula is a test.

2. **A smaller K.** Native `getline`, `cline`, `var`, `constant`, `match` and `move` (the profile's
   top entries) cost less than the p-code they replace; each KB of K is 0.3 KB of T.
3. **Compile to a file, run from a runner.** `bc prog.bas` writes dense code; a runner holding
   only the runtime (2 KB) and the VM runs it with about 24 KB for code (about 20 KB of source
   equivalent), no text, no compiler. Interactive `bas` stays the small-program path; the
   file route is the big-program path, and the SDK story (L3f). Needs code that is position-bound
   to a load base and an entry table for the runtime (a build id check).
4. **REU/Recommended tiers** may spill text or code; never required.
Rejected: dropping T and decompiling `LIST` from code (loses REM text and layout; heavy).

*Order:* 1 and 2 first (they also fix compile speed), measured against the fixture; then 3. The
banner stays `BYTES FREE` = arena minus text until the code is dense enough that it is honest to
within about 10 %.

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
