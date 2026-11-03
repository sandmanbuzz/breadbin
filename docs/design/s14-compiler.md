# S14: the compiler, first slice (host-side reference)

`tools/cc.py` compiles a small C subset to `as` source. It runs on the host, not on the C64, and
writes no kernel bytes. The aim is to settle the language and the shape of the emitted code
before S17 (self-host or stay in assembly) is decided. `tools/test_cc.py` is its host test.

## The subset (this slice)

- `int` only: 16 bit, unsigned in comparisons (`<`, `>`, `<=`, `>=` compare unsigned).
- Functions with no parameters; `main` is the entry. Calls are by name.
- Locals declared with `int name = expr;`. They have static storage (`v_<fn>_<name>`, 2 bytes),
  so there is no recursion yet.
- Statements: declaration, assignment, expression, `if`/`else`, `while`, `return`, blocks.
- Operators: `+ -` (binary and unary minus), `== != < > <= >=`, parentheses.
- `puts("...")`: the one builtin. It prints a string literal through `sys_write`, one byte at a
  time, the way `rootfs/home/hello.s` does. String escapes: `\n \t \r \0 \\ \"`.

Not yet: `char`, arrays, pointers, `for`, `* /`, parameters, globals, `#include`, `&&` `||` `!`.

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

- `as` symbol names are at most 15 characters; the compiler refuses longer local names.
- `as` holds at most 220 symbols (`NSYM`); a large program will hit that before it hits the code
  size. The count is not checked yet.
- The software stack is 32 levels; deeper expressions are refused.
- Zero page: nothing is in zero page yet, except what `as` and the kernel's `sys_write` use
  (`r0`, `r1`) and the `(zp),y` pointer `cc_ptr`. The roadmap's "a few bytes of zero page" is
  still to be measured.
- Not run on the C64: the output is checked for structure (labels, branch targets, the string
  bytes, the routines per operator), not by executing it. Running it is the next step.

## Open for S17

- The compiler is about 576 lines of Python for this slice (with its tests, 769). Whether it is rewritten in its own
  language depends on how the next slices (parameters, `char`, arrays) grow it.
- The runtime routines are about 120 lines of 6502 emitted into every program. Shared routines
  in the kernel or a library would save bytes; that is a decision for S14 v1.
