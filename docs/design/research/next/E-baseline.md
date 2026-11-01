# E-baseline: quantitative baseline (lens E, measurements only)

Method. Footprint tip (branch `footprint`, tip a9b6acf, copied and built with `make`; REU cache default on) is "FP"; main-branch HEAD via `git archive` (no lib split, no INIT segment, pool edge $8000) is "MAIN". Sizes: `ld65 -m` maps of each program relinked at origin 0 plus `make size`. Cycles: ca65 `-l` listings give the real opcode of every instruction on the path; a 6502 base-cycle table maps opcode to cycles; I chose the path (line numbers cited) and branch outcomes by hand. Taken branch +1; page-cross penalties ignored (adds <1%). All figures VERIFIED (read and computed) unless marked. Clock 985,248 Hz (PAL); a PAL frame is 19,656 cycles. Helper scripts live in the scratchpad, not the repo.

## (a) Per-program size and library duplication (FP)

Library = objects pulled from `build/lib/breadbin.lib` (err, input, lib, num, target, passwd). Own = the program's `.o`. Sizes in bytes; "image" = CODE+RODATA+DATA; the BSS is allocated at exec time and is not in the CX file.

Totals over 40 programs (FP) vs 39 programs (MAIN; `cache` is new in FP):

| metric | FP | MAIN |
|--|--|--|
| own code+rodata+data, all programs | 18,086 | 17,755 |
| library code+rodata, summed over programs | 27,551 (60% of image bytes) | 42,854 (71%) |
| one resident copy of each lib object linked anywhere | 1,587 | 1,587 |
| duplicated lib bytes (sum minus one copy each) | 25,964 | 41,267 |
| lib BSS summed (allocated per process, not on disk) | 3,514 | 11,150 |

FP lib objects (size incl. code+rodata; times linked): err 609 (24 progs; of it RODATA 494 error strings), lib 158 (all 40), num 200 (21), input 94 (10), target 103 (2), passwd 423 (3). Every program pays lib.o (158 B) plus its 1 B BSS; a program that prints an error pays 609 B for err.o (494 B of it message strings, `src/lib/err.s:74-147`). MAIN: a single lib.o of 1,061 B image + 267 B BSS in every program.

Full per-program table is in (b) (own and lib split are columns 2-5).

## (b) CX size, relocations, blocks, compressibility (FP, all 40 programs)

Block = 256 B (c64fs, `tools/mkimage.py:92`), NDIRECT=12 so files over 3,072 B add one indirect block (`mkimage.py:66`); blocks column = ceil(size/256) (+1 if over 12). Compression: zlib level 9 and raw LZMA2 preset 9 of the whole CX file (header+image+reloc table).

| prog | own C+RO+D | own BSS | lib C+RO | lib BSS | lib % image | reloc | CX B | blk | zlib9 | lzma | zlib % |
|--|--|--|--|--|--|--|--|--|--|--|--|
| as | 4119 | 14401 | 1061 | 267 | 20% | 593 | 6375 | 26 | 4513 | 4185 | 70% |
| basic | 3399 | 8700 | 861 | 260 | 20% | 570 | 5409 | 23 | 4007 | 3742 | 74% |
| cache | 331 | 9 | 967 | 8 | 74% | 93 | 1493 | 6 | 1126 | 1102 | 75% |
| cat | 101 | 256 | 767 | 1 | 88% | 57 | 991 | 4 | 740 | 736 | 74% |
| clear | 5 | 0 | 158 | 1 | 96% | 10 | 192 | 1 | 179 | 179 | 93% |
| count | 32 | 0 | 358 | 8 | 91% | 23 | 445 | 2 | 403 | 410 | 90% |
| cp | 128 | 256 | 870 | 74 | 87% | 74 | 1155 | 5 | 877 | 862 | 75% |
| date | 287 | 4 | 158 | 1 | 35% | 49 | 552 | 3 | 464 | 442 | 84% |
| df | 195 | 46 | 358 | 8 | 64% | 55 | 672 | 3 | 577 | 558 | 85% |
| echo | 33 | 0 | 158 | 1 | 82% | 14 | 228 | 1 | 215 | 210 | 94% |
| edit | 1470 | 12371 | 158 | 1 | 9% | 231 | 2099 | 9 | 1603 | 1574 | 76% |
| format | 906 | 313 | 967 | 8 | 51% | 175 | 2232 | 9 | 1695 | 1640 | 75% |
| free | 199 | 9 | 358 | 8 | 64% | 52 | 670 | 3 | 567 | 571 | 84% |
| grep | 306 | 258 | 1061 | 267 | 77% | 102 | 1580 | 7 | 1246 | 1227 | 78% |
| head | 85 | 0 | 1061 | 267 | 92% | 84 | 1323 | 6 | 1032 | 1020 | 78% |
| help | 67 | 256 | 767 | 1 | 91% | 53 | 949 | 4 | 707 | 705 | 74% |
| hexdump | 178 | 9 | 1061 | 267 | 85% | 104 | 1456 | 6 | 1121 | 1106 | 76% |
| init | 298 | 138 | 767 | 1 | 72% | 83 | 1240 | 5 | 927 | 904 | 74% |
| kill | 144 | 0 | 967 | 8 | 87% | 68 | 1256 | 5 | 976 | 960 | 77% |
| login | 323 | 34 | 875 | 464 | 73% | 137 | 1481 | 6 | 1172 | 1174 | 79% |
| ls | 474 | 105 | 967 | 8 | 67% | 114 | 1678 | 7 | 1294 | 1278 | 77% |
| mkdir | 93 | 0 | 767 | 1 | 89% | 54 | 977 | 4 | 731 | 728 | 74% |
| more | 130 | 8 | 861 | 260 | 86% | 78 | 1156 | 5 | 888 | 872 | 76% |
| mount | 296 | 35 | 967 | 8 | 76% | 96 | 1464 | 6 | 1099 | 1087 | 75% |
| mv | 88 | 0 | 870 | 74 | 90% | 69 | 1105 | 5 | 835 | 825 | 75% |
| passwd | 667 | 90 | 1484 | 464 | 68% | 219 | 2598 | 11 | 1930 | 1861 | 74% |
| ps | 143 | 16 | 358 | 8 | 71% | 40 | 590 | 3 | 507 | 505 | 85% |
| pwd | 23 | 64 | 158 | 1 | 87% | 13 | 216 | 1 | 200 | 198 | 92% |
| rm | 90 | 0 | 767 | 1 | 89% | 54 | 974 | 4 | 729 | 727 | 74% |
| rmdir | 93 | 0 | 767 | 1 | 89% | 54 | 977 | 4 | 730 | 728 | 74% |
| sh | 2109 | 1284 | 967 | 8 | 31% | 428 | 3941 | 17 | 3081 | 2926 | 78% |
| sleep | 75 | 0 | 358 | 8 | 82% | 25 | 492 | 2 | 446 | 446 | 90% |
| stat | 238 | 8 | 967 | 8 | 80% | 90 | 1394 | 6 | 1052 | 1039 | 75% |
| theme | 383 | 22 | 158 | 1 | 29% | 36 | 622 | 3 | 485 | 480 | 77% |
| umount | 68 | 0 | 767 | 1 | 91% | 53 | 950 | 4 | 696 | 698 | 73% |
| uname | 79 | 0 | 158 | 1 | 66% | 14 | 274 | 2 | 250 | 251 | 91% |
| uptime | 182 | 15 | 358 | 8 | 66% | 58 | 665 | 3 | 567 | 579 | 85% |
| version | 44 | 0 | 158 | 1 | 78% | 11 | 233 | 1 | 221 | 218 | 94% |
| wc | 173 | 2 | 1061 | 267 | 85% | 99 | 1441 | 6 | 1135 | 1124 | 78% |
| whoami | 32 | 1 | 875 | 464 | 96% | 111 | 1138 | 5 | 937 | 944 | 82% |
| TOTAL | 18086 | 38710 | 27551 | 3514 | | 4343 | 54683 | 233 | 41960 | 40821 | |
## main 39

MAIN total row for comparison: `| TOTAL | 17755 | 38701 | 42854 | 11150 | | 5576 | 72112 | 306 | 54973 | 53439 | |` (same column order; 39 programs).

Findings.
- Relocation table = 2 bytes x 4,343 relocs = 8,686 B = 15.9% of all CX bytes (FP; MAIN 5,576 relocs, 11,152 B, 15.5%). Of the 4,343 offsets, 4,340 are within 255 of the previous one (sorted order): a delta-byte encoding would be 4,349 B, saving 4,337 B (7.9% of CX bytes, 17 disk blocks if packed). Computed by script over `build/root/bin/*`.
- General-purpose compression saves only 23% (zlib 41,960 of 54,683; lzma 40,821 = 25%): this is dense 6502 code; most of the win comes from the sorted reloc table and from repeated lib code (compressors run per file, so they do not see cross-program duplication).
- Load cost of relocation: `relocate` loop `src/kernel/exec.s:255-269` = 49 cycles per reloc (4+3+4+2+3+3+2+5+2+3+6+2+2+5+3), so `sh` (428 relocs) = 21.0k cycles, the average program (109 relocs) = 5.3k cycles, plus the `fs_read` of 2 B/reloc.
- Disk: FP 233 blocks for all 40 programs; MAIN 306 for 39. Image `make` reports 334 free blocks (FP) vs 263 (MAIN).

## (c) Cycle counts

Path notation: lines are of the named source file at the FP tip.

**c1. getpid round trip** (`include/breadbin.inc:12` SYS_GETPID is slot n=4; `src/kernel/jtab.s`, `src/kernel/proc.s:502-506`):

| step | lines | cycles |
|--|--|--|
| user `jsr SYS_GETPID` + table `jsr enter` | jtab.s:14-16 | 6 + 6 = 12 |
| enter prologue (sei, cld, save A/X/P, pull return addr) | jtab.s:21-30 | 28 |
| n-by-subtract loop: 5 passes of inx/sbc/bcs, 4 taken (7 each), last 6 | jtab.s:31-33 | 34 (= 7n+6) |
| build return frames, restore regs, cli, rts into handler | jtab.s:34-53 | 62 |
| handler: ldx cur, lda p_pid,x, clc, rts | proc.s:503-506 | 3+4+2+6 = 15 |
| sys_return: php/sei/pha/txa/pha | jtab.s:56-60 | 19 |
| jsr check_signal (ldx 3, lda 4, beq taken 3, rts 6, +jsr 6) | jtab.s:61, proc.s:204-209 | 22 |
| need_resched test (zp), taken | jtab.s:62-63 | 6 |
| epilogue: lda #0/sta in_kernel, pla/tax/pla/plp/rts | jtab.s:68-74 | 25 |
| **total** | | **217 cycles = 220 us** |

Generic syscall overhead excluding the handler = 174 + 7n cycles (write n=10: 244; read n=9: 237). Reschedule on return adds a `sched` (c2) plus a second check_signal.

**c2. Context switch** (`sched`, `src/kernel/proc.s:91-175`; `slot_save_ptr` 55-88). Let d = bytes of stack saved (= $FF - SP at `tsx`), d' for the incoming process.

| part | cycles |
|--|--|
| prologue + state tests + tsx/overflow test (92-105, bcs taken) | 32 |
| 109-111 + `jsr slot_save_ptr` (6 + 86 incl. rts) + ldy | 11 + 94 = 105 |
| save ZP $02-$3F: 62 iterations x 16/17 cycles (114-118; `lda $02,y` assembles as abs,y, 4 cycles) | 1,053 |
| ldx tmp2 | 3 |
| save stack: d x 18 +taken branches (120-125) | 19d - 1 |
| pick, next slot ready (127-140): 8+2+16; each extra probe +20 | 26 |
| found: stx/slice + slot_save_ptr jsr (155-158) + ldy | 100 + 2 = 102 |
| restore ZP: 62 x 16/17 (160-164) | 1,053 |
| lda p_sp,x/tax/txs (165-167) | 8 |
| restore stack: d' x 18 + taken (168-173) | 19d' - 1 |
| plp, rts (174-175) | 10 |
| **total** | **2,390 + 19(d + d')** |

Examples (PAL): d=d'=16 -> 2,998 cycles (3.0 ms, 15% of a frame); d=d'=64 -> 4,822; maximum d=d'=130 (STKSAVE, `k.inc:16`) -> 7,330 (7.4 ms). The fixed ZP save/restore is 2,106 cycles = 88% of the 2,390 floor (34 cycles per ZP byte per switch). With SLICE=3 ticks (`k.inc:20`, 58,968 cycles), a switch at d=16 costs 5.1% of CPU while two or more processes are ready. Each additional non-ready slot scanned in `@n` adds 20.

**c3. Per-tick IRQ**, one running user process, no key down, no sleepers, 12 slots none blocked (`src/kernel/main.s:213-232`, `proc.s:231-301`):

| item | lines | cycles |
|--|--|--|
| hardware IRQ sequence 7 + irq_entry (B-flag test) | main.s:214-223 | 7 + 26 = 33 |
| cld, ack CIA | proc.s:232-233 | 6 |
| `kbd_scan` (jsr 6 + 837): jiffy 16, 8-line matrix scan with stability re-read 323, STOPRAW 15, modifiers 41, 8-byte mask loop 145, 8-byte new-key search 156, held/idle test 9, 8-byte prev copy + exit 132 | kbd.s:118-257 | 843 |
| inc ticks, bne taken | proc.s:235-236 | 8 |
| `con_cursor_tick` (cursor not toggling) | proc.s:240, con.s:83-96 | 6 + 27 = 33 |
| `wakeup(CH_TICK)`: 11 + 12 x 9 + 11 x 5 + 4 + 10, + lda/jsr 8 | proc.s:241-242, 212-228 | 196 |
| sleeper scan, 12 slots | proc.s:244-261 | 169 |
| RUN/STOP buffer + edge test, CH_KEY test | proc.s:263-283 | 6 + 11 + 6 = 23 |
| in_kernel/cur/p_sig tests, dec slice taken, jmp | proc.s:284-292, 301 | 29 |
| irq_exit (pla,tay,pla,tax,pla,rti) | main.s:227-232 | 22 |
| **total** | | **1,362 cycles = 6.9% of a PAL frame (8.0% NTSC, 17,045 cycles)** |

Per blocked process: +9 in the wakeup scan, +8 in the sleeper scan (+17; 12 blocked = +204). Every 16th tick the cursor toggles (cursor_show/hide, ~35 more, `con.s:52-80`). Slice expiry then adds c2.  `kbd_scan` is 62% of the tick; the two 12-slot table scans are 27%.

**c4. One console putc** (`con_putc`, lowercase letter, cursor hidden, ESC state 0, `src/kernel/con.s:100-146`, `to_screen` 348-373, `scr_put` 319-329): 198 cycles (+6 for the caller's jsr); with the cursor visible +29 (`cursor_hide` full path, 52-64). Breakdown: save regs/sei/inc/cursor_hide(hidden) 43, plp/tsx/fetch/esc test 16, compare chain for ESC/LF/FF/BS/TAB (115-133) 25, `to_screen` 47, `scr_put` 39, exit 28. A newline at the bottom row runs `scr_scroll` (con.s:282-302): 11,673 cycles (11.8 ms, 0.6 frame). Through `write(1,&c,1)` the same character costs additionally 244 (syscall) + `sys_write` dispatch + `con_write` loop (not counted here).

**c5. Pipe byte, one-byte write then one-byte read, no blocking** (`file.s:567-611, 614-705` write; `426-564` read):

| part | write | read |
|--|--|--|
| syscall overhead 174+7n (n=10 / 9) | 244 | 237 |
| `fd_get` (file.s:160-171: 53 incl. its fd_slot) | 59 | 59 |
| `sys_write`/`sys_read` flag + type dispatch (569-586 / 428-444) | 34 | 39 |
| pipe_write/pipe_read body: setup, space/count checks, copy loop 1 iteration (39), pointer advance, jsr wakeup 6 | 246 | 141 |
| `wakeup(CH_PIPE|i)` over 12 slots (212-228) | 188 | 188 |
| **total (244+339+188 / 237+239+188; handler paths 339 / 239 incl. fd_get and the wakeup jsr)** | **771** | **664** |

Round trip 1,435 cycles (1.46 ms) per byte through the syscall pair, of which 376 (26%) is the 12-slot `wakeup` scan done even when nobody sleeps on the channel. Marginal cost inside a bulk call: 39 cycles/byte each side (78 per byte round trip, ~12.6 KB/s ceiling), so a full 255-byte pipe write is ~10.7k and read ~10.6k cycles. If the reader was blocked add a switch (c2) each way.

## (d) Kernel modules and BSS

Bytes; FP: CODE (below $CF00), CODEHI (above BSS), INIT (boot-only, freed after boot), BSS. `make size`.

| module | FP code+ro | FP CODEHI | FP INIT | FP BSS | MAIN code+ro | MAIN BSS |
|--|--|--|--|--|--|--|
| proc | 990 | 0 | 16 | 3,315 | 1,006 | 3,315 |
| blk | 1,485 | 0 | 336 | 1,698 | 1,050 | 1,632 |
| file | 2,622 | 0 | 42 | 322 | 2,664 | 322 |
| fs | 2,207 | 0 | 360 | 283 | 2,564 | 283 |
| cbm | 21 | 1,902 | 0 | 33 | 1,923 | 33 |
| exec | 1,213 | 0 | 0 | 160 | 1,213 | 160 |
| con | 1,222 | 0 | 42 | 99 | 1,264 | 99 |
| iec | 765 | 0 | 0 | 15 | 765 | 15 |
| kbd | 673 | 0 | 56 | 18 | 729 | 18 |
| main | 152 | 0 | 269 | 0 | 418 | 0 |
| mem | 159 | 0 | 19 | 158 | 178 | 125 |
| jtab | 0 (in the $CF00 page, JUMPTAB seg) | 0 | 0 | 0 | 371 | 0 |
| **total** | **11,509** | **1,902** | **1,140** | **6,101** | **14,145** | **6,002** |

FP: code+data end at $CDF4, 267 B left below $CF00; BSS+CODEHI end at $FF42, 183 B left below $FFFA. MAIN: 6,079 B and 2,184 B left. The user pool edge moved from $8000 (KSTART, MAIN `k.inc:4`) to $A100 (FP `k.inc:4`), +33 pages, so FP pool is $0800-$A0FF = 38,656 B vs 30,720 B.

Largest BSS items (FP, from `.res` and label gaps in `build/kernel.lbl`): `p_save` 2,304 (12 x 192, `proc.s:30`) = 37.8% of BSS; `bufs` 1,536 (6 x 256, `blk.s:42`); `p_cwd` 576 (12 x 48); `pg_used` 153 (page table, `mem.s:10`); `p_name` 132; `rbuf` 128 (`exec.s:27`); `mt_path` 128 (4 x 32, `fs.s:34`); `p_fd` 96 (12 x 8). The other ~1,050 B are 1-18 B scalars and per-device/per-file tables (NFILE=24 x 9 arrays = 216 B in `file.s:10-18`, `proc.s` 17 per-slot arrays = 204 B).

## (e) Device-type and file-type branches (FP)

Reads of `dev_type` that branch (c64fs vs CBM DOS), 11 sites: exec.s:107; fs.s:224, 255, 879; file.s:232, 262, 456, 832, 959, 1036, 1331. Setters/reporters: cbm.s:760, 779, 955 (set), cbm.s:985 (stat report), blk.s:654 (REU device init). Other device-number special cases: blk.s:213 and 282 (`cmp #1 ; beq @reu`, dev 1 = REU), blk.s:677-678 and 793-794 (`lda rq_dev ; bne` cache applies to dev 0 only). `dev_present`/`dev_drive` are table lookups, not branches (blk.s 126-162, cbm.s 561-1008; 14 references in cbm.s). Open-file-type (`f_type`) compare chains: file.s:102-110, 319, 435-445, 459, 576-590 = 16 `cmp #FT_*`; cbm.s:929-933 = 3. Cross-module calls into cbm.s from file/fs/exec: 13 (`file.s` 109, 234, 264, 387, 402, 461, 462, 589, 962, 1039, 1334; `fs.s` 226, 881). Dev-type dispatch branches by file: blk 4, fs 3, file 7, exec 1, cbm 0 (it is the target); FT_* compare lines: file 16, cbm 3. Total device-dispatch sites in the five files: 15 dev branches (11 `dev_type` + 4 blk), 19 FT compares.

## (f) Zero page map ($02-$8F = 142 bytes)

| range | bytes | owner | cite |
|--|--|--|--|
| $02-$07 | 6 | r0-r2 syscall args | `include/breadbin.inc:42-44` |
| $08-$09 | 2 | r3 (kernel) | `k.inc:63` |
| $0A-$13 | 10 | s0-s4 kernel scratch pairs | `k.inc:64-68` |
| $14-$1B | 8 | sb0-sb7 kernel scratch bytes | `k.inc:69-76` |
| $1C-$1D | 2 | no static reference (free; saved per process) | grep |
| $1E-$1F | 2 | k_entry (exec entry vector) | `k.inc:77`; `jmp (k_entry)` in `proc.s` proc_entry |
| $20-$22 | 3 | argv (2), argc | `breadbin.inc:47-48` |
| $23-$2F | 13 | program-private (`prog.cfg` ZP start $23 size $0D); programs actually define up to $2E (basic `mq=$2D`, 2 B); $2F no program | `prog.cfg:3`, per-program `= $xx` equates |
| $30-$3B | 12 | library: lp1-lp3 $30-$35, lt0-3 $36-$39, lval $3A-$3B | `src/lib/lib.inc:2-9` |
| $3C-$3F | 4 | no static reference (free; saved per process) | `ZPSAVE=$3E` saves $02-$3F |
| $40-$5E | 31 | kernel ZEROPAGE: bp 40, fb 42, pp 44, cur 46, in_kernel 47, need_resched 48, slice 49, ticks 4A-4C, p1-p4 4D-54, k_a 55, k_x 56, k_n 57, k_p 58, tmp0-3 59-5C, stop_prev 5D, intr_pending 5E | `build/kernel.lbl`; segment decl main.s:8, blk.s:37, fs.s:11 |
| $5F-$8F | 49 | reserved by `kernel.cfg` ZP ($40, size $50) and unreferenced | `kernel.cfg:8`; roadmap says 48 ($60-$8F), actual 49 |

Statically free in $02-$8F: $1C-$1D (2), $2F (1), $3C-$3F (4) = 7 inside the per-process saved region, plus $5F-$8F (49) outside it = 56 bytes. The per-process-saved region ($02-$3F, 62 B) costs 34 cycles per byte per switch (c2). Stock addresses the kernel touches directly: $01 (main.s:83), $90 ST (defined `k.inc`), $91 stop key (proc.s:271, kbd.s:36), $A0-$A2 jiffy (kbd.s:37), $BA (blk.s:95), $C5/$C6/$CB keyboard (kbd.s:33-35), $C7 reverse, $D1-$D3, $D6 screen (con.s:57-341), $FB-$FE boot copy (main.s:44-92, INIT only).

## (g) SYS_ call sites (static, `jsr`/`jmp`/references; src/bin incl. `as_ops.inc`, src/lib)

| syscall | bin | lib | total | programs using |
|--|--|--|--|--|
| EXIT | 47 | 2 | 49 | 19 |
| CLOSE | 18 | 1 | 19 | 10 |
| READ | 17 | 1 | 18 | 14 |
| OPEN | 14 | 2 | 16 | 8 |
| WRITE | 12 | 3 | 15 | 7 |
| WAIT | 7 | 0 | 7 | 4 |
| STAT | 5 | 1 | 6 | 4 |
| CONMODE | 6 | 0 | 6 | 3 |
| SPAWN | 5 | 0 | 5 | 4 |
| SLEEP | 4 | 0 | 4 | 4 |
| KILL, RENAME, CHDIR, GETCWD, PROCINFO, MEMINFO, ISATTY, MNTINFO, DISKIO | 3 each | 0 | 3 | 1-3 |
| GETPID, PIPE, MKDIR, RMDIR, UNLINK, FSINFO, TIME, GETUID | 2 each | 0 | 2 | 2 |
| YIELD, SETUID, MOUNT, UMOUNT, CACHE | 1 each | 0 | 1 | 1 |

183 call sites in bin, 10 in lib (193 total) over 33 syscall slots (32 used of NSYS=32, `jtab.s:11`). READ+WRITE+OPEN+CLOSE+EXIT = 117 of 193 (61%). Zero call sites: none (every slot has at least one). The table has no slot to spare: `NSYS=32` and 32 entries are defined.
