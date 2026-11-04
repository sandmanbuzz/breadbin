# S14: the compiler, first slice (host-side reference)

`tools/cc.py` compiles a small C subset to `as` source. It runs on the host, not on the C64, and
writes no kernel bytes. The aim is to settle the language and the shape of the emitted code
before S17 (self-host or stay in assembly) is decided. `tools/test_cc.py` is its host test.

## The subset (slice 3)

- `int` only: 16 bit, unsigned in comparisons (`<`, `>`, `<=`, `>=` compare unsigned).
- Functions with typed parameters (`int` or `char`, passed on the software stack and stored in
  each function's static parameter slots); `main` is the entry. Calls are by name.
- `char`: 8 bit, zero-extended when read; a store keeps the low byte.
- Pointers to `int` or `char` (one level), arrays of `int` or `char` (local, static storage),
  unary `*` and `&`, indexing `a[i]`; pointer `+` and `-` scale by the element. Pointers are read
  through `cc_ptr` ($2b, zero page).
- `for (init; cond; step) body`, desugared to a `while` in the parser.
- Locals declared with `int name = expr;`. They have static storage (`v_<fn>_<name>`, 2 bytes),
  so there is no recursion yet.
- Statements: declaration, assignment, expression, `if`/`else`, `while`, `return`, blocks.
- Operators: `+ -` (binary and unary minus), `== != < > <= >=`, parentheses.
- `puts("...")`: the one builtin. It prints a string literal through `sys_write`, one byte at a
  time, the way `rootfs/home/hello.s` does. String escapes: `\n \t \r \0 \\ \"`.

Slice 3 adds:

- Globals: `int|char [*] name [ [n] ] [= literal]` at top level, static (`g_<name>`), initialised
  as data (a number, a string for a char array or char pointer, or 0 for a pointer).
- `*` and `/` as binary operators: runtime routines in the emitted program (`cc_mul`: the low 16
  bits; `cc_div`: unsigned, and dividing by 0 gives 65535).
- A string literal is the address of its bytes (a char pointer); a char array takes a string,
  its size inferred when left out (a local copies it in each time the declaration runs).

Not yet: pointers to pointers, `char` return types, `#include`, `&&` `||` `!`, arrays of pointers
and string arrays of pointers (use char arrays), `*` on pointers (`p * 2` is refused).

## Emitted shape

- An expression's value is left in `acc` (16 bit: `acc` low, `acc+1` high).
- A binary operator evaluates the left side, pushes `acc` on a memory stack (`cc_stk`, 32
  levels, `cc_sp` its byte index), evaluates the right side, pops the left into `tmp`, and calls
  a runtime routine: `cc_add`, `cc_sub` (`tmp - acc`), `cc_eq`, `cc_lt` (unsigned `tmp < acc`),
  `cc_not`, `cc_swap`. `>` and `<=` are `cc_swap` then `cc_lt`, with `cc_not` for `<=`.
- A condition is tested by `ora acc,acc+1`: zero is false.
- Calling convention: `jsr fn_<name>`; the return value is in `acc`. Functions end with
  `rts`; a missing return gives 0.
- `start:` sets `cc_sp` to 0, calls `fn_main`, then `jmp sys_exit`.
- Labels: `fn_<name>`, `L<n>` for control flow, `s_<n>` for strings, `v_<fn>_<name>` for locals.
  Runtime labels are fixed (`cc_*`, `rt_puts`).

## Limits to keep in mind

Refused with a message (checked by `tools/test_cc.py`):

- Recursion, direct or mutual: locals are static, so it would give wrong answers.
- Stack use along a call chain above 31 values (`cc_stk` holds 32 two-byte values).
- Names longer than 14 characters, and names that clash ignoring case (as keeps 14 characters
  and ignores case).
- Strings longer than 254 bytes (`rt_puts` indexes with Y), strings with `\\0` (it would end
  them early), and characters above Latin-1 (`as` stores 8 bits).
- Expressions nested too deeply for the parser.
- Types must agree: a number is not a pointer (and the literal 0 is the null pointer); a pointer
  points at the same base. Checked at assignment, initialisers, arguments and `return`.
- An array of pointers; `-` of a pointer; parameters on `main` (start passes none).
- Static variables over 8192 bytes (STATIC_MAX, a project limit the owner may change).
- Programs needing more than 220 symbols (`as` holds 255, less its 35 builtins).

Accepted, by decision, and documented here for the owner:

- Comparisons are unsigned: `int x = 0 - 1; if (x < 0)` takes the false branch. C would take
  the true branch. Pinned by the executed tests. Signed compare, or refusing `<` on signed
  values, is for the owner to choose.
- Block scope is not enforced: `{ int x = 1; } x = 2;` compiles, because all locals of a
  function share one namespace. C would refuse the second use.

- `as` symbol names are at most 15 characters; the compiler refuses longer local names.
- `as` holds at most 220 symbols (`NSYM`); a large program will hit that before it hits the code
  size. The count is not checked yet.
- The software stack is 32 levels; deeper expressions are refused.
- Size on `as` (findings for S13): hello assembles to 390 bytes with 71 relocations, from 153
  emitted lines and 24 labels (about 28 names with the system names). The loop program has 194
  lines and 27 labels. Both are far under the 220-symbol table; the count is not checked yet.
- Zero page: one pair, `cc_ptr = $2b` (the string pointer for `(zp),y` in `rt_puts`). `as`
  accepted `(zp),y` with a non-zero-page pointer and emitted a silent wrong address (found on the
  machine: the string read as empty). The data area was the first placement and it was wrong.
- Run on the C64: `tests/test_compiled.py` compiles hello, a five-pass loop, and an operator
  program with a string of 82 characters (emitted over several lines), on the host,
  puts the `.s` on a copy of the test disk, runs `as` on the machine, runs the result and checks
  the output.
- Executed on a 6502 simulator on the host (`tools/test_cc_run.py`, needs ca65, ld65 and py65):
  the operator grid, wrap-around arithmetic, call return values, a long string, a long loop body
  and a 31-value expression. Mutants of `cc_lt` and `cc_swap` fail the grid.

## Open for S17

- The compiler is about 576 lines of Python for this slice (with its tests, 769). Whether it is rewritten in its own
  language depends on how the next slices (globals, `&&`, `#include`) grow it.
- The runtime routines are about 120 lines of 6502 emitted into every program. Shared routines
  in the kernel or a library would save bytes; that is a decision for S14 v1.
