# S13: limits of `as` found by the S14 work

Measured with tools/asim.py (py65, the built `as`), so each line below is a behaviour seen on
the host model, not on the machine. The machine's `as` is the same program.

| limit | what `as` does | status |
|---|---|---|
| Input line longer than 127 characters | was: dropped every character past 126 without a word; a long `.byte` line lost its tail and its zero, and the program ran on | **fixed** on fix/as-long-line: lines up to 254 characters are kept whole; a 255th is refused with `as: line N: line too long (over 254 characters)` (tools/test_as.py, AsLongLine) |
| `(zp),y` or `(zp,x)` with a pointer outside zero page | was: accepted (exit 0) and assembled with the low byte only; on the machine it read the wrong bytes | **fixed** on fix/as-zp-names: refused with `as: line N: (zp),y and (zp,x) need a zero page pointer`, checked in pass 2 so forward references count (tools/test_as.py, AsZeroPageAndNames) |
| Symbol names | was: cut at 14 characters, so two distinct 15-character names collided (`duplicate symbol`) | **decided and fixed** on fix/as-zp-names: a name over 14 characters is refused with `name longer than 14 characters` and the line number; not widened (the symbol record holds 15 bytes and widening it is a storage change for S13) |
| Symbol named `a` | `a` is the accumulator operand (`lsr a`), so a symbol or label called `a` is refused; `ab`, `a1` and the like are fine | **fixed** (item 7c): `as: line N: ...` refusal, tools/test_as.py |
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

## The output file: temporary name, unlink, rename

- `as` writes the output under a temporary name in the output's own directory, then renames it over the
  output. The name is `^` plus the first 13 characters of the output's last component (`+` instead of `^`
  when the output's name itself starts with `^`, so the two can never be equal). A c64fs name is at most
  14 characters, so a longer output name is refused (`as: output name is too long`).
- An output whose last component is empty (ends in `/`, or is empty) is refused (`as: output name is empty`), and so
  is one whose last component contains `*`, `?`, `:`, `,` or `=` (`as: output name has a character CBM DOS treats
  specially`): the unlink of the old output sends the name to CBM DOS in a scratch command, where those are
  wildcards or command syntax and would scratch unrelated files. Both refusals happen before any file is touched.
  (Directory parts are not checked: only the leaf goes into the scratch command.)
- Known wording limit: on CBM, scratch of a missing file reports success (files scratched: 0), so on a first
  assembly with no old output the unlink succeeds and a failed rename then says "the old output was removed first"
  although there was none. The file is still named correctly; only that sentence can be wrong on CBM.
- A file already at the temporary name is never overwritten: `as` refuses (`will not overwrite the existing
  file ...; remove it and try again`), and only "no such file" from the probe counts as free.
- A failed write or close removes the temporary and leaves the old output exactly as it was.
- CBM DOS cannot rename onto an existing name (`R0:new=old`; the kernel returns EIO), so after the temporary is
  written and closed `as` unlinks the old output (no such file is ignored), then renames.
- **The window:** if the rename fails after the unlink, the old output is gone and the complete new file exists
  only under the temporary name. The message says so and names it (`the old output was removed first, so the
  complete file is ^name`). If the unlink itself fails the old output is intact and the message names the
  temporary as the complete new file.
- Measured on VICE (x64sc, 1541 as drive 9, `mount 9 /mnt`, CBM DOS module), 2026-11-04: `mv /mnt/ux /mnt/readme`
  onto an existing name answers `mv: /mnt/ux: i/o error` and changes nothing. A name containing `~` cannot be
  created on the CBM path (`echo hi > /mnt/~x` gives `sh: /mnt/?x: i/o error`), which is why the prefix is not
  `~`. Created and read back on a CBM disk: `^x`, `.x`, `#x`, `@x`, `-x`, `+x` (`cat` replies `hi`); `_x` is
  created silently but cannot be read back. The prefix is `^`, and `+` when the leaf starts with `^`.
- The pool is `$0800-$A1FF` (`KSTART` `$A200`) = `$9A00` = 39,424 bytes. `.res` refuses an image plus BSS total of
  exactly 39,424 as well (conservative: the loader gets one byte to spare); the message says "must be under".
