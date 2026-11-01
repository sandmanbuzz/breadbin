# Kernel modules v1: the interface (short note)

Status: agreed between the kernel session (loader side: `exec.s`, `mem.s`, `blk.s` cache ops) and f7 (build side: `tools/kexports.py`, `src/mod/`, `mk/modules.mk`). Background and alternatives: `docs/design/research/next/C-modules-drivers.md` (loader section). A module is an ordinary CX file linked against the kernel's absolute addresses; the loader is the existing relocator.

## What a module is

- A CX v1 file (same container, `tools/cx.py`) installed as `/lib/km/<name>` on the root disk. It is linked twice (origin `$0000`, `$0100`) exactly like a program, so the module's own high bytes are relocated by the load page and **kernel addresses are not** (identical in both links).
- Kernel symbols come from `build/kexp.s` (generated, `.export name := $ADDR`, `.exportzp` for zero page) and `build/kexp.inc` (the matching `.import`/`.importzp` lines to include). Resident cost: 0 bytes. The set of exported names is the whitelist `src/mod/kapi.txt` (one symbol per line, `#` comments). Adding a name is a deliberate, reviewed act: it is the module ABI.
- No `ZEROPAGE` segment. A module uses the kernel's zero page (`r0-r3`, `tmp0-3`, `p1-p4`, ...) by import, only inside a call, and keeps no state there.
- Image layout, fixed offsets (the `HEADER` segment, first in the image):

| Offset | Size | Content |
|---|---|---|
| 0 | 3 | `jmp init` |
| 3 | 3 | `jmp fini` |
| 6 | 2 | kernel API hash (little endian) |
| 8 | 1 | class byte (0 test/generic, 1 filesystem, 2 char device, 3 block driver, 4 IRQ hook; only 0 is used by v1) |

## Calls

- `init` (`jsr base+0`): called by the loader after relocation, BSS zeroed, hash checked. Registers whatever it provides (vectors, a class row) and returns carry clear, or carry set with A = errno (the loader frees the pages). 
- `fini` (`jsr base+3`): undo `init`. Carry clear = unloaded; carry set + `EBUSY` = refuse (something is open). The loader frees the pages only on carry clear.
- Both run as kernel code: on the caller's stack (STKSAVE leaves 130 bytes: use under 24), `in_kernel` set, no sleeping, no calls that can block. They may call anything on the whitelist.
- Module memory (image + BSS) is pool pages loaded top-down and never moves. Once `init` returns, the module's state stays at fixed addresses until `fini`.

## The hash

CRC-16 (CCITT, init `$FFFF`) over the lines `name=ADDR\n` for every whitelisted symbol in whitelist order, ADDR as 4 upper-case hex digits. `tools/kexports.py` computes it from `build/kernel.lbl`. The kernel carries it as one RODATA word in `build/khash.inc` (`kapi_hash: .word $XXXX`, 2 bytes resident); every module carries it at offset 6; the loader compares and fails with `ENOEXEC` on mismatch. Because the hash depends on the final link, the kernel is linked twice (the first time with a placeholder word; the word does not change any address, which `kexports.py --check` verifies by comparing the whitelisted addresses of both links).

Build rules enforced by `kexports.py` (hard errors): a whitelist name missing from `kernel.lbl`; a name inside `[__INIT_RUN__, +__INIT_SIZE__)` (released after boot); a duplicate; a name that is not a plain label (the `__...__` linker symbols).

## Kernel side (Agent 3)

`kapi_hash` is read from the kernel, the module from `base+6`; `cx_load` (split out of `spawn_common`) with `argsz = 0`; `mod_load`/`mod_unload`/list on cache ops 4-6; four table entries `{base page, npages, class}`. None of that is in this note's scope, only the contract above.

### What landed (2026-11-01, main)

- `exec.s`: `cx_load` (path in r0, `argsz` preset, `ld_hi` picks the allocator) is split out of `spawn_common`; `mod_load`, `mod_unload`, `mod_list` with a 4-slot table (`mod_base/np/cls`). Root only (load, unload). The lowest free slot is used. `init` runs on the caller's stack with `in_kernel` set.
- `mem.s`: `page_alloc_hi` (first fit from the top of the pool).
- `blk.s`: `SYS_CACHE` ops 4 (load, r0 = path -> A = slot), 5 (unload slot X), 6 (list into r0, 12 bytes: base page, pages, class per slot). Command: `mod [ls | load PATH | unload SLOT]`.
- Proven: `tests.test_system.Modules` (load at the top of the pool, unload runs fini, a non-CX file and a missing file are refused) and the whole suite.
- Cost: loader about 320 bytes resident; `KSTART` went $9700 -> $9600 (one page of TPA on loan until `cbm.km` takes about 1.2 KB out).

## First module and test

`src/mod/hello.s`: `init` prints `hello from module` with `con_puts_ax`, `fini` prints `bye`. Proves: link against `kexp`, relocation, hash, load top-down, unload, `free` shows pages back. VICE test (kernel side): `cache load hello`, screen shows the greeting, `free` drops by the module's pages; `cache unload hello`, pages return. Host test `tools/test_kexports.py`: unresolved name, INIT name, duplicate, ZP vs absolute export forms, stable hash, `--check` fails when an address moves.

## Later (not v1)

CX v2 modules (trailer, delta relocs), per-class registration tables (C1/C2 in lens C), `cbm.km` (first real module), `uci.km`, versioned hash per class, signed modules (not needed while kernel and modules ship on one image).
