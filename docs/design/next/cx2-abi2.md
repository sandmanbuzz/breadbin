# CX v2 and syscall ABI v2: exact spec (design note, next contract)

Status: paper only. Nothing here is built or run. Base: `next/contract-free` (= footprint a9b6acf) for exec/proc/lib, footprint 05eb474 for the syscall entry ("v1.5": `jsr enter` table at `SYS_BASE+3n`, a 3-byte record per call, 75 cycles constant). Breaking changes are allowed; every binary is rebuilt with the OS. Tags: **V** = I read the code at the cited line; **U** = inferred, not checked or not run. Cycle counts are hand counts from 6502 tables (no page-cross penalties).

## 0. Decisions in one screen

1. **CX v2** = image at file offset 0, then the relocation streams, then the extension tables, then a **20-byte trailer** ending in `"CX",2`. File block *i* = process page *i*, so exec can read pages straight in (from the bus, the REU cache, or an image already in the REU).
2. **Relocations** are 1-byte deltas with a 3-byte escape and a 3-byte terminator. Two classes: P (+ load page) and L (+ library page). Loop: **37 cyc/reloc read in place**, against 49 + ~62 for the fs_read copy today.
3. **Syscall entry stays v1.5**: `SYS_BASE+3n` addresses and the 3-byte records. The record's spare byte becomes an **argument descriptor** for the EFAULT checks. No 5-byte records.
4. **NSYS stays 32.** `SYS_CTL` absorbs ISATTY, CONMODE, CACHE and DISKIO, and `SYS_SYSINFO` absorbs MEMINFO. The freed slots hold CTL, SYSINFO, EXEC, BRK and LSEEK. The `$CF00` page grows by 5 bytes only.
5. **Shared library: relocation class**, loaded as pinned pages at the top of the pool at boot. Its per-process state lives in program BSS through a ZP pointer that crt0 sets.
6. **Recommended tier:** exec and overlays take a *source* (c64fs inode, REU linear image, later UCI). Measured UCI LOAD_REU is ~5 MB/s against ~16 KB/s for byte reads (hardware session). With that, relocation becomes the largest part of an exec, so the faster loop matters there.

## 1. CX v2 byte layout

### 1.1 File

| File offset | Content |
|---|---|
| 0 .. img-1 | image (CODE+RODATA+DATA, linked at page 0) |
| img .. img+relsz-1 | P stream, terminator; then the L stream and its terminator if `F_IMPORTS` |
| .. +extsz | extension area (overlay table and overlay sections; reserved in v2.0) |
| size-20 .. size-1 | trailer |

Invariant checked by exec: `img + relsz + extsz + 20 == inode size`. Otherwise ENOEXEC: the file is truncated or has trailing junk.

### 1.2 Trailer (20 bytes, little-endian)

| Off | Size | Field | Rule at exec |
|---|---|---|---|
| 0 | 2 | `img` | > 0 |
| 2 | 2 | `bss` | library CX: must be 0 |
| 4 | 2 | `relsz` | total stream bytes including terminators; ≥ 3 |
| 6 | 2 | `extsz` | skipped by the v2.0 loader |
| 8 | 2 | `entry` | offset into the image; must be < img, else ENOEXEC (today the entry is fixed at offset 0: `k_entry` low byte = 0, exec.s:539-544 V) |
| 10 | 1 | `zp_hi` | last ZP byte the program uses; the kernel clamps it to [`$2F`, `ZPMAX`]; 0 = ZPMAX |
| 11 | 1 | `stack` | maximum user stack depth in bytes; 0 = default; > `STKSAVE`−48 gives ENOEXEC |
| 12 | 1 | `heap` | pages to reserve beyond bss+argv (for `brk`) |
| 13 | 1 | `flags` | see 1.3; an unknown bit set gives ENOEXEC |
| 14 | 2 | `libid` | 16-bit CRC of the library export table and LIBBSS; checked if `F_IMPORTS` |
| 16 | 1 | `abi` | syscall ABI; must equal the kernel's `KABI` (2) |
| 17 | 2 | `"CX"` | magic |
| 19 | 1 | `ver` | 2 |

The magic sits last, so a truncated file never shows a valid magic. A v1 binary (`"CX",1` at offset 0, exec.s:139-147 V) and a text file both fail with ENOEXEC.

### 1.3 Flags

| Bit | Name | Meaning in v2.0 |
|---|---|---|
| 0 | `F_NEEDREU` | ENODEV if `reu_banks`=0 |
| 1 | `F_NEEDUCI` | ENODEV if there is no UCI |
| 2 | `F_IMPORTS` | an L stream is present; needs the loaded library with a matching `libid` |
| 3 | `F_OVERLAYS` | extension area holds an overlay table; ignored by the loader, `ovload` returns ENOSYS until it exists |
| 4 | `F_LIBRARY` | this file is the shared library: bss = 0, no L stream; exec refuses it (ENOEXEC), only the boot loader takes it |
| 5 | `F_COMPRESSED` | reserved: ENOEXEC |
| 6-7 | - | must be 0 |

### 1.4 Relocation stream

The cursor starts at image offset −1. Each byte `d`:

| Byte(s) | Meaning |
|---|---|
| `d` = 1..255 | cursor += d; patch (`image[cursor] += addend`) |
| `00 lo hi`, gap ≠ 0 | cursor += gap; patch |
| `00 00 00` | end of this stream |

Offsets are distinct and sorted, so a gap of 0 can never be a reloc and is free to mean "end". Measured (E): 4,340 of 4,343 gaps are < 255. Size: 8,686 B (v1) → 4,349 + 120 (terminators) + 440 (+11 B trailer × 40) ≈ 4,909 B, a **net saving of ≈3,777 B, ~15 blocks** (U, arithmetic on E's measurement). The patched byte must not carry past `$FF`. A carry means a corrupt image and gives ENOEXEC; this check is free in the loop (1.6).

### 1.5 Extension area (reserved, fixed now so nobody invents another)

`n` (1 byte), then `n` × 9-byte records: `file_off(3) img(2) load_off(2) relsz(2)`. Each overlay section is `[image][P stream][L stream]` and is relocated with the same loop. A process records its *source* (1.7) at spawn, so an overlay can be fetched again (REV2: overlays are CACHE pages with a refetch recipe).

### 1.6 Loader hot loop

Today (exec.s:226-279 V) the loader `fs_read`s 2-byte offsets into the 128-byte `rbuf`, at ~31 cycles per copied byte (fs.s:741-752 V), and then patches at 49 cycles per reloc (E). Effective cost: **~111 cycles per reloc**.

v2 reads the stream **in place** from the cache buffer, or from the process page that already holds it (`bp` = start of the 256-byte block, Y = file offset low byte). X stays 0.

```
; p1 = cursor (abs address), radd = addend (base or lib_page), C = 0 on entry
@l:   lda (bp),y      ; 5  stream byte
      beq @esc        ; 2
      adc p1          ; 3
      sta p1          ; 3
      bcs @pg         ; 2  page cross: out of line
@p:   lda (p1,x)      ; 6  X = 0
      adc radd        ; 3
      bcs @bad        ; 2  high byte overflow = corrupt image
      sta (p1,x)      ; 6
      iny             ; 2
      bne @l          ; 3  -> 37 cycles per reloc
      jmp @refill     ; next block of the stream (bread, or DMA into a bounce buffer)
@pg:  inc p1+1
      lda p1+1        ; bounds: base <= page < base+npages
      cmp lim_lo
      bcc @bad
      cmp lim_hi
      bcs @bad
      clc
      bcc @p
@esc: ; fetch lo, hi (may straddle the block: slow-path getbyte), 0/0 -> done
      ; else p1 += gap, bounds check as in @pg, clc, jmp @p
```

The page check costs nothing on the hot path: the cursor changes page only through `@pg` or `@esc`. A bad stream can therefore patch only the process's own fresh pages, and those are freed when exec fails. `@refill` refuses to go past file offset `img+relsz` (ENOEXEC). At the end, the position must equal `img+relsz` exactly.

| Program | relocs | v1 (49 + copy) | v2 (37) |
|---|---|---|---|
| sh | 428 | ~47.5k cyc | 15.8k |
| as | 593 | ~65.8k | 21.9k |
| average | 109 | ~12.1k | 4.0k |

Bytes: the loop and refill are about the size of `relocate` (~57 B, U). The escape and bounds paths add ~30 B and trailer parsing ~30 B. `rbuf` (128 B of kernel BSS, exec.s:27 V) is deleted.

### 1.7 Load algorithm and sources

```
exec_load(src):                         ; spawn, exec and (later) ovload share this (= M0-6)
  T = src.read(size-20, 20)             ; via fs_read (handles a trailer straddling 2 blocks)
  validate T (1.2, 1.3), size invariant, abi, libid, flags vs tier
  npages = ceil(img + bss + heap*256 + argsz); pages = page_alloc(npages)
  for i in 0 .. ceil(img/256)-1:  src.page_to(i, base+i)   ; whole blocks, straight in
  run P stream with radd = base; if F_IMPORTS: L stream with radd = lib_page
  zero bss (from img: also wipes the stream bytes the last image block dragged in)
```

Copying the last, partial image block whole is safe: the allocation always extends past it (argv needs ≥ 2 bytes). The stream's first block is then already in the process's own page and is read in place (`bp` = that page).

| Source | `page_to` | stream blocks | When |
|---|---|---|---|
| c64fs inode | cache hit: copy; REU block cache hit: 256-byte DMA from page 4+b (blk.s:21-24 V); else `iec_read` straight into the page (F3, ~50-70 B, U) | `bread` (cache) | all tiers |
| REU linear (`reu_addr`, `len`) | one DMA per ≤ 8 KB chunk | DMA into a `bget_buf` buffer (blk.s:240 V), invalidated after | Expanded/Recommended |
| UCI file | later: LOAD_REU into a scratch REU region, then "REU linear" | | Recommended |

**REU exec store (Recommended, coordinator addition).** After a successful exec from c64fs on a machine with an REU, or on demand (`uci` LOAD_REU of a host file), keep the whole CX file contiguously in a CACHE-class REU region. The store is keyed by (dev, ino, size) and must be invalidated by `fs_write`, `itrunc` and `unlink` on that inode, by mount/umount, and by `cache off`. c64fs has no generation number, so without the write hook an inode reused at the same size would run stale code. That would cost one table compare per write (U, about 20 B).

Recommended `as` exec (~5.8 KB v2): LOAD_REU ~1.2 ms (5 MB/s, hardware-measured rate), DMA ~6 ms, relocation 21.9k cyc ≈ 22 ms, so **~30 ms against ~26 s** on the Classic bus (U: arithmetic). Relocation is ~70 % of that, which is why the 37-cycle loop matters on this tier. Option for later, not now: also store the *relocated* image keyed by the base page, so that reloading at the same page is pure DMA.

DMA stalls the CPU. A 32 KB transfer is ~33 ms, which is two ticks: keyboard scans are lost and `ticks` drifts (U). So DMA is chunked to ≤ 8 KB with interrupts allowed between chunks.

### 1.8 Tooling: does the double link still work?

**Yes, for both.** cx.py diffs the links at `$0000` and `$0100` and rejects any byte that differs by other than +1 or when the sizes differ (cx.py:19-28 V; Makefile:43-47 V). `enumerate` yields the offsets ascending, so delta-encoding is a pure re-encoding of the same list.

- **L class:** a third link. `tools/cx.py --stub` turns the library's label file into `bbstub.s` (`.export print := LIBORG + $0012` …), assembled twice (`-D LIBORG=$4000` and `$4100`).
  - Links: A = prog `-S 0` + stub0; B = `-S 256` + stub0; C = `-S 0` + stub1.
  - P relocs = diff(A,B); L relocs = diff(A,C).
  - A byte in both sets gives a build error. That catches `>(libsym-progsym)` and similar mixes, loudly.
  - Library pages must be page-aligned, like program pages, so low bytes never differ.
- **`entry`** = the `_start` label from `-Ln`, 0 if absent. **`zp_hi`**: add `define = yes` to the ZEROPAGE segment in `prog.cfg` and take `__ZEROPAGE_RUN__+__ZEROPAGE_SIZE__-1`. Programs today use `= $xx` equates (E §f), which the linker cannot see. So add a host lint that fails the build on a ZP equate above the declared range (see review item 4).
- **mkimage.py does not write or parse CX** (V: no CX references; it copies `build/root`). It needs no change. `/lib/bb` is just another file.
- **The on-machine assembler is a second CX writer** (as.s:150-195 V, header bytes `"CX",1`, 2-byte relocs in `rbuf`). It must emit v2 in the same commit: write the deltas in `reloc_at` (it emits offsets in ascending pc order in pass 2, U for every directive), and append the trailer. Its builtin `SYM` table of syscall addresses (as.s:1295-1318 V) changes with the table below. Its `RMAX`×2 buffer stays the same size and holds ≥ 2× the relocs.
- `tools/test_mkimage.py:111-128` (V) asserts `CX\x01` and must be rewritten as v2 round-trip tests.

## 2. Syscall ABI v2

### 2.1 Entry

Keep v1.5 (footprint 05eb474, V): `jsr SYS_x` → `jsr enter` → `records-2,x`/`records-1,x` with X = 3n+2; 75 cycles; `sys_return` in CODE. The single-gateway idea is already met: the gateway is the page, and the function code is the entry address. CP/M's `C=fn; call 5` would cost 2 bytes and a register at each of 193 call sites (E §g). B's 5-byte inline records would save 32 B of the page but move every address, for no cycle gain. **Not adopted.**

v2 adds one thing to `enter`: the record's third byte (`.byte 0` today) becomes an argument descriptor.

```
        ...push sys_return-1, handler-1 (unchanged)...
        lda records,x        ; 4  descriptor (record n+2 = records + X)
        bne @chk             ; 2  -> 81 cycles for unchecked calls
@go:    ldx k_x
        lda k_a
        cli
        rts
@chk:   jsr chk_args         ; CODE, ~50 B; interrupts still off, in_kernel = 1
        bcc @go
        pla
        pla                  ; drop handler-1: sys_return-1 is next
        lda #EFAULT
        cli
        rts                  ; C set -> sys_return -> caller sees EFAULT
```

+5 B in the page: v1.5 uses ~227 of 256 (U: hand count, 96+96+35).

**Descriptor byte:** bits 7-6 give the class: 00 none; 01 kernel writes `r1` bytes at `r0`; 10 kernel writes N bytes at `r1`; 11 kernel writes N bytes at `r0` (N = 0: length in A). Bits 5-0 = N.

**EFAULT policy:**
- Only buffers **the kernel writes** are checked. The range must lie inside the caller's pages `[p_mpage, p_mpage+p_mlen)`. ZP and stack are refused: a `read` into the stack page would overwrite the in-progress kernel frame.
- Buffers the kernel only reads (write data, paths, argv) are not checked in v2. Reading cannot corrupt anything; the I/O-page read side effect (`$DC0D`) is in the open questions.
- `cur=$FF` (kernel-internal `spawn_kernel`, exec.s:34-52 V) skips the check.
- `SYS_CTL` checks per op by calling `chk_args` itself.

### 2.2 Register conventions (unchanged)

Arguments in A, X, Y, r0-r2 (`$02-$07`, breadbin.inc:42-44 V). C clear = ok; C set = error, errno in A. Only C, A and the outputs each call names are defined; the rest are clobbered.

New errno: `EINTR=4` (reserved), `EFAULT=14`, `ENOTTY=25`, `ESPIPE=29`, `ENOSYS=38` (unknown ctl op or sysinfo key: "kernel too old" is distinct from EINVAL).

### 2.3 Every syscall: keep / change / absorb

| n | v1 | v2 | Desc | Notes |
|---|---|---|---|---|
| 0 | EXIT | keep | - | |
| 1 | SPAWN | **change** | - | `r2` lo = child stderr fd, `$FF` = inherit (exec.s:65-69 V always inherits). `2>&1` = pass the stdout fd; no `dup` needed |
| 2-6 | WAIT KILL GETPID YIELD SLEEP | keep | - | |
| 7 | OPEN | **change** | - | new flag `O_NONBLOCK=$80` (bit free: breadbin.inc:52-57 V) |
| 8 | CLOSE | keep | - | |
| 9 | READ | **change** | `$40` | EAGAIN with r1=0 on an `O_NONBLOCK` console or pipe with no data |
| 10 | WRITE | keep | - | |
| 11-16 | PIPE MKDIR RMDIR UNLINK RENAME CHDIR | keep | - | |
| 17 | GETCWD | keep | `$C0` (len in A) | file.s:1270 V |
| 18 | STAT | keep | `$88` | buf[8] at r1 |
| 19 | PROCINFO | keep | `$D0` | buf[16] at r0 |
| 20 | MEMINFO | **absorbed** → SYSINFO key 1 | | slot 20 = **SYSINFO** `$D0` |
| 21 | FSINFO | keep | `$88` | |
| 22 | TIME | keep | - | |
| 23 | ISATTY | **absorbed** → CTL op 0 | | slot 23 = **CTL** |
| 24 | CONMODE | **absorbed** → CTL op 4 | | slot 24 = **EXEC** |
| 25-28 | GETUID SETUID MOUNT UMOUNT | keep | - | |
| 29 | MNTINFO | keep | `$E2` | buf[34] at r0 (cbm.s:969 V) |
| 30 | DISKIO | **absorbed** → CTL op 7 | | slot 30 = **BRK** |
| 31 | CACHE | **absorbed** → CTL op 6 | | slot 31 = **LSEEK** |

Reusing slot numbers is safe only because of the `abi` byte. A binary that is not rebuilt fails with ENOEXEC instead of calling the wrong handler.

### 2.4 New calls

**CTL (23):** A = fd or target, X = op, Y = small argument, r0/r1 = buffers. The dispatcher is `cpx #NOPS; bcs @mod; lda ctl_hi,x; pha; lda ctl_lo,x; pha; rts` (~16 B plus 2 B per op). Ops ≥ `$40` go to a registered module range (CP/M 3 RSX bones) and give ENOSYS until one exists.

| Op | Name | In | Out / errors |
|---|---|---|---|
| 0 | ISATTY | A=fd | C clear if console; ENOTTY |
| 1 | GETFL | A=fd | A = `f_flags` |
| 2 | SETFL | A=fd, Y = `O_NONBLOCK`/`O_APPEND` bits | |
| 3 | NREAD | A=fd | r1 = bytes readable now ($FFFF unknown): console line or keys, pipe count, file size−pos. This is the one-fd `poll`; no select |
| 4 | CONMODE | A=fd (must be the console), Y = 0 cooked / 1 raw | ENOTTY |
| 5 | SIGINT | Y = 0 default, 1 ignore, 2 catch | catch: `p_sig=SIGINT` is delivered as `ZP_SIGF=$24` ← 1 |
| 6 | CACHE | Y = 0 stat (7 B at r0, checked), 1 off, 2 on, 3 flush | as blk.s:965-1000 V |
| 7 | DISKIO | A = drive, Y = op, r0 buf (256 checked), r1 block | as cbm.s:814-830 V |

**SIGINT catch delivery.** Delivery happens in the target's own context: in `check_signal` (proc.s:203-209 V) and in the IRQ's `@die` test (proc.s:289-298 V) when `cur` is in user mode. In both cases the target's ZP is live, so this is a plain `lda #1; sta ZP_SIGF` plus clearing `p_sig`. Nothing ever writes into a save area from the IRQ: `slot_save_ptr` (proc.s:54-88 V) would clobber `p3`/`tmp0-1` in interrupted kernel code. Exec resets the mode to default.

**SYSINFO (20):** A = key, r0 = buf[16] → r1 = length; unknown key gives ENOSYS.
- Key 0: `abi, kver_hi, kver_lo, nsys, nctl, tier (bit0 REU, bit1 UCI, bit2 U64 turbo), reu_banks, lib_loaded, libid(2)`.
- Key 1 (old MEMINFO extended): `free, total, reu_banks, procs, maxprocs, pool_first, pool_last, largest_free_run`. The first five bytes keep their old offsets (mem.s:94-130 V), so `free`/`ps`/`uptime` change only the call.
- Key 2: build id (4).

**EXEC (24):** r0 = path, r1 = argv (NULL = {path}), same as spawn.
1. Do everything that can fail first: namei, trailer, flags, `measure_args`, `page_alloc` of the new run while the old one is still held.
2. Load, relocate, and copy argv out of the *old* image.
3. Only then free the old pages, reset ZP `$02..zp_hi` and the signal mode, `con_release(pid)`, set SP=`$FF`, and `jmp proc_entry`.
4. The pid, ppid, fds, cwd, uid and `SP_*` flags are kept.

Every failure returns to the intact caller (ENOMEM if both images do not fit). There is no point of no return. ~120 B (U).

**BRK (30):** A = new end page (0 = query) → A = end page. It grows only into free pages that directly follow the run and shrinks no lower than img+bss+argv. ENOMEM. It updates `p_mlen` and `ZP_MEMTOP=$23`, which spawn and exec also set. ~60 B (U).

**LSEEK (31):** A = fd, X = whence (0 SET, 1 CUR, 2 END), r0/r0+1/r1 = 24-bit signed offset → same registers = new position.
- c64fs file or dir: set `f_pos0..2` (file.s:15-17, 471-500 V).
- Pipe, console, null and CBM-DOS (`f_pos` holds track/sector there, file.s:347-351 V): ESPIPE.
- A negative result gives EINVAL.
- Past EOF is allowed: reads return 0 and holes read as zeros (fs.s:731 V).
- File block indices are 1 byte (`lda f_off+1; jsr bmap`, fs.s:~728 V), so positions ≥ 35,840 cannot be backed. Writing there must return EFBIG (U: not checked that `fs_write` does). ~60 B (U).

### 2.5 Library v2 (static part)

- **crt0** (`_start`, the CX `entry`): sets the `lst` ZP pointer to `libstate: .res LIBBSS` in program BSS, then `jsr main; lda #0; jmp exit`.
- **`exit`** flushes stdout, then `jmp SYS_EXIT`. The 46 `jmp SYS_EXIT` sites (grep V) become `jmp exit`.
- **stdout** is buffered in 128 B at `(lst)`. It is flushed on newline when fd 1 is a tty (CTL op 0, cached), when full, and in the lib's `read`/`spawn`/`exec`/`wait`/`exit`. **stderr stays unbuffered.** Per-character cost drops from ~540 to ~40 cycles (B L3, U).
- `user_ret` (proc.s:187-189 V) remains the fallback for programs without crt0, and it does not flush.

## 3. Shared library

| | Fixed address (A: `$0800` + jump table) | **Relocation class (recommended)** |
|---|---|---|
| Call cost | +3 cyc and +3 B per entry (jump table), or relink everything on any lib change | plain `jsr`, 0 extra cycles; one L reloc per call site |
| Memory | pins the pool bottom | PIN pages at the top (REV2 tagged allocator); the bottom stays first-fit for PROC |
| Failure: library grows | pushes `pool_first`; fine with the table, every binary breaks without it | none: `libid` changes, so everything is rebuilt (it already is) |
| Failure: version skew | silent wrong-target `jsr` if the table order changes | `libid` mismatch gives ENOEXEC, never a crash |
| Failure: load timing | INIT runs from the load area at `$0801` (main.s:30-60 V); the library cannot be placed until INIT is released (U on the exact order in `kmain_run`) | loaded anywhere free, before `spawn_kernel` |
| Tier variants, two versions resident | impossible | possible (refcount, `libid` per process) |

The library file `/lib/bb` is a CX v2 with `F_LIBRARY`: bss = 0, no self-modifying code (core, input and err V; passwd U). Its small state moves to ZP `$24-$2F`; its buffers go through `(lst)`:
- input: `rd_*` (259 B) — input.s:6-10 V
- num: `ldec` (7 B) — num.s:8 V
- core: `lchar` (1 B) — lib.s:7 V

`passwd` and `target` (≤ 3 users, E §a) stay static objects.

Failure scenarios of the recommendation:
1. `/lib/bb` is missing or corrupt, so every `F_IMPORTS` binary, including init, gets ENOEXEC. The kernel panics with "no /lib/bb" instead of "no init". Proposed: link `init` statically, so a damaged library still boots far enough to print why (open question 2).
2. A library bug hits every process (true of both designs).
3. A program that patches library code damages every process. There is no protection on a 6502; documented.

## 4. Migration (each commit builds; the whole tree is rebuilt every time)

| # | Commit | Gate |
|---|---|---|
| 1 | CX v2: cx.py writer, `as.s` writer, kernel trailer + delta loader + bounds, `KABI=2`, delete `rbuf` | `make test-host` (new TestCX: round trip, escape, terminator, size mismatch, carry overflow), smoke, `Boot.test_19_assembler`, `test_17_basic_script`, `test_24_editor`, `test_09_errors`; new: a v1 file gives ENOEXEC |
| 2 | exec straight to pages (sources: c64fs, REU cache) | `Cache` (all), `REU`, smoke; `cache stat` boot read count before/after |
| 3 | descriptor byte + `chk_args` + EFAULT | **full suite** (syscall path); new: `read` into `$E000` and into `$0100` gives EFAULT |
| 4 | CTL; ISATTY/CONMODE/CACHE/DISKIO absorbed; `basic ls edit login passwd cache format` and `as` SYM updated | `Console`, `Keyboard`, `Cache.test_off_and_flush`, `Drives.test_format`, `test_24_editor`, `test_25_login_password`, `test_03_ls_bin` |
| 5 | SYSINFO, MEMINFO absorbed | `test_22_easy_commands` |
| 6 | lib: crt0, `exit`, buffered stdout | smoke, `test_06`, `test_11`, `test_12`, `test_20_more_pages` |
| 7 | spawn stderr in r2, `sh 2>` | `test_06_redirect_roundtrip` + new |
| 8 | SIGINT catch, BASIC RUN/STOP | `test_13`, `test_14`, `test_17`, `test_18` + new |
| 9 | LSEEK; O_NONBLOCK/NREAD | new seek test; `Keyboard` |
| 10 | EXEC; `login` execs `sh` | `test_25`, `test_15_too_many_processes`, `test_08` |
| 11 | ZP re-split, `zp_hi` save, BRK/memtop (memory-map milestone) | **full suite, stock ROMs and JiffyDOS** |
| 12 | shared library (L class, `/lib/bb`, PIN pages) | **full suite**; `free` before/after |
| 13 | REU exec store, UCI source | `REU`, `Cache`; hardware run |

Kernel bytes, sum of the U estimates: ~+500 B of code against 267 B of room at a9b6acf (E §d; U for 05eb474). Commits 10-13 wait on the footprint pass or a `KSTART` decision.

## 5. Adversarial review: how this could brick the boot disk or corrupt a process

1. **cx.py and the kernel disagree on the trailer.** Every exec fails and the boot panics "no init" (main.s:48-50 V). This is not a brick: the D64 is rebuilt on the host. On a *physical* disk, `cp` of a bad binary over `/bin/init` or `/lib/bb` makes it unbootable until it is rewritten from the host. Mitigations: a static init (open question 2); the kernel tries `/bin/init`, then `/bin/init.0`.
2. **Corrupt stream.** Every patch is bounded to the fresh run (the page check) and the stream is bounded to `img+relsz`. All of it happens before `PS_READY`, and failure frees the pages. Residual: patches *inside* the run land in wrong places in the image, so the process runs corrupted code. That is self-harm. It is not detected without a checksum (~10 cyc/byte; open question 5).
3. **Trailer lies.** `entry` ≥ img and `stack` too large are rejected. A low `bss` only hurts the program itself. A high `heap` gives ENOMEM.
4. **`zp_hi` lies low.** Each process saves and restores only its own declared range, so other processes stay correct. The liar sees stale bytes. The real risk is a build that under-declares (equates, §1.8), hence the lint and the clamp to ≥ `$2F`. The kernel's `$08-$1F` block is always inside the clamp. Kernel globals in ZP were unprotected before and still are.
5. **EXEC.** argv is copied before the old pages are freed. Raw console mode is keyed by pid (con.s:394-418 V) and would survive the exec, so exec calls `con_release`. Unflushed stdout is flushed by the lib wrapper. Children keep `p_pslot = cur`, which is unchanged. Exec needs both images resident, so ENOMEM leaves the caller intact.
6. **EFAULT check with interrupts off:** ~40 cycles more latency on checked calls only. A wrong descriptor table would refuse legitimate calls loudly (the tests in commit 3 cover each class).
7. **REU exec store staleness:** covered by the write/unlink hooks and the mount hooks. A missed hook runs the old program, so the hook belongs in the same commit as the store, with a test that rewrites a binary and runs it.
8. **DMA starving the IRQ:** chunked (§1.7). An unchunked 32 KB DMA loses ~2 ticks (U).
9. **SIGINT catch** never writes into another process's memory (§2.4), so the IRQ cannot corrupt a saved context.
10. **Slot reuse:** guarded by `abi`. A user `.s` file using `sys_isatty` fails to assemble (loud) instead of running.

## 6. Open questions for the owner

1. Reuse freed slot numbers (proposed; the page stays at NSYS=32) or append new calls (+6 B of page per call)?
2. Static `init` (+~0.8 KB on disk, always resident) so a broken `/lib/bb` still boots, or panic?
3. Should kernel *reads* of user memory also be checked? The only harm found is reads of the I/O page (`$DC0D` acknowledges CIA interrupts), which a `write(fd, $DC00, n)` would do. A 1-compare `$D0..$DF` refusal costs ~8 B.
4. ZP map: adopt A's re-split (lib `$24-$2F`, program `$30-$6F`, kernel globals `$70-$8F`) in commit 11, or keep `$40-$5E` for the kernel and give programs less?
5. Is a CX image checksum worth ~10 cyc/byte (~40 ms for sh) on Classic, given that the REU and UCI paths make loads cheap?
6. Who owns the `as.s` change (commit 1 must land the kernel, cx.py and as.s together)?
7. REU exec store: key on (dev, ino, size) plus write hooks, or add a generation byte to c64fs inodes if the filesystem is redone anyway (REV2: fs is a free variable)?
8. `login` execs `sh` (changes `ps`, and a shell `exit` goes back to init)?
