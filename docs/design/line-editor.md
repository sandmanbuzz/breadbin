# Line editor with history (shape-of note, CP7)

Status: design only. No code. Checkpoint 7 ("kernel line editor with history") in `docs/design/next/checkpoints.md`. Upstream's version is read, not ported; a port would be blind without these numbers.

## What the user gets (upstream, read from source)

- **Keys:** DEL erases the last character; CTRL-D on an empty line is end of file; RETURN ends the line; anything else printable is added (up to the line limit).
- **History:** UP and DOWN recall the last eight lines (`HIST`, one 64-byte slot each, `HLEN`). The recalled line is editable like a typed one.
- **TAB (CTRL-I):** completes the word before the cursor as a glob (`word*`, in `/bin` for a command name, at the start or after `|`, `;` or `&`). The part all matches share is typed; then `/` after a directory or a space after a file. With nothing to add, the matches are listed and the line shown again.
- **Script input and pipes** do not use the editor (their buffer shares the history memory; `ibuf = hbuf`).

Our shell has none of this. It reads each line with `SYS_READ` and leaves editing to the console (`src/bin/sh.s`, `getline`). `SYS_CONMODE` (raw mode) is already in our contract.

## Where it could live

| placement | what it owns | cost against the room | notes |
|---|---|---|---|
| **shell** (`sh.s`, user pool) | raw keys, history, TAB, the glob call | pool pages, not kernel bytes | upstream's shell takes 20 pages; ours is 3682 bytes and about 18 pages resident at an idle prompt. Every kernel-free byte here comes out of the same pool as the programs. |
| **kernel console** (`con.s`, CP7 as written) | the same, plus a shared history for `edit` and `more` | kernel bytes | the room is 354 bytes below `$CF00` and 14 above BSS and CODEHI. The estimate below does not fit. It needs a footprint pass first (CP2, CP5) or it moves code out. |

Recommendation: shell placement first. It answers the user's need now, costs pool pages (which CP2 measures), and leaves the kernel room alone. The kernel version is worth it only if `edit` and `more` must share the history (the CP7 screen save/restore reason); decide that with CP7's other items, not on this note.

## Byte estimate (from source, not measured)

- Routines in upstream's `sh.s` for the editor: `readline` 65 lines, `complete` 159, `addch` 12, `hist_add` 21, `hslot` 17, `recall` 24: 298 source lines (comments included). At roughly 60 percent instructions and about 2.6 bytes each, that is **about 0.5 KB of code**.
- History: `HIST * HLEN` = 8 x 64 = **512 bytes** of BSS (2 pool pages with the rest of the shell).
- Total: **about 1 KB**, which is about three times the 354 bytes of kernel room. A kernel placement cannot land without freeing room first.
- Measure before any port: build the prototype in the shell, then `make size` for the kernel (should be unchanged in the shell placement) and the shell's page count at an idle prompt (the `ps` and `free` figures).

For scale, the three cheap ports landed on 2026-11-03: `tee` 909 bytes, `tail` 1473, `sort` 1182 (`docs/design/upstream-survey.md`).

## What to measure first

1. A prototype `getline` with raw keys and DEL only, in the shell: the code size and the idle-prompt pages.
2. Add history (8 slots). Measure again. The 512 bytes is the largest single number.
3. Add TAB by reusing the shell's `glob`. Upstream's `complete` is 159 lines; check how much of it our `glob` already does.
4. Only then decide whether CP7 needs the kernel placement.

## Open questions

- Does `edit` need the history, or only the raw keys? (`edit` does its own keys today.)
- The 40-column screen: upstream's TAB listing can scroll the line off the screen; what does CP7's screen save/restore need to keep?
