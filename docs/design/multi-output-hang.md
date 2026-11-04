# Finding: programs with three or more output files hang (2026-11-03)

Status: finding for the kernel owner (B takes kernel fixes). No kernel change made here.

## Observed (VICE 3.10, stock ROMs, container runner, `tests.test_system.Pipes`)

| case | files | pipe | result |
|---|---|---|---|
| `echo two \| tee f1 f2` | 2 | yes | OK |
| `echo three \| tee f1 f2 f3` | 3 | yes | **hang at the prompt** (harness timeout) |
| `echo four \| tee f1 f2 f3 f4` | 4 | yes | **hang at the prompt** |
| `fanout f1 f2 f3` (test program: open, write "x", close each; no pipe) | 3 | no | no hang, but `cat f3` is empty |
| `fanout f1 f2 f3 f4 f5` | 5 | no | **hang at the prompt** |

`fanout` is a 40-line test program, not landed. It was used to take the pipe out of the picture.

## What it says

- A hang with **no pipe** (fanout, five files) means the hang is in the kernel path that opens several files for write, or in the fd/open-file table, not in `tee`'s pipe logic.
- `tee` with three files hangs with a pipe; `fanout` with three does not. So there may also be a second, tee-side effect, with the pipe being read while several outputs are open.
- The empty `f3` from `fanout` (three files, no hang) is not explained yet. It could be the same defect as a silent write failure.

## Not done

- No kernel change. The owner or B takes the kernel fix.
- Not checked: the open-file slot limit per process (SYS_OPEN's answer on the fourth or fifth open), whether the write to the third file returns an error, and the shell's own fd use.

## Suggested next look (for the kernel owner)

1. Print the error from `SYS_OPEN` and `SYS_WRITE` for the third and fifth file in `fanout` (currently the error is not checked).
2. Count the fds a process holds at exit: does `SYS_EXIT` release all of them?
3. Check the file table size against the number of simultaneous `O_WRONLY|O_CREAT|O_TRUNC` opens.
