# Lens C: kernel modules, loadable drivers, device/filesystem model

Source read: the footprint worktree (`.claude/worktrees/reu-cache`, branch `footprint`) **including its uncommitted changes** (cbm.s in `CODEHI`, `KSTART=$A100`, the new `jsr enter` syscall page, `SYS_CACHE`=31). The tree is moving; line numbers are from that state. Sizes come from `make size` on a copy built in the scratchpad (VERIFIED, 2026-10-31).

## 1. Executive summary

1. **Modules can be CX files today, and the format does not need to change.** Link a module against the kernel's *absolute* addresses (generated from `build/kernel.lbl`). cx.py's two-origin diff relocates only the module's own high bytes, so kernel references pass through untouched. That costs **0 resident bytes for an export table**, and the build id check covers mismatches.
2. **The loader is ~120 bytes**: split `spawn_common` into `cx_load` plus a `mod_load` and add a top-down `page_alloc_hi`. Modules live at the **top of the user pool** (processes take pages from the bottom) and are counted in `free_pages`.
3. **First module: a 30-byte test char device, then `cbm` (~1,400 bytes out of resident).** Do not start with UCI: it does not exist yet and VICE cannot test it. cbm is already isolated in its own segment and has a VICE test (`tests/test_system.py:418`).
4. **Ops tables are about size-neutral by themselves (±40 bytes).** Do not sell them as shrinkage. Their value is that the third backend (UCI) adds **0 core bytes** instead of ~120 bytes of new branches plus a second copy of open/create (cbm needed 170).
5. There are three seams: **fs-class vectors** (12 ops), **open-file classes** that are the device majors (read/write/close), and **block-driver vectors** (read/write). That last one is the hook for fast1541 drive-code upload.
6. **UCI DOS is a filesystem driver, not a block device.** The UCI core (command push, response) is a small transport module that the fs driver, rtc and net share. Software IEC (target `$05`): skip it, since UCI DOS covers it.
7. **Keep c64fs on the boot image as root on every tier.** Mount UCI at `/u` from init when the probe succeeds. A root pivot later is a one-variable change (`namei` hard-codes dev 0, `src/kernel/fs.s:1073-1076`).
8. **Stays monolithic:** IRQ/scheduler/syscall entry, mem, file table and pipes, console+kbd, c64fs+blk+standard iec (they read the modules in), the CX loader, mount/umount.
9. **Net after stage 3:** about 1.2 KB leaves resident, which lets KRAM code move into the freed CODEHI, so `KSTART` rises by ~4-5 pages on boots that never mount a CBM disk. UCI, fast1541 and the REU cache join as modules at zero resident cost.
10. **Contract breaks:** `dev_type` becomes an ops offset, `SYS_CACHE` becomes `SYS_KCTL` (cache plus modules), `mount` takes a type, and `/dev` majors become file classes. `SYS_DISKIO` can become `/dev/diskN`.

## 2. Current-state findings

| Fact | Cite | Status |
|---|---|---|
| Resident code: KRAM 10,919 code + 590 rodata; CODEHI 1,902 (cbm); INIT 1,140 (released); BSS 6,101. Room: 267 bytes below `$CF00`, 183 below `$FFFA` | `make size` | VERIFIED (ran) |
| Pool is `$0800-$A0FF` (153 pages); `KSTART=$A100` | `src/kernel/k.inc:4`, `src/kernel.cfg` KRAM | VERIFIED |
| `dev_type` behavioural branches: **11** (file.s 232, 262, 456, 832, 959, 1036, 1331; fs.s 224, 255, 879; exec.s 107). Plus dev_type writes in cbm.s 759, 778, 955, a read at 985, and blk.s 653 | grep | VERIFIED |
| `f_type` chains: sys_read 5 compares (file.s:434-446), sys_write 5 (file.s:579-590), oft_unref 3 (file.s:101-110), umount busy check 3 (cbm.s:928-933) | read | VERIFIED |
| Block driver branch: `rq_dev cmp #1` (REU vs IEC) in bread and bwrite (blk.s:212-214, 281-283); the cache tests dev 0 (blk.s:677, 793, 262) | read | VERIFIED |
| cbm.s splits into the CBM filesystem proper `dir_entry..cbm_fsinfo` = $F7D5-$FC99 = **1,220 bytes**, and generic mount/diskio/umount/mntinfo $FC99-$FF42 = **681 bytes**. Plus `cbm_open`/`cbm_create` living in file.s, $B1AA-$B254 = **170 bytes** | kernel.lbl | VERIFIED (arithmetic from labels) |
| CX: header `"CX",1,img,bss,nrel`, page-aligned load, relocation = add base page to listed high bytes; image entry at offset 0 | `tools/cx.py:1-35`, `src/kernel/exec.s:139-151, 226-279, 540-544` | VERIFIED |
| Loader pieces: `spawn_common` namei → load = $AB79-$ACA0 (295 B); `relocate` 119 B; programs only run from c64fs | exec.s:88-215, 106-111 | VERIFIED |
| `page_alloc` is first-fit from the bottom, with no top-down variant | `src/kernel/mem.s:32-74` | VERIFIED |
| Syscall page: NSYS=32, all used (index 31 = sys_cache) | `src/kernel/jtab.s:9-11, 76-87` | VERIFIED (working tree) |
| IRQ is a fixed sequence: kbd_scan, ticks, con_cursor_tick, wakeups, sleepers, SIGINT, slice. NMI is a bare `rti` | `src/kernel/proc.s:231-290`, `src/kernel/main.s:208-209` | VERIFIED |
| Device files: inode `I_MAJOR` 0=null, 1=console, mapped by hand in open | file.s:303-310, `docs/filesystem.md:87` | VERIFIED |
| Per-device state is struct-of-arrays over NDEV=5 (`dev_present`, `dev_type`, `dev_drive`, `sb_*` x8, cbm `w_busy`) | blk.s:56-59, fs.s:18-25, cbm.s:30 | VERIFIED |
| Root is always dev 0, ino 1 | fs.s:1073-1076 | VERIFIED |
| No UCI code exists on any branch | `git log --all`, `ls src` | VERIFIED |

## 3. Proposals

### First-class: loadable modules through the existing CX relocator (the peer's question)

**Can a module be a CX file loaded by a kernel-mode variant of the spawn relocator?** Yes, with no format change.

- **Linking against the kernel.** A new `tools/kexports.py` reads `build/kernel.lbl` and writes `build/kexp.s` (`.export iget := $BA95`, and so on) for a whitelist file `src/kernel/kapi.txt`. The module links with `kexp.o` at origins $0000 and $0100 as programs do. Kernel addresses are identical in both links, so cx.py records only the module's own high bytes (`tools/cx.py:19-28`). Resident cost: **0 bytes**. An index-based export jump table would cost 3 bytes per function and still cannot export *data* (`ci`, `fs_name`, `nm_dev`, `bp`, `f_pos*`, which fs code uses constantly). Rejected.
- **Guarding the absolute link.** kexports.py emits a 16-bit hash of the exported addresses into both the kernel (one RODATA word) and the module header. A mismatch gives ENOEXEC. Every module ships on the same image as its kernel, so a mismatch only happens when disks are mixed.
- **Rules kexports.py must enforce:** no export may point into `INIT` (released at boot, `src/kernel.cfg` INIT segment). The module's cfg has no ZEROPAGE segment, because `prog.cfg`'s `$23-$2F` is per-process ZP and a module uses kernel ZP (`$40-$8F`, r0-r3, tmp*) through imports.
- **Module image convention, inside an unchanged CX:** offset 0 `jmp init`, 3 `jmp fini`, 6 the kernel hash (2 bytes), 8 a class/name byte. `init` registers vectors and returns carry. `fini` restores them; it may refuse with EBUSY.

**Minimum change to exec.s** (UNVERIFIED estimate, no build):

1. Move `jsr measure_args` (exec.s:157) to the top of `spawn_common`. It only reads r1.
2. Extract exec.s:99-210 (namei → iget → header → size → `page_alloc` → `fs_read` image → `relocate`) into `cx_load: pp=path, argsz preset → base, npages, carry`. Spawn calls it, then `zero_bss/copy_args/setup_proc`. About +4 bytes (jsr/rts).
3. `cx_load` picks the allocator by a flag byte: `page_alloc` for processes, new `page_alloc_hi` (scans `pg_used` from the top) for modules. About 30 bytes in mem.s.
4. `mod_load: argsz=0 → cx_load → zero_bss → check hash at base:06 → jsr base:00 → record (base, npages, class)`. About 55 bytes.
5. `mod_unload: jsr base:03 → page_free`. About 25 bytes. Module table: 4 entries x 3 = 12 bytes BSS.

Total ≈ **120 code + 12 BSS**. Spawn is unchanged for programs.

**Where modules live:** pool pages, top-down. They are counted in `free_pages`, and `meminfo` gains a "module pages" byte. The KHI island has 183 bytes left, so it is not an option. Modules cannot execute from the REU; it can stash an unloaded module for a fast reload later (stretch). Risk: no memory protection, and a module sits next to the highest user pages. That is today's risk for KRAM too, but now inside the pool.

**How a module is loaded:** automatically by `sys_mount` (probe says CBM → `mod_load("/lib/km/cbm")`, kept loaded while referenced), and explicitly through `SYS_KCTL` (below) for `mod load|unload|ls`. Loads always come from the c64fs root, so the bootstrap is fixed: blk + iec standard + c64fs + exec stay resident.

**Smallest first module:** `devzero.km`, ~30 bytes. It registers file class 2 (`/dev/zero`): read fills r0 with zeros, write discards. It proves link, relocation, hash, register and unload in VICE in a day, with no risk to storage. **The real guinea pig is `cbm.km`, not UCI.** cbm is already segment-isolated (`CODEHI`, cbm.s diff), Classic-tier and CI-testable (`tests/test_system.py:418` test_cbm_disk), and it pays ~1.4 KB. UCI comes third and is born as a module, so it never touches resident space.

### LOW

**[C1] Open-file classes = device majors** | all tiers | `f_type` indexes a class table of {read, write, close} vectors. `I_MAJOR` maps straight to a class (`FT_CHR0+major`), so a new char device is just a module filling one row | cost: table 8 classes x 6 = 48 bytes DATA + 14-byte dispatcher, replacing ~80 bytes of chains (file.s:101-110, 434-446, 579-590): about **-20 bytes** (UNVERIFIED) | break: f_type numbering is internal, but `stat`'s major semantics are documented in `docs/filesystem.md:87` | depends: none | risk: low; the console's "always writable" special case (file.s:575-578) becomes a class flag | test: test-smoke plus test_console and the pipe tests.

**[C2] Filesystem ops vector, `dev_type` becomes an offset** | all | `fsv: NFS(3) x 12 ops x 2` (72 B, c64fs row initialised in DATA). `dev_type,x` holds `class*24`, so the dispatch is `tya; adc dev_type,x; tay; lda fsv+1,y; pha; lda fsv,y; pha; rts` (~14 B). Ops: `lookup, iget, iput, open, create, read, readdir, write, close, unlink, rename, statfs` plus a flags byte (can mkdir, can exec). Convention: **X = dev**, the arguments in the existing globals (`nm_dev/nm_ino`, `ci`, `fs_name`, `fs_name2`, `sb6` = open-file entry, r0/r1), return carry/A as today. These are the conventions cbm.s already uses, so the adapters are small. Each of the 11 sites drops from 11 to 8 bytes: -33, +14 dispatcher, +24 c64 row = **≈ +5 bytes** (UNVERIFIED). `not_cbm` (file.s:829-838) becomes the flag test | break: `mntinfo` returns a type byte (cbm.s:985), which must now be an fs id. Fix `mount` (`src/bin/mount.s`) to match | depends: none | risk: the c64fs paths fall through inline today, and moving them behind vectors touches `fs.s`, file.s and exec.s together. Do it per op, smoke test each | test: test-smoke, the Drives tests, Persistence, REU.

**[C3] Exec through the read op** | all | spawn reads the image through `fs op read` on a temporary open-file entry instead of `fs_read` with `f_off` (exec.s:122-134, 189-201, 248). This deletes the ENOEXEC guard (exec.s:106-111) and gives **run-from-CBM and run-from-UCI** (S11c and S11 ask for it) | cost: about +20 bytes | depends: C2 | test: run a CX from a CBM disk in VICE.

### MEDIUM

**[C4] The module loader** (above) | all | ~132 bytes | break: none for programs | depends: none (C1 for the devzero proof) | risk: the kexports discipline; INIT exports | test: devzero load/unload under VICE, `free` before and after shows pages returned.

**[C5] `cbm.km`** | Classic and up | moves cbm.s:37-675 (1,220 B) and file.s `cbm_open/create` (170 B) out of resident. Mount, umount, mntinfo and diskio (681 B) stay resident. Resident saving ≈ 1,390 - 132 (C4) = **~1,250 bytes**. Those are CODEHI bytes, so KRAM code can move up into CODEHI: `KSTART` rises by ~4 pages | cost: 2-3 days | break: a CBM mount now needs `/lib/km/cbm` on the root disk (mkimage adds it) | depends: C2, C4 | risk: the module's BSS (`w_busy`, `nbuf`, ~33 B) moves into module pages and is lost on unload, so unload must refuse while a write is open (it already counts FT_CBMW, cbm.s:933) | test: `Drives.test_cbm_disk` plus a new "mount, umount, `free` shows the pages back".

**[C6] `SYS_KCTL` replaces `SYS_CACHE`** | all | the syscall page is full (jtab.s:11). Fold cache ops 0-3 and modules 4-6 (load path, unload id, list) into one call | cost: about 40 B handler, 0 table bytes | break: `src/bin/cache.s` changes and a `mod` command is added | depends: C4.

**[C7] Block-driver vector** | all | `dev_drv[NDEV]` indexes `bdv: {read, write, probe}`. Driver 0 is iec (blk.s:496-547), driver 1 is reu (blk.s:567-579). This replaces blk.s:212-214 and 281-283 | about ±10 bytes | **This is the drive-code-upload hook ([C10]).** Leave the REU cache where it is, wrapped around the driver call in bread and bwrite | test: Cache tests, REU tests.

**[C8] Tick hook list plus NMI vector** | all | 4 vectors (8 B BSS), called after `con_cursor_tick` (proc.s:240) through a small loop (~22 B); `nmi_handler` (main.s:208) becomes `jmp (nmi_vec)` (+5 B). Uses: UCI network polling, a SID player, RESTORE as an "sysrq"-style dump. **Do not add a raster IRQ yet**: no consumer exists, and the IRQ source today is only CIA1 (proc.s:233). Add it when fast1541 needs raster-safe windows | test: devzero-style test module that counts ticks.

### STRETCH (cooler OS)

**[C9] UCI as a first-class filesystem** | Recommended | Two modules:
- `uci.km`: transport (probe `$DF1D==$C9`, push, response and status queues), ~150 B (UNVERIFIED: WP1 has not measured anything).
- `ucifs.km`: an fs row for C2, ~800-900 B (by analogy with cbm's 1,220).

The 1-byte `ino` becomes a driver handle into a module-BSS vnode table (e.g. 16 paths x 64 B = 1 KB of *module* memory, not resident). Keep one cached target handle (the target has one open file per instance, `docs/roadmap.md:180,187`). Device: dev 5 = DOS instance 1. Mount syntax: `mount uci /u` (A = `'U'` in place of drive 9-11). init auto-mounts it when the probe passes. **Root stays c64fs** on every tier: the image boots everywhere, and with the REU cache, `/bin` loads from the emulated 1541 are already warm. Pivot later through a `root_dev` byte in namei (fs.s:1073, +1 B). Software IEC (target `$05`): **skip it.** Its only extra over the bus path is speed, and UCI DOS already gives that. An Ultimate's Software IEC drive on the serial bus is reachable by cbm.km today | test: hardware only (S9), plus a host-side fake UCI model, since VICE has none (`docs/roadmap.md:275`).

**[C10] fast1541.km: drive-side code upload as a block driver** | Classic and Expanded with a 1541-class drive | probe (M-R a ROM signature), `M-W` the drive routine, `M-E`, then overwrite `bdv.read` for that device (C7). On a timeout or I/O error, restore the standard read and re-probe at the next mount, since drive RAM is lost on a drive reset. `fini` sends the drive's exit sequence and restores the vector. Size per `docs/design/fast-io.md:85`: ~160 B code + 170 B drive blob, all in the module | depends: C4, C7, **and the physical-1541 stall being understood first** (`docs/wip.md:65-67`: a drive-side loader runs the same drive) | licence: credit fastboot1541 / Krill per the existing shortlist.

**[C11] REU cache as a module** | Expanded | ~530 B resident (blk.s:659-1010, `cdma`..`sys_cache`, $A48D-$A6A0 plus INIT) would be 0 on Classic. Chicken and egg: `cache_attach` runs before the root mount (blk.s:851). As a module it attaches after init loads it, so the first reads of a boot bypass it. Feasible, but it changes the cache's verified boot behaviour. Do it last, if at all.

**[C12] `/dev` namespace through C1** | majors 0 null, 1 console, then module-provided:
- `zero`
- `rtc`: read returns `YYYY-MM-DD HH:MM:SS`, from UCI time or the CIA TOD.
- `reu`: seekable raw REU. `f_pos` is 3 bytes, enough for 16 MB.
- `sid`: write (reg, val) pairs.
- `uci`: raw command pipe for experiments.
- `disk9-11`: 256-byte blocks at `f_pos`/256, which deletes `SYS_DISKIO` (cbm.s:818-895, 160 B) and makes `format` plain file I/O.

`net` and `http` (UCI target `$03`) as one-socket-at-a-time files: stretch of the stretch. mkimage already makes device nodes (`--dev console:1`, `Makefile:52`).

## 4. Staged path

| Stage | Contents | Resident Δ (est.) | Proves |
|---|---|---|---|
| 1 | C1 + C2 (+C3) | ≈ -15 | seams exist; no behaviour change |
| 2 | C4 + C6 + devzero | +170 | load, link, unload in VICE |
| 3 | C5 cbm.km | **-1,250** | real module, CI-tested; KSTART up ~4 pages |
| 4 | C7 + C8 | +35 | driver and IRQ hooks |
| 5 | C9 uci/ucifs | 0 | Recommended storage |
| 6 | C10, C12, maybe C11 | 0 (C11: -530) | fast path, /dev |

## 5. Things I would NOT change

- **c64fs, blk, standard iec, exec and the CX loader stay resident.** They read every module in. A "loader module" just moves the bootstrap problem.
- **The IRQ entry, scheduler, syscall page, mem, the file table and pipes, console and kbd** stay too: panic needs the console (main.s:235-249), and every syscall goes through them.
- **mount, umount and mntinfo stay generic and resident** (681 B): they are how modules get loaded.
- **No by-name symbol resolution, no ELF-like format.** Absolute link plus a hash is the cheapest correct answer when the kernel and its modules always ship together.
- **No raster IRQ and no Software IEC backend** until a consumer exists.

## 6. Open questions for the humans

1. Should a module's pages come from the TPA (top-down, dynamic, my proposal) or from a fixed module window below `KSTART`? A dynamic edge is the "TPA-agnostic" NTH in `docs/roadmap.md:287`, but it makes `free` vary with what is mounted.
2. Is it acceptable that a CBM mount needs `/lib/km/cbm` on the root disk? A root disk without it cannot mount CBM disks.
3. Should UCI become root on Recommended, or `/u`? I recommend `/u` now and a pivot later.
4. The syscall-number churn: may `SYS_CACHE` become `SYS_KCTL`, and `SYS_DISKIO` be replaced by `/dev/diskN`?
5. Does the hardware session's WP1 (`uci` explorer) land before C9? The UCI byte estimates here are unmeasured.
