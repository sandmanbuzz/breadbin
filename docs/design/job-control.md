# Job control (shape-of note, R4)

Source: upstream `acec2b5` (Breadbin 0.3: own IEC driver, GeoRAM `/tmp`, job control, software clock, kernel fixes) and `64d5f31` (jobs are process groups; fg and bg act on whole pipelines). Read from the upstream mirror; not ported. MIT upstream, so a port is allowed with credit, but this note is a shape-of: our kernel differs.

## What the user gets (upstream)

- CTRL-Z stops the foreground job. `jobs` lists the background and stopped jobs. `fg` and `bg` continue a job (by number or by default the last one).
- A pipeline is one job: `fg` and `bg` act on all of its stages (process groups, `64d5f31`).

## What we have today

- `cmd &` runs a background job; `jobs`, `kill`, `bg` and `fg` exist in `src/bin/sh.s` (the shell tracks children by pid; `jobs` reads the process table).
- Kernel signals: `SIGINT`, `SIGKILL`, `SIGPIPE`, `SIGTERM` (`include/breadbin.inc`), `SYS_KILL`. No stop signal, no continue, no process groups.
- CTRL-C reaches the foreground job (tested: Boot tests 13 and 14).

So the missing pieces are the stop state, CTRL-Z, continue, and groups.

## Where it would live

- **Kernel:** a stopped state in the process table, a stop signal raised by the console on CTRL-Z (the console already has an interrupt path for CTRL-C), a continue, and a group id so that a pipeline stops and continues as one. This is where upstream's bytes are: `proc.s` +259 lines and `con.s` +14 lines in `acec2b5`, +3 in `proc.s` for the groups in `64d5f31`.
- **Shell:** the stop-and-report of jobs and the fg/bg built-ins. Upstream adds about 50 job-related lines to `sh.s`.

## Byte estimate (from source lines, not measured)

- Kernel: about 280 source lines in `proc.s` and `con.s`, at 4 to 6 bytes a line: **about 1.1 to 1.7 KB**. Against 354 bytes of kernel room, this does not fit without a footprint pass (CP2, CP5).
- Shell: about 50 lines: **about 0.2 to 0.3 KB** of pool.
- The stop state adds one byte per process-table entry. The groups add one more. At our pool sizes, that is small.

## Smallest version that fits

1. Shell only: `cmd &` jobs keep working; CTRL-Z is not offered. No kernel bytes.
2. A stop flag per process and a SIGSTOP that the console sends on CTRL-Z, with `fg` and `bg` in the shell: the kernel part is roughly the size of the signal path, about 0.3 to 0.5 KB. Still needs room.

## Open questions

- Does CTRL-Z stop the whole pipeline, or the stage that has the console? (Upstream: the whole pipeline, which needs groups.)
- Which of the four existing signals already has a stop-like path we can reuse?
