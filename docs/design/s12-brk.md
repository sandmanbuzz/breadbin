# S12: growing a process (design and byte cost; no code yet)

Status: proposal by the hygiene/broad-view agent, 2026-11-03. Facts were gathered by a read-only
subagent and spot-checked; byte counts are hand estimates (UNVERIFIED until assembled and run
through `make size`). Whether this starts before the space pass is the owner's call.

## What exists (verified against the source)

- A process owns one contiguous run of pages: `p_mpage`/`p_mlen` (`proc.s`). Layout: image, BSS,
  then argv (`exec.s`, `copy_args`). `pg_used` is one byte per page, bottom first-fit (`mem.s`).
- Programs are relocated at load, so a live process cannot be moved. The only ways to give it more
  memory are to extend its run in place, or to reserve the room at exec.
- `exec` already allocates `image + bss + args` pages and zeroes the BSS from the header's BSS
  size (`exec.s`: `npages` near line 195, `zero_bss` near 321). `as` always writes that header
  field as 0 (`as.s`, near 156-175), so every `.res` in assembled output is stored in the file.
- All 32 syscall slots are used (`NSYS=32`); a new one is a 6-byte entry in the `$CF00` page, which
  has about 29 bytes free (hand count: 4 more calls fit). A module cannot register a syscall.

## Two steps, cheapest first

**S12a. Header BSS (zero kernel bytes).** `as` emits trailing `.res` space as the header's BSS
size instead of file bytes. `exec` already honours it. A compiled program's stack, tables and
buffers stop costing file bytes (the 35,840-byte file limit) and load time; the size is fixed per
program, not per input. This removes most of the pain S13 and S14 would hit, and it is a change
in `as.s` only. Do it first and measure.

**S12b. `brk(n)` (resident kernel code), only if a program must size its memory at run time.**
Extend the caller's run by n pages if the n pages after it are free, else ENOMEM; zero the new
pages (`page_alloc` does not); grow `p_mlen`; move argv (stored at the end of the run) up and
rewrite the pointer at ZP `$20`; n may be negative to give pages back at the top. In-place growth
succeeds only if nothing sits above the process, so for a compiler run from the shell (usually the
topmost process in the pool) it mostly works, and the failure mode (ENOMEM) is clean. It is not a
general `malloc` and is not promised to succeed.

Rejected: moving the process (relocated code); a heap grown from the top of the pool (collides
with module loading, `page_alloc_hi`, and with a second grower); `brk` as a module (a module
cannot register a syscall, and costs at least a pool page).

## Byte cost (estimates)

| Item | Bytes | Where |
|---|---|---|
| S12a | 0 | `as.s` only (a user program, not the kernel) |
| `brk` handler: check next pages free, mark, zero, update `p_mlen` | 45-60 | `CODE`, `mem.s`, next to `pg_used` |
| argv move and `$20` fix | 25-35 | same |
| syscall slot (`jtab`) and `SYS_BRK` constant | 6 | `$CF00` page |
| Total S12b | about 80-100 | against 354 free below `$CF00` |

The 14 bytes above BSS and CODEHI are not touched if the code goes into `CODE`. Pool pages: none.
Hardware stack and zero page: unchanged. `ps` reads `p_mlen`, so it follows. The kernel is not
preemptible, so the scan-and-mark is atomic.

## Test plan (before any kernel merge)

Host: a model of `pg_used` for in-place growth and ENOMEM. VICE: a program that grows, writes,
shrinks and exits (pages returned); a grow with a neighbour above (ENOMEM, nothing changed); grow
then `exec`, argv intact; `make size` before and after in the commit message; the JiffyDOS subset
at the milestone as usual.

## Open for the owner

Whether S12a goes first (recommended: no kernel bytes) and whether S12b waits for the space pass;
whether shrink is in v0 (recommended: yes, same code path).
