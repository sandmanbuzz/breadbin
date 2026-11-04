# S13: limits of `as` found by the S14 work

Measured with tools/asim.py (py65, the built `as`), so each line below is a behaviour seen on
the host model, not on the machine. The machine's `as` is the same program.

| limit | what `as` does | status |
|---|---|---|
| Input line longer than 127 characters | was: dropped every character past 126 without a word; a long `.byte` line lost its tail and its zero, and the program ran on | **fixed** on fix/as-long-line: lines up to 254 characters are kept whole; a 255th is refused with `as: line N: line too long (over 254 characters)` (tools/test_as.py, AsLongLine) |
| `(zp),y` or `(zp,x)` with a pointer outside zero page | was: accepted (exit 0) and assembled with the low byte only; on the machine it read the wrong bytes | **fixed** on fix/as-zp-names: refused with `as: line N: (zp),y and (zp,x) need a zero page pointer`, checked in pass 2 so forward references count (tools/test_as.py, AsZeroPageAndNames) |
| Symbol names | was: cut at 14 characters, so two distinct 15-character names collided (`duplicate symbol`) | **decided and fixed** on fix/as-zp-names: a name over 14 characters is refused with `name longer than 14 characters` and the line number; not widened (the symbol record holds 15 bytes and widening it is a storage change for S13) |
| Symbol table | 220 entries, 35 of them builtins (NSYM) | recorded: S14 checks the count for its programs (185 left) |
| Output | 8 KB (`OBMAX`) | recorded; S12a (tools/as-bss) moves trailing `.res` out of the stored image |

## Open decisions for the owner

- **A comment (or any line) past 254 characters now fails the assembly.** Before, the tail was dropped
  silently, which did no harm to a comment. Now a long comment is a refused line. Choices: keep
  the refusal for every line (as now); or refuse only when the overflow is in code, so that a comment
  past 254 is cut without a word. The second needs quote and comment state in readline.
- **CRLF lines:** the CR is skipped, so a CRLF file has the same limit as an LF one.

## Known limits of the zero-page check (R2)

- `(zp),y` and `(zp,x)` accept a plain constant below 256 (`$2b`) and refuse a label, `*`, and any
  `<` or `>` operator. A constant written with `<` or `>` is refused too; write the constant.
- An expression that overflows 16 bits wraps before the check sees it: `ptr = $ff00 + $100` is
  `$0000` and is accepted as zero page. Arithmetic overflow is not reported anywhere in `as`; that
  is a separate limit to record, not a zero-page bug.
