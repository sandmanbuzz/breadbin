# UCI v1: Ultimate file storage as a development unblocker (design note)

Status: design, nothing built. **Throwaway by intent**: v1 is resident and quick; v2 (ship milestone) re-homes it as a module
(section 6). Base: `next/contract-free` (pool edge `$A100`). Code claims cite `file:line`, VERIFIED (read in this tree) or UNVERIFIED.
Hardware numbers: `hw-bench:docs/hardware-notes.md`, "UCI as measured" (C64 Ultimate, fw 1.1.0, polled). Byte counts are estimates.

## 1. Goals, non-goals, done

**Goal.** With the Command Interface enabled: a mounted tree on the Ultimate's storage, real directories, files far beyond 35 KB, used by
unmodified programs through the existing syscalls, and runnable programs.

**Non-goals.** Root on UCI, network, Software IEC, REU cache prefill (F8), image mounting, clock. Any change on Classic: without a UCI the
kernel never touches `$DF1B-$DF1F`.

**Done** (observed, not inferred):

1. VICE, stock and JiffyDOS ROMs: boot unchanged; `mount uci /u` says "no such device"; smoke, Drives, Persistence, REU tests pass;
   `make size` delta quoted.
2. Bench: `mount uci /u`; `mount` lists it; `ls /u/Temp` and `ls -l` match the host.
3. `cat` of a pattern file made by the standalone `experiments/iec-stall/uci.py write` shows the right bytes; `wc` says 32768.
4. `cp /bin/as /u/Temp/as`; `/u/Temp/as` runs; `cd /u/Temp; ./as` runs.
5. A 100 KB write completes, `ls -l` says 102400, and the standalone tool reads the same bytes after a reset.
6. `cp /u/Temp/a /u/Temp/b`, `mv`, `rm`, `mkdir`, `rmdir` and the error cases give the same messages as on c64fs.

## 2. The smallest transport

Registers, as used by the working tool `experiments/iec-stall/uci.s` (VERIFIED on the bench): `$DF1C` control (write `$01` PUSH_CMD,
`$02` DATA_ACC, `$04` ABORT, `$08` CLR_ERR; read bit 7 data available, bit 6 status available, bits 5-4 state 00 idle / 01 busy /
10 last / 11 more, bit 3 error); `$DF1D` command FIFO (write) and ID `$C9` (read); `$DF1E` data; `$DF1F` status text. **Polled**: the
completion IRQ hung the interface on 1.1.0 (measured).

```
uci_probe:  ldx #3                          ; at mount time only, never at boot
@r:         lda $DF1D : cmp #$C9 : bne nodev : dex : bne @r
            lda #$0C : sta $DF1C            ; ABORT|CLR_ERR: clear what a reset interrupted
            IDENTIFY target 1, expect "ULTIMATE-II DOS"   ; open bus can read $C9 by chance
uci_begin:  wait state 00 (bounded) ; sta $DF1D target ; sta $DF1D cmd
uci_put:    sta $DF1D                       ; path bytes, 32-bit args LSB first
uci_go:     lda #$01 : sta $DF1C ; wait state >= 10, or timeout -> ABORT, EIO
uci_get:
@b:         bit $DF1C : bpl @pk             ; 4+2
            lda $DF1E : sta (p1),y          ; 4+6
            iny : bne @b                    ; 2+3 = 21 cycles/byte
@pk:        drain $DF1F -> st_code ; lda #$02 : sta $DF1C ; state 11 -> next packet
```

The measured flat 62 us/byte is the measuring loop (`rstore`: a `jsr`, a mode test, 16-bit counters, ~60 cycles), not the register.
The 21-cycle loop predicts ~45 KB/s at 1 MHz if the FIFO keeps up (UNVERIFIED, Q1). Writes: 15 cycles/byte (`lda (p1),y : sta $DF1D :
iny : bne`); measured 21 KB/s with a slower loop. Command push ~10 cycles/byte on top of the Ultimate's latency (open 4.3-4.8 ms).

**Error map** (~50 bytes; Q4 completes it): empty status (past EOF) or `00` -> OK, short count; `01` DIRECTORY EMPTY -> EOF; `02`
TRUNCATED -> short count; `82`/`83`/`88` or text starting `F` (`FILE DOESN'T EXIST`) -> ENOENT; text starting `A` (`ACCESS DENIED`)
-> EPERM; `84`/`85` (no file open) -> EIO, a driver bug; anything else and timeouts -> EIO.

## 3. Mapping onto the kernel

**Device.** `NDEV` 5 -> 6 (`k.inc:10`): dev 5 = UCI. One byte more in each per-device array (`blk.s:56-59`, `fs.s:18-25`, `cbm.s:30`):
12 bytes BSS. `FS_UCI = $80` beside `FS_C64`/`FS_CBM` (`k.inc:13-14`), so each site becomes `beq c64 / bmi uci / (cbm)`: 5 bytes with
a local `jmp`.

**The 11 `dev_type` sites** (VERIFIED, matching Lens C; each treats nonzero as CBM today):

| Site | Today | For UCI |
|---|---|---|
| `file.s:232` open, create | `cbm_create` | OPEN attrib `$06` |
| `file.s:262` open, exists | `cbm_open` | file: path slot, OPEN `$01`/`$02`/`$03` (`$0A` with O_TRUNC); dir: FT_DIR, k = 0 |
| `file.s:456` read | `cbm_read(dir)` | `uci_read` / `uci_readdir` |
| `file.s:832` `not_cbm` | EPERM | dispatch to mkdir (`$16`) / rmdir (DELETE `$09`, Q4) |
| `file.s:959` unlink | `cbm_scratch` | DELETE `$09` |
| `file.s:1036` rename | `cbm_rename` | RENAME `$0A old $00 new` |
| `file.s:1331` fsinfo | BAM count | constants; no free-space command exists |
| `fs.s:224` iget | `cbm_iget` | `uci_iget` (below) |
| `fs.s:255` iput | no-op | already right for any nonzero type: 0 bytes |
| `fs.s:879` dir_lookup | `cbm_lookup` | probe the full path |
| `exec.s:107` spawn | ENOEXEC | allowed (section 4) |

**New sites**: `sys_write` reaches `file_setup`/`fs_write` for any FT_FILE (`file.s:597-609`; CBM escapes via FT_CBMW); `oft_unref`
must flush and release a UCI handle on last close (beside `file.s:104`); the namei hook; `sys_umount`, which calls `iec_close` on the
device (`cbm.s:956`) and would address IEC device `dev_drive[5]`; `sys_mount` (`cbm.s:677`) takes `A = 'U'`; `mntinfo` returns
`dev_type` (`cbm.s:985`), so `src/bin/mount.s` learns `uci`.

**Paths: string namei.** c64fs walks one component at a time through `iget`/`dir_lookup` (`fs.s:1065-1190`) and rejects components
over `NAME_MAX = 14` (`fs.s:1107`). The host resolves a whole path in one OPEN, so the hook sits at `@comp` (`fs.s:1101`), before that
check: if `nm_dev` is UCI, jump to `uci_namei`. That catches both crossing the mount (`@found`) and a relative path from a UCI cwd
(`@rel`, `fs.s:1079`). `uci_namei`:

1. `build_path` (`file.s:1178`) normalizes the original `pp` against `p_cwd` into `pbuf`; `.` and `..` resolve textually (correct: no
   symlinks).
2. If `pbuf` no longer starts with the mount's `mt_path` as a whole component (`/u/..`), restart namei on `pbuf`.
3. Host path = `pbuf` minus the prefix. Long components work; the limit is `build_path`'s 47 characters (`file.s:1251`).
4. Parent wanted: last component to `fs_name`, `nm_ino = 3` ("a directory"), no command. Otherwise probe (method per Q2): CHANGE_DIR
   succeeds -> dir, ino 3; else OPEN + FILE INFO -> file, ino 2, size (32 bits clamped to 24) in a one-entry record, the file left open
   as an unowned cached handle; else ENOENT.

One probe per path (~5-11 ms) however deep. `uci_iget`: ino 1/3 -> T_DIR, 2 -> T_FILE with the record's size. The record is only
valid right after a probe, and every `iget(UCI, 2)` caller is right after one (open `file.s:259`, stat `file.s:1295`, chdir, spawn,
rename). That is the v1 hack. Mutating operations never use the record: they rebuild the host path from `pp`. Rename streams
`build_path(r0)`, `$00`, `build_path(r1)` straight into the FIFO (string work only in between), so no second buffer.

**cwd**: `chdir` already stores the normalized string (`file.s:1134-1142`); that is all the state UCI needs.

**24 open files against two host handles.** Measured: one open file per target, a second open re-opens, targets `$01`/`$02` are
independent. v1 has **two handle slots**, `{owner, pos(4), mode}` (12 bytes BSS). A UCI open-file entry keeps the 24-bit position in
`f_pos0-2`, a path-table index in `f_ino`, the last slot in `f_pipe`. `ensure(entry)`: owner matches -> go; else take the free or LRU
slot, flush and CLOSE it explicitly, OPEN the path, SEEK if the position is not 0, claim. A switch costs ~6 ms for reads (open 4.5,
seek 0.8, close 0.85, measured; write open is Q3). With one slot `cp /u/a /u/b` would reopen twice per 256-byte chunk; two keep it at
zero. Probe and directory commands take the victim slot the same way.

**Pool pages, not BSS**: `mount uci` allocates (`page_alloc`, `mem.s:31`) page 1 for 5 path slots of 48 bytes (a sixth UCI open:
EMFILE) and the last status text, pages 2-3 for one 256-byte read-ahead/write-behind buffer per slot. Umount frees them; Classic never
allocates them.

**Directories.** CHANGE_DIR, OPEN_DIR `$13`, READ_DIR `$14` (one packet per entry: attribute, name) -> the existing 16-byte
`{ino, name[15]}` records (`cbm.s:347-420`), ino from the DIR bit. Stateless like `cbm_readdir`: index k in `f_pos`; when the buffer
fills, ABORT, and the next call re-lists and skips k (quadratic; fine for hundreds; Q5). **Names over 14 characters show truncated
with `~` and cannot be opened by that name** (the full name works). Wider dirents are a v2 contract change.

**Sizes**: FILE INFO is 32-bit; `I_SIZE` and `f_pos` are 24-bit. v1 clamps at 16 MB.

## 4. Running programs from UCI

`spawn` calls `fs_read` three times: header (`exec.s:134`), image (`exec.s:201`), relocations in 128-byte chunks (`exec.s:248`). v1
replaces them with `jsr xread` (dev test, then `fs_read` or `uci_pread`, ~12 bytes) and opens `exec.s:107`. Reads are sequential from
0, so the probe's open handle serves them with no OPEN or SEEK. One READ_DATA takes up to 65,535 bytes as a chain of 512-byte packets
(measured: 32 KB in one command), so the image is one command. `as` (6,375 bytes plus relocations) loads in ~0.4 s at the measured rate,
~0.15 s if Q1 holds, against tens of seconds from a 1541. The CX magic check stays (`exec.s:136-157`).

**The fast path, not v1.** LOAD REU `$21` put an open 32 KB file in the REU in 6.2 ms (~5 MB/s, measured); the existing `cdma`
(`blk.s:664`, 1 byte per cycle) then fetches it: ~40 ms for 32 KB, ~20x the byte path. Cost ~70 bytes plus a staging bank outside
`/tmp` (0-7) and the cache (8-10, `blk.s:21-33`): `reu_banks-1`, when `reu_banks >= 12`. The command "assumes a 16 MB REU" and loads
past the real end were not tried (Q7), so only <= 64 KB at a bank start is safe. **v1 is the byte path**: program loads are already
sub-second, it needs no REU (Recommended does not imply one), and writes and directories need it anyway. The fast path pays its 70
bytes with F8 (174,848 bytes: ~4-11 s by bytes, ~0.25 s by DMA) and overlays: v1.1 or v2.

## 5. Cost

| Piece | Bytes (UNVERIFIED) |
|---|---|
| Transport, error map | ~205 |
| `uci_namei`, probe | ~130 |
| Handle slots, path table | ~110 |
| read, write, write-behind, close | ~170 |
| readdir, unlink, rename, mkdir, rmdir, fsinfo, iget, lookup | ~190 |
| mount/umount/mntinfo | ~60 |
| Core: 11 sites x 5, new sites, `xread` | ~90 |
| **Total** | **~0.95 KB** code, ~36 BSS |

Lens C's "~120 bytes" counted the branches only; its module estimate (~150 + 800-900) agrees with this table. Room (VERIFIED, `make
size` on a scratch copy): **267 bytes** below `$CF00`, 183 in KHI. So v1 costs **~3 pool pages on every tier** (`KSTART`/`KRAM` `$A100`
-> `$9E00`, `k.inc:4`, `src/kernel.cfg`) plus 3 pages while mounted. BSS fits.

Cut order if over: (1) read-ahead/write-behind (-2 mounted pages, ~-40 bytes; `as` writes whole buffers, `src/bin/as.s:183-208`, so only
`putc`-style output redirected to `/u` slows, ~1.5 ms per write, Q3); (2) probe-handle reuse (+4.5 ms per exec); (3) rmdir/rename;
(4) text errors -> EIO.

**Classic at ~zero, if the 3 pages matter before Wave 3:** link the UCI code as its own segment with a fixed run address at the pool
top, emitted as `/lib/uci`, read by `mount uci` after a good probe (~40 bytes, as exec reads; build id checked). Classic then pays
~90 bytes. It is a module loader without relocation; not v1 by default.

## 6. v2: what goes, and the seam

Goes: the `bmi` branches (-> Lens C's C2 ops row), the probe record and ino 2/3 (-> a vnode table in module memory), the namei restart,
14-character readdir, the 24-bit clamp, residency. Stays: the transport (`probe/begin/put/go/get`), the error map, the slot cache, the
fake and the acceptance script.

The seam: (a) `src/kernel/uci.s` (fs glue) and `uci_t.s` (transport), headers saying THROWAWAY v1; (b) one jump table at the start of
segment `UCI` whose entries are exactly C2's ops (lookup, iget, iput, open, create, read, readdir, write, close, unlink, rename, statfs,
mkdir, rmdir) with cbm.s's conventions (X = dev, `fs_name`, `ci`, `sb6`, r0/r1, carry/A). Core sites call only that table, so v2 points
the ops row at it and deletes the branches; (c) only the glue calls the transport, so rtc/net modules can share it unchanged.

## 7. Testing without hardware

VICE has no UCI; `tools/fake_ultimate.py` fakes the REST API only (`fake_ultimate.py:1-8`). A VICE monitor checkpoint on `$DF1E`
cannot supply the value a load returns, and per-byte round trips would be fragile: not recommended.

**Recommended: a VICE-less 6502 test**, `tests/test_uci_sim.py`, with py65 as a pip test dependency (BSD per its project page; confirm
before adding; not vendored). A `FakeUCI` maps `$DF1B-$DF1F` on py65's observable memory onto a temporary directory and implements the
*measured* behaviour: Data More chains, 512-byte packets, empty status at EOF, `84`/`85`, the text errors, re-open, two independent
targets, ID `$C9`. Run the real kernel's boot stub up to `kmain`, call `mem_init`/`file_init`, poke one process (`p_cwd = "/u"`,
`p_cwddev = 5`) and one mount entry, then call `sys_open/read/write/close/stat/rename/spawn` and readdir with **relative paths**, so c64fs
and IEC are never reached. That covers the namei hook, the sites, the slots and the transport in seconds. Calibrate the fake by running
`uci.s` against it and diffing with the bench log. Effort ~1-2 days; the fake shares the documentation's gaps. VICE keeps the regression
(probe absent -> ENODEV; full matrix at the milestone).

**Minimal hardware run** (~15 minutes, under `tools/with-lock`): mount the image, reset, type through the key buffer by DMA (`feed`
in `experiments/iec-stall/bench_basic.py`; works because `kbd.s` keeps `$0277`/`$C6`), read screen RAM; section 1 items 2-6; cross-check
bytes with the standalone `uci.py` after a reset. `/Temp` (Ultimate RAM disk) for speed, one USB/SD path for persistence.

## 8. Risks

- **Data loss**: cached write handles and write-behind lose the tail on reset and may leave the FAT size short. close, exit and kill
  flush and CLOSE; eviction CLOSEs explicitly. FAT is case-insensitive: `cp A a` truncates its source. Never write a `.d64` the
  Ultimate has mounted (Q6).
- **Wrong file**: mutations rebuild the path from `pp`; only reads trust the record.
- **Kernel time**: commands run in the non-preemptible kernel (`proc.s:3`) with IRQs on, so no locking, but others wait (open ~5 ms,
  create 54 ms, measured). Bounded waits (`UCI_TMO` ~5 s) then ABORT/EIO; never `sei` around a wait. No kernel IRQ path touches
  `$DF1x` (VERIFIED: no `$DF1` in `src/kernel`).
- **DMA**: none on the byte path; the fast path's fetch halts the CPU ~1 ms/KB: cap at 8 KB per fetch.
- **REU overlay**: our REU code uses `$DF00-$DF0A` only (`blk.s:9-18`, VERIFIED). A real REU mirrors every 32 bytes, so `$DF1B-$DF1F`
  read unused registers (`$FF`) and the probe fails cleanly; a stock C64's open bus can read `$C9`, hence three reads plus IDENTIFY, at
  mount only.
- **Turbo**: nothing is cycle-counted; register speed at 48 MHz unknown (Q9); turbo stays off.
- **1541 stall**: unrelated (measured: same rate with the interface off); v1 sends nothing on IEC, and the umount branch keeps
  `iec_close` off dev 5.
- **Other UCI users**: no user program may touch `$DF1x` while `/u` is mounted; the experiment tools reset the machine first.

## 9. Open questions -> measurements

| Q | Question | Item | Decides |
|---|---|---|---|
| Q1 | Read rate with the 21-cycle loop; `$DF1C` bit 7 DMA mode | extends throughput | read-ahead size; whether exec needs the fast path |
| Q2 | CHANGE_DIR with an absolute path? FILE STAT relative after it (absolute gave `82`)? | new | probe by CD+STAT (no eviction) or OPEN+INFO |
| Q3 | OPEN-for-write of an existing file; small WRITE_DATA latency | extends latency | keep or cut write-behind; switch cost |
| Q4 | mkdir existing, rmdir non-empty, DELETE of a dir, delete missing, disk full, rename onto existing | extends errors | error table, rmdir |
| Q5 | READ_DIR packets, `.`/`..`, ABORT mid-listing | new | readdir |
| Q6 | When a drive-modified image reaches its host file | write-back | `.d64` rule; F8 |
| Q7 | LOAD/SAVE REU beyond 32 KB, near the end of a 2 MB REU | not tried | fast-path safety |
| Q8 | Host root layout (`/Temp`, USB, SD names) | get path | `mount uci /u [hostdir]` |
| Q9 | UCI registers under turbo | new | turbo with UCI |

Settled by measurement: poll, not IRQ; two slots (targets independent); packets as Data More chains; network target present, out of
scope.

## Addendum (2026-10-31): corrected and added measurements

From the hardware session (C64 Ultimate, firmware 1.1.0, polled; source: the entry "CORRECTION to the throughput above" in `docs/hardware-notes.md` on `hw-bench`). They supersede the 16 KB/s and 21 KB/s figures used earlier in this note, which were bound by the measuring loop (a `jsr` to a store routine per byte), as the note's Q1 suspected.

| Item | Measured |
|---|---|
| Read, DATA_AV tested on every byte (`lda $DF1C / bpl / lda $DF1E / sta page,y / iny / bne`, ~20 cycles) | 44.0-44.8 KB/s, same for requests of 512 / 4096 / 32768 |
| Read, no status test (512 bytes per chunk blind, ~14 cycles) | 61.6-63.3 KB/s; each chunk handshake costs ~0.2 ms |
| LOAD REU (file open for read first) | 32 KB 6.2 ms; 128 KB 13.7 ms (9.6 MB/s); 512 KB 44.4 ms (11.8 MB/s) |
| Create (open for write, create-always, flag $0A) | 54.8-55.7 ms; overwrite the same; flag $0E answers FILE EXISTS; close 1.1 ms |
| CHANGE DIR /Temp | works, 7.8 ms; GET PATH then returns /Temp/ |
| OPEN | accepts an absolute path |
| FILE STAT ($08) | answers 82,FILE NOT FOUND for any name: use OPEN + FILE INFO (4.9 ms, 22-byte stat packet) |
| Write throughput | 21 KB/s was measured with the same slow loop; probably also loop-bound, not yet re-measured |
| DMA bit ($DF1C bit 7) for reads | not tried |

Consequences for the design:
- **The v1 byte path is comfortably enough**: design for ~44 KB/s (safe), ~62 KB/s blind. A 6.4 KB program (`as`) loads in roughly 0.15 s through the registers, so Q1's "LOAD REU is not in v1" holds with more margin than assumed. LOAD REU remains the right tool for bulk (REU cache fill, overlays, swap staging) at 10x or more the byte path.
- **Creating a file is slow** (about 55 ms against 4.5 ms for an open): workloads that create many small files (compiler temporaries, `mkdir` trees) will notice. Prefer keeping a created handle open over reopening, and do not create-per-write.
- **Absolute paths on OPEN** confirm the whole-path resolution design (section 3): the kernel strips the mount prefix and passes one host path, no per-component walk needed. `stat` goes through OPEN + FILE INFO; there is no cheap stat-by-name.
- Q1, and the open-for-write and absolute-path questions listed in section 9, are now answered; image write-back timing, the DMA read bit and a write-throughput re-measure remain open.
