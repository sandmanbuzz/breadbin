> DRAFT (2026-11-03), written by a read-only subagent from roadmap.md and src/bin/as.s and not reviewed by a human or the owner. Claims tagged U are unverified; every byte cost is an estimate. Companion: docs/design/s12-brk.md (which supersedes the brk parts here: header BSS first, then an in-place brk). Nothing here is a decision.

# S14 Compiler v0 (bc): requirements, with S12 and S13 inputs

Tags: V = VERIFIED (file:line read), U = UNVERIFIED (doc claim or my estimate). Byte costs are estimates (U) unless stated.

## 0. Facts about the machine and `as`

- Roadmap: S12 brk syscall, S13 lift `as` limits, S14 compiler, single pass, recursive descent, streaming source (V docs/roadmap.md:256-258). Language choice is an open question; Forth or compiling `basic` are fallbacks (V roadmap.md:276).
- Free zero page for programs `$23-$2F` (13 bytes), `$30-$3F` used by lib.s (V include/breadbin.inc:49). `r0`=$02, `r1`=$04, `r2`=$06, argv=$20, argc=$22 (V breadbin.inc:42-48). `$60-$8F` is unused by the kernel and is the proposed place for more (V roadmap.md:154); the compiler's real need is "measured at S14" (V roadmap.md:158).
- ~30 KB process memory, 130-byte hardware stack slice: doc claims (V roadmap.md:17-18). Pool is now 154 pages, 39,424 bytes (V CLAUDE.md status). Hardware stack size itself: U.
- Page allocator `page_alloc` (Y pages -> A first page, carry clear), `page_free` (A, Y) exists (V src/kernel/mem.s:30-33,118-119). `exec` computes npages = ceil((img+bss+args)/256) from the CX header (V src/kernel/exec.s:195-216), so a process cannot grow today. Syscall table ends at SYS_CACHE index 31 (V breadbin.inc:39); a new slot is the next entry.
- `as` today:
  - `NSYM=220`, `SYMSZ=18` (name[15] value[2] flags), `OBMAX=8192`, `RMAX=1024` relocs (V as.s:22-26). BSS = symtab 3,960 + obuf 8,192 + rbuf 2,048 + ~300 = about 14.5 KB (V as.s:57-59). Code about 4.1 KB, total 6,116 bytes (V docs/design/program-size.md top-five table).
  - Uses `$23-$28` (syp, obp, tq) (V as.s:17-19). Reads the source with `getc` line by line into `lbuf[128]`, lowercased outside quotes, over-long lines silently truncated at 127 (V as.s:211-255). Two passes: re-opens the source file each pass (V as.s:114-120), so the source must be a seekable file, not a pipe.
  - Writes a CX header `C X 1`, image size, BSS size 0, nrel, then obuf, then rbuf (V as.s:156-198). BSS size WAS always 0 (so every `.res` cost file bytes); since S12a a trailing `.res` is the header's BSS size, a `.res` followed by anything is still stored. There is no `.org`; output is position-independent via relocations.
  - Syntax (V as.s:1-12, 258-306, 327-345): one statement per line; `;` comment; `label:` (name up to 15 significant chars, case-insensitive, `isidstart` first char); `name = expr`; directives `.byte` (also `.text`, same handler) with numbers, `"strings"`, `<expr`, `>expr`; `.word expr,...`; `.res count` (zero-fills, as.s:403-414). Operands `#imm #<e #>e zp abs ,x ,y (zp,x) (zp),y (abs)`; accumulator forms `asl` / `asl a`. Expressions: `$hex %bin dec 'c' label * + -` only (V as.s:769-940): no `*`, no `/`, no shifts, no parentheses. Branch range errors are reported (V as.s:627-660). Predefined names: `sys_exit ... sys_isatty r0 r1 r2 argv argc o_*` (V as.s:10-11); is `SYS_*` callable by name via `jsr sys_write`? U, check as.s:1291-1330.
  - Not supported: `.include`, `.import/.export`, local labels, `.org`, macros, `.bss` (UNVERIFIED by grep of the directive list, as.s:327-345: only byte, word, res, text).

## 1. The language ("B", a C subset)

Types: `int` (16-bit signed), `char` (8-bit unsigned), pointers to either, one-dimensional arrays. Globals and locals. No structs, unions, floats, `long`, `switch`, `do`, `goto`, `typedef`, preprocessor, function pointers, multi-dimensional arrays, initialised arrays other than string literals, `static`, K&R declarations, `++`/`--` (v0.1), `?:`, comma operator, `sizeof` (v0.1). Left out so each costs nothing: the parser has one precedence table and one type tag per symbol.

```ebnf
program   = { global | function } ;
global    = type {"*"} ident [ "[" number "]" ] [ "=" const ] ";" ;
function  = type {"*"} ident "(" [ param { "," param } ] ")" block ;
param     = type {"*"} ident ;
type      = "int" | "char" | "void" ;
block     = "{" { local } { stmt } "}" ;            (* locals first: one pass sizes the frame *)
local     = type {"*"} ident [ "[" number "]" ] ";" ;
stmt      = block | "if" "(" expr ")" stmt [ "else" stmt ]
          | "while" "(" expr ")" stmt
          | "for" "(" [expr] ";" [expr] ";" [expr] ")" stmt
          | "return" [expr] ";" | "break" ";" | "continue" ";" | expr ";" | ";" ;
expr      = assign ;
assign    = lor [ "=" assign ] ;                    (* lvalue checked after parse *)
lor       = land { "||" land } ;   land = bor { "&&" bor } ;
bor       = bxor { "|" bxor } ;    bxor = band { "^" band } ;  band = eq { "&" eq } ;
eq        = rel { ("==" | "!=") rel } ;  rel = shift { ("<" | ">" | "<=" | ">=") shift } ;
shift     = add { ("<<" | ">>") add } ;  add = mul { ("+" | "-") mul } ;
mul       = unary { ("*" | "/" | "%") unary } ;
unary     = ("-" | "!" | "~" | "*" | "&") unary | postfix ;
postfix   = primary { "[" expr "]" | "(" [ expr { "," expr } ] ")" } ;
primary   = ident | number | charlit | string | "(" expr ")" ;
```
Comments `/* */` and `//`. Undeclared names are errors; functions must be defined before use (no prototypes; one pass). Arguments are evaluated left to right. `int` and pointers are 2 bytes; `char` promotes to `int` unsigned on load.

Examples, rising difficulty (each is a test program):
1. `int main(){ return 0; }`
2. `int main(){ puts("hello"); return 0; }` (`puts`, `putchar`, `getchar` come from the runtime)
3. `int x; int main(){ x=3; return x+4; }`
4. `int sq(int a){ return a*a; } int main(){ return sq(7); }`
5. `int main(){ int i; int s; s=0; for(i=1;i<=10;i=i+1) s=s+i; return s; }` (55)
6. `int fact(int n){ if(n<2) return 1; return n*fact(n-1); } int main(){ return fact(5); }` (120)
7. `char buf[16]; int main(){ char *p; p=buf; *p='A'; p[1]=0; puts(buf); return 0; }`
8. `int len(char *s){ int n; n=0; while(s[n]) n=n+1; return n; } int main(){ return len("breadbin"); }` (8)
9. `int main(){ int i; for(i=1;i<=15;i=i+1){ if(i%15==0) puts("fizzbuzz"); else if(i%5==0) puts("buzz"); else if(i%3==0) puts("fizz"); else putnum(i);} return 0; }`
10. Sieve of 100 primes over a `char[100]` array plus a `reverse(char *s)` in-place string reverser, with mutual calls (exercises arrays, pointers, nested loops, `break`).

## 2. Constraints and code generation

- Single pass: recursive descent, one-token lookahead, source streamed via `getc` (V src/lib/input.s:21), never held in memory. Constants are folded only for `number op number`. Forward jumps use generated labels `L<n>`; `as` resolves them in its own two passes, so the compiler needs no backpatching. Output is text assembly written line by line with `fputc` (V as.s imports, line 15).
- Output file size: every emitted line is 10-25 bytes of text, about 8 asm lines per C statement; a 400-line C program is about 3,200 lines, 60 KB of `.s`. That exceeds the 35,840-byte file limit (V roadmap.md:19). Hard budget: sources up to about 150 C lines until S13 or compact output. See Open Q3.
- Zero page proposal (13 bytes, `$23-$2F`): `sp` $23-24 (software stack pointer, grows down), `fp` $25-26, `t0` $27-28 (scratch/pointer), `t1` $29-2A, `t2` $2B-2C, `rt` $2D-2E (runtime temp), `$2F` flags. Value register: A=lo, X=hi (the `r0` pair `$02` also usable as scratch inside the runtime). The 130-byte hardware stack is reserved for `jsr` return addresses (2 bytes per call): max call depth about 60, minus syscalls; the compiler must not push data on it.
- Calling convention proposal ("caller pushes, callee frames"): arguments pushed right-to-left onto the software stack (2 bytes each, `jsr push_ax`, about 14 cycles-bytes: `jsr` 3 bytes); `jsr f`; the caller pops via `jsr pop_n` or `adjsp #n` (3 bytes, 1 call). Callee prologue `jsr enter` plus a 1-byte-immediate frame size (4 bytes): saves `fp`, sets `fp = sp`, subtracts locals. Epilogue `jmp leave` (3 bytes). Return value in A/X. Local or argument access `ldy #off / jsr ldloc` (5 bytes; `lda (fp),y` forms are 2 bytes plus 2 for the high byte). Cost of `f(a,b)` with locals: about 25 bytes of call and 12 bytes of frame code. Max frame 255 bytes (offsets are Y, 1 byte).
- Expression codegen: left operand in A/X, push with `jsr push_ax`, right operand in A/X, then `jsr op_add` etc. (the runtime pops the left into `t0`). Constants and simple loads emit inline (`lda #<5 / ldx #>5`, 4 bytes).
- Runtime (`rt.s`, assembled in with the program once S13 gives `.include`; until then the compiler emits it as a preamble): `push_ax pop enter leave ldloc stloc add sub mul div mod shl shr cmp lt le eq ne neg not puts putchar getchar putnum`. Target: 600-800 bytes of CODE (`mul`/`div` about 120 bytes each). Linked into every program regardless of use, unless the compiler emits only the used ones (see step 9).
- Software stack storage: since S12a the compiler can put the stack and data in a trailing `.res` (BSS, not stored); only run-time sizing needs S12b (`brk`).
- What `as` rejects that the compiler must not emit: expressions with `*` or `/`, parentheses, `.org`, local labels. Labels are `[a-z_][a-z0-9_]{0,14}` and case folds: generated `L123` and user `l123` collide; the compiler prefixes user identifiers with `_` and truncates to 14 chars after the prefix, and errors on collision.
- Branches: 6502 branches reach +/-127 bytes; for conditional jumps emit `bne +3 / jmp L` pairs ("inverted branch over jmp"). V as.s:627-660 reports out-of-range.

## 3. Memory budget for `bc` (U: estimates)

| Item | Bytes |
|---|---|
| Code: lexer 600, expr parser 1,200, statements 700, declarations 600, codegen 800, helpers/io 500 | 4,400 (target <= 5,000) |
| Const data: keyword table, messages, preamble | 800 |
| Fixed BSS: line/token buffers 300, current function state 100, label counters, string pool index | 500 |
| Symbols: 1 entry = name 15 + type 1 + class 1 + value/offset 2 = 19 | |
| Fixed table, N = 220 symbols at 19 bytes | 4,180 |
| Strings literals (kept until the end of the function and emitted at the end of the program) | 1,000 fixed |

Image about 6 KB plus BSS about 6 KB: 12 KB, leaving about 18 KB of the 30 KB for the stack/heap with a fixed table. It overflows at N = 220 if the table is fixed at that size; the same 4 KB table holds about 220 symbols, which is enough for the 150-line programs in 2. With S12 the table starts at 4 pages (about 54 symbols) and grows a page at a time (13 symbols per page); the limit becomes free memory (about 18 KB = 950 symbols) and per-symbol cost stays at 19 bytes. Locals are dropped at the end of each function, so N counts globals + one function's locals, normally under 120. Overflow behaviour must be a clean error ("too many symbols") with the line number, never a hang.

## 4. Work breakdown (12 steps)

Host model first: `tools/bc_ref.py`, a Python reference that implements the same grammar and emits the same `as` source. The emitted text is checked on the host by pattern (golden files); executing it needs a 6502 model (py65 is in the CI image, V commit f04f859) or VICE.

1. Language spec + the 10 examples as `tests/bc/*.c` with expected exit code and stdout. Acceptance: files exist, `make test-host` runs a checker that all parse with the Python reference.
2. Python reference: lexer + parser (no codegen) producing an AST for all 10 programs. Acceptance: host test; rejects 12 malformed inputs with line numbers.
3. Python reference codegen, runtime preamble in `as` syntax. Acceptance: host test that the output uses only the constructs of section 0 (a Python checker that implements the `as` grammar subset); golden output for examples 1-4.
4. Run the golden output on py65 with stubbed `puts/putchar` and the soft stack. Acceptance: examples 1-9 return the expected values (host test).
5. S12: `SYS_BRK` (A/X = new break in pages, returns old/new) in kernel + `include/breadbin.inc` entry + a tiny test program. Acceptance: `tests.test_system` style test grows 4 pages, writes the last byte, reads it back, refuses beyond free pages with an errno, memory is freed at exit (compare `free` before and after).
6. S13: as's symtab, obuf and rbuf on the heap from S12, `.include`. Acceptance: `as` assembles a generated file with 400 labels and 20 KB output; existing as test passes.
7. Assembly `bc` skeleton: arg parsing, source via `getc`, lexer, token tests with a debug `bc -t` dumping tokens. Acceptance: system test on example 9 token count equals the Python lexer.
8. `bc` declarations, symbol table on the heap, expressions, with codegen for constants and globals only. Acceptance: examples 1-3 compile and `as` accepts the output; exit codes correct.
9. `bc` functions, locals, calls, statements (if/while/for/break/continue/return), emitting only used runtime routines. Acceptance: examples 4-6 run under VICE (`xvfb-run -a make test-only T="tests.test_system.Boot.test_bc_6"`).
10. `bc` pointers, arrays, strings. Acceptance: examples 7-8, 10.
11. Diagnostics: file:line errors, limits (symbols, frame 255, labels), the 35,840-byte file warning. Acceptance: 12 negative tests match the Python reference's messages.
12. "hello" end to end on-device and the `make size` entry. Acceptance: `bc hello.c hello.s && as hello.s hello && hello` prints `hello` under VICE; size of `bc` quoted in the commit; full `test-smoke` still passes.

## 5. Open questions for the owner

1. Language: small C subset vs. Forth vs. compiling `basic` (V roadmap.md:276). Recommend C subset as specced; the grammar above is about 30 rules, and the Python reference makes the risk measurable by step 4.
2. Extra zero page: use `$60-$8F` for the compiler's runtime, or hold to 13 bytes (V roadmap.md:154). Recommend 13 bytes for v0 (this spec fits), revisit at step 9 with measurements.
3. File limit: 35,840 bytes caps the generated `.s` (V roadmap.md:19). Recommend compact output (abbreviated runtime calls, no comments, no indentation) and an on-device limit of about 150 C lines for v0; the real fix is a pipe or the REU, not a v0 goal.
4. Runtime: always linked vs. only used routines. Recommend only used (step 9), costing about 150 bytes of compiler code.
5. `char` signedness: unsigned recommended (cheaper: `ldx #0`).
6. Should the compiler emit `as` text or write CX directly (skipping `as`, saving the 2-pass cost and file size)? Recommend text for v0: debuggable and the roadmap says so.
7. brk semantics: grow only (no shrink), per page, and the stack above the break. Recommend grow-only, return carry on failure, free all at exit.
