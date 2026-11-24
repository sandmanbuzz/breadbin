# Glyph survey: what a C64 keyboard types, what the console shows

Status: survey done 2026-11-24 by `tools/glyph_survey.py` (re-run it after any font or keytab change). Read-only; it changes nothing.

## Method

- **Frequency:** characters counted over the repo's own text (`src/`, `tools/`, `docs/`, `tests/`, `include/`). That is a proxy for what a user meets in files. Markdown code fences inflate the backtick.
- **Keyboard:** `src/kernel/keytab.inc` (the standard layout, checked against a ROM by `tools/check_keytab.py`; not changed here) through `kbd.s`'s PETSCII and `con.s`'s `to_ascii`, which is the path a typed key takes into the shell.
- **Console:** the 40-column `to_screen` (`con.s`) and the 80-column `sc80` (`con80.inc`) plus `src/mod/con80.font`.

## Findings

**Keyboard reach.** Every common printable character has a key with at most one modifier, except four:

| char | uses | keyboard | 40-col | 80-col |
|---|---|---|---|---|
| `` ` `` | 22,636 | none | nothing | nothing |
| `}` | 9,713 | none | `?` | glyph `$67` |
| `{` | 3,007 | none | `?` | glyph `$65` |
| `~` | 1,011 | none | `?` | glyph `$68` |

The C64 keyboard has no key that produces any of these (the nearest keys give PETSCII graphics, which `to_ascii` drops). So they can be displayed but not typed. Typing them needs a layout decision (a chord handled in the shell or editor, not a change to `keytab.inc`), which is the owner's call.

**Output.** Every other printable character prints a glyph of its own on both consoles, with these exceptions:

- **`@` was blank on the 80-column console.** Screen code `$00` was all zero. Fixed in this survey's commit: the glyph is now drawn (`docs/design/glyph-survey.md` is the record; the font change is in `src/mod/con80.font`). The simulator test checks it.
- **Backtick** has no glyph on either console. The 80-column font has no free slot, and adding one costs about 9 bytes (a range check and a glyph). The module is at 1,789 B of 1,792 B for 7 pages, so it would need an eighth page. Decision for the owner: take the page, or find 6 bytes of driver code first.
- **`{ } ~`** print glyphs on the 80-column console and `?` on the 40-column one. The 40-column console is the stock character set and has no braces; changing that is a kernel change, not made here.
- **`|`** is the screen code `$5D` on the 40-column console and `$66` on the 80-column one (the bar glyph). The two bar shapes are identical; the console shows a bar on both.

**Duplicate shapes (by design).** `[`, `\` and `]` exist at both the stock codes (`$1B`, `$1C`, `$1D`) and the ASCII-position codes (`$5B`, `$5C`), and the bar at `$5D` and `$66`. The VICE test decodes text by matching shapes, so a duplicate is ambiguous there. None of the tested paths types these characters, so no test fails on it.

**PETSCII graphics.** The keyboard's shifted letters give PETSCII graphics (`$A0-$DF`, `$C0`, `$DB`). `to_ascii` drops them, so they never reach the console. Nothing to show.

## What is not done

- A glyph for the backtick (needs the page decision above).
- Typing `{ } ~` and the backtick from the keyboard (needs a layout decision).
- Eyes-on check of the new `@`, `{ } ~ |` shapes on a CRT (hand-drawn; the owner's eyes).
