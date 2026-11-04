# Shell `$?`, `&&`, `||` and `2>` (shape-of note, R4)

Source: upstream `b64fd2d` (feat: shell `$?` `&&` `||` `2>` history, RESTORE kills, fsck). 13 files, +1532 -31; the shell part is `src/bin/sh.s` +425 lines. Read from the upstream mirror; not ported (MIT, so porting is allowed with credit, but the kernel part differs).

## What the user gets (upstream)

- `$?` holds the exit status of the last command; `echo $?` prints it.
- `a && b` runs `b` only if `a` succeeded; `a || b` runs `b` only if `a` failed.
- `cmd 2> file` sends the error output to a file (and `2>&1` joins it to standard output).
- RESTORE (the key) kills the running program (in `b64fd2d`, bundled with the rest).

## What we have today

- `;` sequences, `|` pipelines, `<`, `>`, `>>`, `&` background jobs, quoting, wildcards (`src/bin/sh.s`).
- Exit status is not kept: the shell does not record `$?`, and there is no `&&`, `||` or `2>` (checked on main: none of those strings appear in `sh.s`).
- Error messages go to the standard error channel of the program, which the shell does not redirect.

## Where it would live

- **Shell (user pool):** `$?`, the `&&` and `||` operators in the tokenizer and the sequencing loop, `2>` and `2>&1` in the redirection code. This is most of upstream's `sh.s` change (+425 lines, about 40 of them for the operators, the rest mostly for the history and completion that come with that commit).
- **Kernel:** the program's exit status must reach the shell. Check whether `SYS_WAIT` already returns it (our kernel: `SYS_WAIT` is in `include/breadbin.inc`; the status path needs a look before anything is designed). Upstream's kernel part in this commit is about 100 lines across `cbm.s`, `exec.s`, `main.s` and `proc.s`, which is about 0.4 to 0.6 KB at 4 to 6 bytes a line.
- **Stderr redirection:** a per-process error descriptor (upstream's `2>` needs the kernel to know which descriptor is standard error). This is the part that costs kernel bytes.

## Byte estimate (from source lines, not measured)

- Shell: about 40 lines for the operators and `$?`, at 4 to 6 bytes a line: **about 0.2 to 0.25 KB** of pool; `2>` adds about the same.
- Kernel: about 0.4 to 0.6 KB, which does not fit the 354 bytes of room below `$CF00`.

## Smallest version that fits

1. `$?` and `&&` / `||` in the shell only, using whatever status `SYS_WAIT` already returns. No kernel bytes if the status is there; check first.
2. `2>` is the only piece that needs the kernel. Defer it until a footprint pass has freed room.

## Open questions

- Does `SYS_WAIT` return the child's exit code today? (Check before designing.)
- RESTORE: is it a kernel key or a shell key? Upstream does it in the kernel (`b64fd2d`), which is outside this note.
