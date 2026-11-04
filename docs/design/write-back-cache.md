# Write-back block cache and `sync` (shape-of note, R4)

Source: upstream `6d45c40` (feat: write-back block cache, sync; parallel test runner in make test). 13 files, +302 -24. The disk layer change is `src/kernel/blk.s` (+101 lines in that file). Read from the upstream mirror; not ported.

## What the user gets (upstream)

- Writes to the disk are much faster: a block written is kept in memory and written back later, so a command that writes many blocks does not wait for the drive for each one.
- `sync` writes every dirty block back now. Data written by a program is on disk after `sync` (and when the shell exits, as far as upstream guarantees).

## What we have today

- A read cache in REU for the boot drive (the `cache` command, `make CACHE=0|1|2`): repeat reads are fast, and writes go through to the drive (write-through, per `docs/roadmap.md`).
- Writes take the full bus time: about 1 second per 256-byte block on the physical 1541, and the bus stays busy until the write returns.
- No `sync` command.

## The trade-off

- Write-back is fast, but a power cut or reset loses the dirty blocks. Upstream says so in its docs; our REU cache already has the crash-consistency problem for the boot drive, so write-back raises the stakes, not the rule.
- Write-through (today) is safe and slow. Write-back needs `sync` to be usable at all: a user who never runs `sync` loses work.

## Where it would live

- **Kernel (`blk.s`):** the dirty flag per cached block, a flush on `sync`, a flush before a drive change or a mount change, and a flush at shutdown or reset where the hardware allows. This is the 101 added lines in `blk.s`, plus the syscall (`sync`) in `file.s` and `fs.s`.
- **Memory:** the dirty blocks sit in the REU cache, not in kernel RAM, so the kernel room is not spent on buffers. That is why our REU cache is the right home for it.
- **User:** the `sync` command (about 20 lines in `src/bin/sync.s`, a user program).

## Byte estimate (from source lines, not measured)

- Kernel: about 100 lines in `blk.s` and about 20 in `file.s` and `fs.s`, at 4 to 6 bytes a line: **about 0.5 to 0.7 KB**. Against 354 bytes of kernel room, that does not fit without a footprint pass.
- Memory: none in kernel RAM if the dirty blocks stay in REU.
- User: `sync` is about 0.1 KB as a program.

## Smallest version that fits

1. `sync` as a program that asks the kernel to flush, with the cache in write-through mode (nothing dirty, so it does nothing yet): no kernel bytes beyond the syscall.
2. Dirty flags and the flush on `sync`, in the REU cache, behind a switch that defaults to write-through.

## Open questions

- What does a flush on drive change or on reset cost on the physical 1541 (it has no way to refuse a write)?
- Does `sync` need to be a syscall, or can the shell call the cache command?
