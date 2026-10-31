# Lens D: console/UX contract and a "Cooler Operating System"

Code base: footprint tip `a9b6acf` (worktree `.claude/worktrees/reu-cache`), built in a scratch copy. V = VERIFIED (read or ran), U = UNVERIFIED (inferred, or from docs not code).

## 1 Executive summary

1. **Every kernel byte now costs TPA page for page.** `make size` on the tip: 267 bytes free below `$CF00`, 183 below `$FFFA`; the pool is `$0800–$A0FF` (V, run). A console feature in the kernel costs 1 page of the 153-page pool per 256 bytes. So the rule is: the kernel gets the hooks and the shared state, and everything else goes into user space.
2. **The cooked line editor is already in the kernel** (`con_read`, con.s:592-674, V), and `sh`, `basic`, `more` and `login` all read through it. Adding history and cursor editing there (~300 B of code plus a 256 B buffer) upgrades every program at once. Best wow per byte for typing.
3. **The syscall page is nearly full**: 14 bytes left in `$CF00–$CFFF`, enough for 2 more syscalls (V, map). Make the first contract change a multiplexed `SYS_CTL` (ioctl-style), so console, timer and hook features don't each need a slot.
4. **Cheapest big wins (Classic tier):** termios-lite mode bits, an alternate screen (save/restore for `edit`/`more`), a status line with the TOD clock, a screen blanker (+5% CPU), and a **tick hook** so a background process can play SID music. Together that is about 0.9–1.2 KB of kernel, 4–5 TPA pages.
5. **Top-down page allocation** (about 10 bytes) keeps VIC bank 0 (`$0800–$3FFF`) free most of the time. That makes SID tunes at `$1000`, a RAM charset, bitmaps and extra screens claimable with no kernel memory model change.
6. **Virtual consoles are cheap in the kernel (~450 B) but expensive in TPA.** Each extra console needs its own shell, about 5 KB, because CX has no shared text. Ship 2 consoles first; 4 consoles want shared text (a CX contract change) or REU swap.
7. **Ultimate features go in user space** (`uci`, `turbo`, `wget`, time sync) behind one serialised UCI transaction op, so Classic never pays. Turbo is already measured: CPU-bound BASIC is 51x faster at 48 MHz (hardware-notes.md:126, V as recorded).
8. **Do not do:** an ANSI/VT100 parser in the kernel, ptys, an 80-column bitmap console in the kernel, SID or mouse as kernel devices.
9. **Recommended first "breadbin-next" demo:** SYS_CTL, termios-lite, line editor with history, alt screen, status line with clock, tick hook with `play`, blanker, plus `turbo`/`uci time` on the Ultimate. About 2 weeks, about 1.3 KB of kernel (5–6 pages, pool 39.2 KB to 37.7 KB).
10. **Flag for S14 (the compiler):** the console cannot show `{ } ~` (they print as `?`) or `` ` `` (dropped) (con.s:359-365, V). A C-like language needs a RAM charset (2 KB of TPA), and this should be decided before S14.

## 2 Current-state findings that matter

| Finding | Cite | V/U |
|---|---|---|
| Internally ASCII; output goes straight to `$0400`, lowercase ROM charset (`$D018` bit 1) | con.s:3-8, 36-38 | V |
| One colour for the whole screen; `ESC C fg bg border` rewrites all 1000 colour cells | con.s:207-213, 245-254 | V |
| Escapes: `ESC = r c` (+32), `ESC R`/`r` reverse, `ESC K`, `ESC C`. No scroll region, no insert/delete line, no save/restore, no geometry query | con.s:148-239 | V |
| Glyph losses: `[ \ ] ^` map to the screen codes for `[ £ ] ↑`; `_` is `$64`; `{ } ~` print `?`; `` ` `` is dropped | con.s:348-381 | V |
| Cooked input: only RETURN, DEL and ^D. Cursor keys are dropped (`to_ascii` gives 0 for `$91/$11/$9D/$1D`). Line max 79 | con.s:11, 614-628, 466-498 | V |
| Raw mode is one global (`con_raw`, `raw_pid`); `sys_conmode` keeps only bit 0 (`and #1`), so the other bits are free for new modes | con.s:26-27, 394-405 | V |
| Raw codes: `^P ^N ^B ^F ^A ^L ^H $0A`, F-keys `$85–$8C`, ctrl-letters `$01–$1A` | con.s:676-723; breadbin.inc:97-110 | V |
| Scroll costs about 12.5k cycles (3×256 copies at ~35 cyc/iter + 192×~15 + clear) | con.s:281-302 | V code; U cycles |
| IRQ: CIA1 tick (rate left as the KERNAL set it; programs assume 60/s), keyboard scan, cursor blink, sleeper wake, RUN/STOP sends SIGINT to every non-BG, non-IGNINT process (no process groups, no tty ownership) | proc.s:231-330; uptime.s:5; sleep.s:16 | V; tick rate U |
| Signals are all fatal: `check_signal` does `ora #$80` then `proc_exit`. No handlers, no stop/continue | proc.s:202-209 | V |
| Pipe = 1 page, 8-bit count, NPIPE=4 | file.s:19-25, 718-727; k.inc:8 | V |
| sh: pipelines, `< > >>`, `&`, `;`, quotes, `#`, globbing, built-ins cd/exit/kill/jobs, scripts, `[pid] done` reaping. No history, PATH, variables, `$?`, fg/bg, or control flow. Command path hard-coded to `/bin/` | sh.s:1-10, 142-161, 843-870 | V |
| `edit` redraws all 24 rows after every key and clears the screen on exit (the shell's screen is lost). It hard-codes ROWS 24 / COLS 39 | edit.s:8-9, 14-15, 110-114, 139-141 | V |
| `more` hard-codes 22 rows and 40 cols | more.s:4, 35 | V |
| `login`/`passwd` have their own raw-mode loops to echo `*` | login.s:91-131; passwd.s:216-243 | V |
| `date` already uses the CIA1 TOD clock, which keeps time while interrupts are off (the jiffy clock stops during formats) | date.s:1-8; roadmap M0-4 note | V |
| init: theme, then motd, then login or sh; `/etc/help` and `help` exist | init.s:1-60; rootfs/etc | V |
| First-fit page allocation from page `$08` upward, so programs fill VIC bank 0 first | mem.s:29-50 | V |
| Syscall page: table 32×3 + enter/return + 2 address tables = `$CF00–$CFF1`; 14 B left, 5 B per new syscall | jtab.s:10; kernel.map | V |
| Room: KRAM 267 B, KHI 183 B; con module is 1156 B of code | `make size` (run) | V |
| UCI not yet exercised from the C64; `$DF1D` reads `$C9` by DMA | hardware-notes.md:28 | V (as recorded) |

## 3 Proposals

Costs: "K" = kernel bytes, which are TPA bytes; "P" = pages taken from the pool when the feature is used.

### LOW (days, clear win)

**[D1] `SYS_CTL` multiplexer** | all tiers | Avoids running out of syscall slots; one place for console, timer and hook ops | K ≈ 5 B in the page + ~30 B dispatch; 0.5 day | New syscall number 32, `A = op`; nothing old breaks | none | trivial | host build; a smoke test that calls op 0 (version)

**[D2] termios-lite: mode bits in `SYS_CONMODE`** | all | bit0 raw (as today), bit1 no-echo (cooked password entry, so login/passwd can drop their loops, about −150 B of user code), bit2 timed read (X = ticks; raw read returns `r1=0` on timeout, so games, `top` and clocks can poll without spinning), bit3 TAB ends a cooked read (completion hook), bit4 ISIG off (RUN/STOP arrives as `$03`, for editors) | K ≈ 70 B. The timed read blocks on `CH_TICK` and checks the deadline, reusing `p_wk0-2` (proc.s:25-27): it wakes every tick only while such a reader exists | Bits 1-4 are ignored today (con.s:395), so old binaries are unaffected; breadbin.inc gains `CM_*` | — | low | test_console: noecho, timeout returns 0 bytes, TAB break

**[D3] Console geometry and capability query** (`SYS_CTL` op) | all | Returns rows, cols, first usable row, and flags (status line, alt screen, colour pen, REU-backed). `edit` and `more` stop hard-coding 24/39/22/40, which makes the status line, a soft-80 mode and smaller windows possible later | K ≈ 20 B; 0.5 day plus edit/more edits | edit.s, more.s change | D1 | low | edit/more tests unchanged

**[D4] Kernel line editor with history** | all (buffer from a pool page on Classic, REU later) | LEFT/RIGHT with insert, DEL mid-line, HOME/^A, ^E, ^U, UP/DOWN through a 256 B NUL-separated ring. **sh, basic, more, login all gain it for free** | K ≈ 300 B code + 256 B ring (2.2 pages); 2–3 days. Cost per key: redrawing the tail of the line is at most 79 `con_putc`, about 10k cycles (U) | Cooked mode becomes "readline". Programs that relied on cursor keys being ignored: none found (V, grep). Per-console history if D11 lands | D2 (bit for "no history" in password reads) | Medium: lines that wrap across rows near row 24 scroll during the redraw, so cursor arithmetic must use `$D6` after the redraw, not before. Test it at the bottom row | test_console: type, left×3, insert, return; up recalls; a wrapped line at row 24

**[D5] Alternate screen (save/restore)** | Classic: 4 pool pages taken while active; Expanded: 1000 B by DMA to a reserved REU bank | `ESC S` saves screen, cursor, `$C7` and colour; `ESC s` restores. `edit`/`more`/`help` return to the shell's screen intact, and a crashed full-screen program is restored by `con_release` on exit (con.s:408) | K ≈ 110 B; copy 2×1000 B ≈ 18k cycles (~18 ms) Classic, ~2k cycles REU; 1 day | New escapes; edit.s:110-114 drops its clear | — | low; out of pages: ESC S fails silently and the program falls back to the clear it does today | test: `ls` then `edit` then ^X, and the `ls` output is still on screen

**[D6] Status line with clock** | all; time comes from TOD (Classic) or the UCI clock (Recommended, see D16) | Reverse-video row 0: `hh:mm:ss  tty1  97p free  reu  uci`. Updated from the IRQ when the TOD seconds change (8 cells, ~150 cyc/s). Shown only in cooked mode on the main screen; raw or alt-screen programs get all 25 rows, so `edit` is unaffected | K ≈ 160 B: make the scroll top variable (con.s:281-311 hard-code row 0/24), clamp `ESC =` to the window, and the formatter; 1–2 days | `ESC =` row 0 means the first usable row in cooked mode; D3 reports it | D3 | Medium: TOD reads must read hours first and tenths last (latch), done in the IRQ. U: whether `$DC0E` bit 7 (50/60 Hz TOD input) is set right on PAL; check on hardware | test_console: screen line 0 matches a time pattern; `clear` keeps it

**[D7] Screen blanker** | all | After N idle minutes, clear `$D011` bit 4; a key restores it (the first key is swallowed). Also a `SYS_CTL` "blank now" for long jobs: a blank screen has no badlines, about **+5% CPU** (25 badlines × 40 cycles = 1000 of 19656 cycles per PAL frame) | K ≈ 40 B (16-bit idle counter: 65535 ticks ≈ 18 min max); 0.5 day | none | — | low. Screen RAM is untouched, so the tests' DMA screen reads still work; default off under the test harness, or a long timeout | keybuf after a short timeout set by ctl

**[D8] Tick hook** | all | One global user callback called every tick from the IRQ, with an owner pid that is cleared in `proc_exit`. It enables a background music player, a sprite cursor, key clicks and visual effects, all in user space. Rule: the hook may not touch ZP `$02–$3F` (it belongs to the interrupted process); give it 4 documented bytes at `$8C–$8F` (unused BASIC area, roadmap "Zero page policy": allowed) | K ≈ 40 B (3 B state, `jmp (hook)` trampoline, exit cleanup); 1 day | New ctl op; ZP table gains `$8C–$8F` | D1 | Medium: a buggy hook hangs the machine, since there is no protection anyway. Hook time adds to IRQ latency; keep it under ~2k cycles and say so in the docs, and re-check against the IEC stall work (interrupt latency was ruled out per commit 120aee5, but any IEC work with interrupts on is still sensitive) | test: a hook that increments a counter; the process exits and the counter stops

**[D9] Top-down page allocation + page claim** | all | Programs are allocated from the top of the pool, which keeps `$0800–$3FFF` (VIC bank 0, outside char ROM `$1000–$1FFF`) free as long as possible. `SYS_CTL` "claim pages p..p+n" fails if they are taken. That gives PSID tunes at `$1000`, a RAM charset at `$3800`, bitmaps at `$2000` and extra screens | K ≈ 10 B (scan direction) + 35 B (claim); 0.5 day | none for relocatable CX (U: confirm nothing assumes low load addresses; tests that print `ps` addresses would change) | D1 | low | `free`/`ps` before and after; claim `$10` succeeds after boot

**[D10] `play` (PSID player) and `blank`/`ctl` commands** | all | `play tune.sid &`: claim the load range, call init, install the hook with its own 6:5 divider (60 Hz tick to 50 Hz PAL tune rate), sleep until killed. Zero kernel bytes beyond D8/D9 | 1 day, ~400 B user program | — | D8, D9 | Licence: ship no tunes in the repo (a tune's player belongs to its author); the user brings their own, or we write an original 30-second tune | VICE: SID register writes visible in the monitor; on hardware, listen

### MEDIUM (a week each)

**[D11] Virtual consoles (C= + 1..4)** | Classic: 2 consoles (the hidden one in 4 pool pages); Expanded: up to 4 | Per-console state (line buffer 80, cursor `$D1–$D3/$D6/$C7`, escape state, raw mode, pen, ~95 B) is swapped on switch and on any `con_write`/`con_read` from a non-visible console (~2k cycles per syscall when interleaving). The screen base becomes a variable, so background writes land in the backing pages. `p_tty` per process (12 B) is inherited at spawn; `sigint_fg` (proc.s:313) only hits the visible tty; `/dev/tty1..4` (inode minor) | K ≈ 450 B + 95 B × N; P = 4 per hidden console; 4–5 days | `/dev/console` means "my tty"; FT_CON gains a minor; `con_raw` becomes per tty | D5 (shares the save/restore code), D2 | **TPA is the real cost**: each console runs a shell of ~5 KB (sh 3941 B + ~1.2 KB BSS, sh.s:24-77), so 4 consoles take ~15 KB of 39 KB. Shared text (CX with split text/data relocation bases) would cut that to ~1.3 KB per shell; flag it to the memory lens | test_keyboard: C=+2, type, C=+1, the screen comes back; SIGINT on tty2 leaves tty1 alone

**[D12] REU scrollback** | Expanded | Before each scroll, DMA row 0 (40 B) into a 64 KB ring: about 50 cycles of setup + 40 DMA cycles against the scroll's 12.5k, so +0.7%. C= + up/down shows the history (uses D5 save/restore); 1638 lines | K ≈ 200 B; one 64 KB bank taken from the `/tmp` RAM disk; 2 days | `/tmp` loses 64 KB | D5, REU bank reservation shared with the REU cache work | low | `seq` past 100 lines, scroll back, compare

**[D13] Tab completion** | all | sh sets CM_TAB; the read ends at TAB with the partial line; sh completes against cwd or `/bin` (reusing glob, sh.s:600) and preloads the editor buffer through a ctl op ("push text into lb") | K ≈ 30 B; sh ≈ 300 B; 2 days | none | D2, D4 | low | `ca<TAB>` gives `cat `

**[D14] Colour pen (opt-in per-cell colour)** | all | `ESC c fg` sets a pen and turns on colour RAM writes; scrolling then also moves colour RAM (12.5k to ~25k cycles per scroll). Coloured `ls` (directories), errors in red, the prompt in a theme colour. `ESC C` keeps its recolour-all meaning | K ≈ 90 B; 1–2 days | New escape; con.s header contract | — | low | test_console reads colour RAM by monitor

**[D15] Job control** | all | ^Z sends SIGTSTP (kernel special case: state PS_STOPPED, not fatal), `fg`/`bg` in sh, `wait` reports stopped children. With D5, `edit` → ^Z → shell → `fg` comes back to an intact editor screen | K ≈ 200 B; sh ≈ 250 B; 3–4 days | `wait` status gains "stopped"; new signals 18/20 | D11 if per-tty | medium (wait/zombie paths) | edit, ^Z, `ls`, `fg`, text still there

**[D16] Ultimate as user-space commands** | Recommended; on Classic each command prints "no ultimate" | `uci` (WP1, hardware session), `turbo` (already measured), boot-time `date -u` sync from the UCI DOS get-time into TOD, then `wget url > file` and `nc` over the network target `$03` (U: present on C64 Ultimate firmware 1.1.0? The documentation numbers firmware for U2/U64, roadmap.md:174-183). Kernel cost: one ctl op, "UCI transaction" (lock + push + drain), so user tools and the S10/S11 kernel backend never interleave | K ≈ 60 B on top of S10; tools 1–3 days each | none | S10 core | the hardware stall work holds the bench; network target untested | hardware run: `wget` of a small file, compared with the host

**[D17] RAM charset in ASCII order** | all | Copied at boot from the char ROM (at run time, never stored in the repo), with original glyphs for `{ } ~ \` | ^ _ \` and code = ASCII, so `to_screen` (con.s:348-381) mostly goes away (about −40 B K). Needed for S14 braces | P = 8 (`$3800–$3FFF`, needs D9); 1–2 days | Screen codes change for anything poking screen RAM directly (tests read the screen through a translation table, tools/vicetest.py, U) | D9 | medium: test screen decoding | test_console prints `{}~`

**[D18] sh niceties**: a `PATH`-like search (`/bin` then `~/bin`), `$?`, `user@cwd` prompt, `man` = `more /usr/man/x` (man pages on disk, or REU via S8) | all | user space, ~250 B; 2 days | none | — | low | scripts

### STRETCH ("cooler OS")

**[D19] Raster split** (status line in its own colour, or a bitmap top with text below) | all | ~60 B + raster IRQ source discrimination in `irq` (proc.s:231) | 3 days | — | D6 | Interacts with IEC timing: do it after the physical-1541 stall is understood

**[D20] Soft 80 columns** (4×8 font on a hires bitmap) | all | P = 36 (bitmap 8000 + screen 1000 in bank 0), font ~400 B, renderer ~400 B, scroll ~80k cycles (~80 ms) | 1–2 weeks | Needs D3 (programs query cols) | D3, D9 | as a loadable user-space "console server" only, never kernel-resident

**[D21] Shared text in CX** (two relocation bases) | all | Makes per-console shells, `play`, daemons and cron cheap (code once, data per instance) | memory/exec lens | CX format | — | high

## 4 Things I would NOT change, and why

- **No ANSI/VT100 CSI parser in the kernel.** It means numeric parameters, ~300 B, and nothing on the machine needs it. A future telnet client translates in user space.
- **No ptys.** They need a pipe pair, a terminal discipline in the kernel and a master daemon; the TPA cost of a second terminal emulator buys nothing that the vconsoles don't give.
- **No SID, joystick or mouse as kernel devices.** User code can poke `$D400` and read `$DC00`/`$DC01` (kbd_scan leaves `$DC00 = $FF`, kbd.s:157, V). Use the tick hook instead.
- **Keep the 60 Hz CIA tick as the clock contract.** `sleep` and `uptime` hard-code 60 (sleep.s:16, uptime.s:5). A raster tick at 50 Hz on PAL would silently change them; music handles 50 Hz with its own divider.
- **Keep the existing escapes**, and only add to them (`ESC S/s`, `ESC c`). The tests and every full-screen program rely on them.
- **Bigger pipes: not now.** Doubling to 2 pages saves about 15% of switch overhead (one switch, about 3k cycles, per 256 B against ~7.7k cycles of copying, U), but costs 16-bit counters across file.s. Low wow.
- **No cron daemon:** a resident ~2 KB process on a 39 KB machine for a feature nobody asked for.

## 5 Ranking

| ID | Kernel B | TPA pages | Days | Wow/byte | Wow/day |
|---|---|---|---|---|---|
| D8+D9+D10 music | ~85 | 0 (+tune) | 2.5 | ★★★★★ | ★★★★★ |
| D7 blanker | 40 | 0 | 0.5 | ★★★★ | ★★★★ |
| D16 turbo/uci time | ~0–60 | 0 | 1–2 | ★★★★★ | ★★★★ |
| D4 line editor | 300+256 | ~2.2 | 2.5 | ★★★★ | ★★★★ |
| D5 alt screen | 110 | 4 while used | 1 | ★★★★ | ★★★★ |
| D6 status clock | 160 | 0.6 | 1.5 | ★★★ | ★★★★ |
| D2/D3 modes | 90 | 0.4 | 1 | ★★★ (enabler) | ★★★ |
| D14 colour pen | 90 | 0.4 | 1.5 | ★★★ | ★★★ |
| D13 tab | 30 (+sh 300) | 0.1 | 2 | ★★★ | ★★ |
| D11 vconsoles | 450+ | 4 + ~20 per shell | 5 | ★★ | ★★★ |
| D12 scrollback | 200 | 0.8 | 2 | ★★★ (REU only) | ★★ |
| D15 job control | 200 | 0.8 | 3.5 | ★★ | ★★ |
| D17 charset | −40 | 8 | 1.5 | ★★ (needed for S14) | ★★ |

**First "breadbin-next" demo:** D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, plus D16 (`turbo`, `uci time`) on the Ultimate. Kernel about 1.3 KB, so lower `KSTART` by 5–6 pages (pool 39.2 KB to ~37.7 KB). Ordering: D1, then D2/D3, then D9 and D8, then D10 (music, which shows early). D4, D5 and D6 can run in parallel; D7 any time. Demo script: boot with a status clock synced from the Ultimate; `play tune.sid &`; up-arrow recalls `ls`; `edit` and ^X returns to the intact shell screen; `turbo 48; basic bench.bas`; walk away and the screen blanks.

Contract changes this demo makes: syscall 32 `SYS_CTL`; `SYS_CONMODE` bits 1–4; escapes `ESC S/s`; row 0 reserved in cooked mode; ZP `$8C–$8F` for the hook; top-down allocation. Each is additive, and old binaries behave the same except that they lose row 0 while the status line is on.

Tests: `test_console` and `test_keyboard` gain cases for each item (keybuf with PETSCII cursor codes); smoke before each commit. The hook and the blanker want one hardware run, because they change IRQ timing.

## 6 Open questions for the humans

1. The TPA trade: are 5–6 pages (about 1.4 KB of the 39 KB pool) for the console demo acceptable, given that S10/S11 (UCI backend) and the REU cache also want kernel room?
2. Status line: is it on by default (it costs row 0 in the shell), or an `/etc/rc`-style opt-in?
3. Vconsoles: are 2 enough, or is 4 the goal? If 4, shared text in CX (D21) moves up the memory lens's list.
4. The compiler track: is S14 committed to braces? If so, D17 (RAM charset, 8 pages) is a dependency, not a nicety.
5. Ultimate network: does the C64 Ultimate on firmware 1.1.0 expose the UCI network target? Add it to the hardware session's WP1 list.
6. Music: may the repo ship an original tune, or does `play` ship with no tune at all?
