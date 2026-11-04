# S13: limits of `as` found by the S14 work

Measured with tools/asim.py (py65, the built `as`), so each line below is a behaviour seen on
the host model, not on the machine. The machine's `as` is the same program.

| limit | what `as` does | status |
|---|---|---|
| Input line longer than 127 characters | was: dropped every character past 126 without a word; a long `.byte` line lost its tail and its zero, and the program ran on | **fixed** on fix/as-long-line: lines up to 254 characters are kept whole; a 255th is refused with `as: line N: line too long (over 254 characters)` (tools/test_as.py, AsLongLine) |
| `(zp),y` with a pointer outside zero page | accepted (exit 0) and assembled with a non-zero-page pointer, which the 6502 cannot address that way: on the machine it read the wrong bytes | **open**: `as` should refuse it. Found on the machine by the S14 `puts` (cc_ptr had been in the data area); S14 now uses `cc_ptr = $2b` |
| Symbol names | cut at 14 characters: two distinct 15-character names collide and report `duplicate symbol` | **open** (loud, but the message is misleading): the cut is a limit to state, or `as` should refuse names over 14 with the line number |
| Symbol table | 220 entries, 35 of them builtins (NSYM) | recorded: S14 checks the count for its programs (185 left) |
| Output | 8 KB (`OBMAX`) | recorded; S12a (tools/as-bss) moves trailing `.res` out of the stored image |

## Open decisions for the owner

- **A comment (or any line) past 254 characters now fails the assembly.** Before, the tail was dropped
  silently, which did no harm to a comment. Now a long comment is a refused line. Choices: keep
  the refusal for every line (as now); or refuse only when the overflow is in code, so that a comment
  past 254 is cut without a word. The second needs quote and comment state in readline.
- **CRLF lines:** the CR is skipped, so a CRLF file has the same limit as an LF one.
