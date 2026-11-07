# IO attack: log (append-only)

Rules: dated entries, newest last. A wrong conclusion is retracted in a later entry, never edited away. Every hardware entry carries the commit, the configuration, the trial rows, the denominator and one line per hypothesis. Brief: `io-attack-brief.md`; evidence: `io-evidence.md` (E-n.m); protocol: `io-trial-protocol.md`.

## 2026-11-07: lead's ranking before any run (main e16f3b4)

Nothing run on hardware. The ranking was written before any experiment result was in.

### Two failure classes, not one

The records mix two signatures and I treat them as separate until a trial joins them:

- **Class S (the original stall):** the drive is idle. Motor off, LED steady, CLK held low after 2-6 bits of a byte, free on ATN, resumes from its pointer (E-1.2 #8-12, E-1.3 #33). Since day one, also on the upstream kernel and with the ROM's own ACPTR inside Breadbin, never in 1,600+ block reads under stock KERNAL code started some other way (E-1.3 #20-22). The retry mitigation absorbs it.
- **Class R (new on 2026-11-07):** the drive is busy. `LOADING` hangs with the motor on and the LED solid, and a `LOAD ERROR`, both in the machine's own KERNAL LOAD, before our code runs (E-2.4 a, b, e). The same day both disks "failed" (owner). A busy, spinning drive that never answers looks like a drive that cannot read a sector, not like class S. The root-mount panic (E-2.4 d) could be either class: with no counter we cannot tell retries used up on class S from a read-error status on the U1.

### Ranking

| Rank | Hyp | Class | Why this rank | First test | Expected (my bet) |
|---|---|---|---|---|---|
| 1 | H2 + H1 (media / head / drive wear) | R | Class R matches a drive that cannot read; both disks failed the same day; a week of continuous reads with uncleaned heads; the rate rose over time (owner) | Control disk (H4), cold, then the Breadbin disk's boot file loaded by the KERNAL alone, interleaved (protocol, session 1) | Breadbin disk fails a KERNAL-only load as well; the control disk passes; points at media/heads, not code |
| 2 | H8 (the mitigation hides a rising rate) | S | Cheap, software only, and it turns every later run into data | IOSTAT counters (branch `io/instrument`) | VICE: 0 retries. Hardware: retries > 0 per boot, possibly several |
| 3 | H9 (new): start state | S | The `disksum` reader stalled at sector 0 with stock KERNAL calls (E-2.7) although stock KERNAL code is the "never stalls" control; how the stock stress runs were started is unrecorded (E-6.1 #5). If DMA starts and resets leave the drive or the bus in a different state from a power-on boot, that difference is what Breadbin runs and the control runs did not share | Research: does the Ultimate's reset pulse the IEC RESET line? Then the same stock stress program started by DMA vs by LOAD from BASIC | Unknown; this is the hypothesis I most want to kill or keep |
| 4 | H10 (new): drive frame error | S | The signature (mid-byte, CLK held, ATN frees, resume) looks like a talker that saw DATA low during a bit and parked until ATN. If so, the question becomes who pulls DATA (us, the Ultimate's IEC hardware, a slow line) | VICE: glitch DATA mid-byte and compare the drive's response with the signature; 1541 ROM behavior from public disassemblies | VICE reproduces it; that names the mechanism, not the culprit |
| 5 | H4 (stage a is not ours) | R | Inference from the words on screen (E-2.5); cheap to settle | Same as rank 1 | Control disk passes, so the machine and drive are fine on good media |
| 6 | H7 (power) | R, S | Plausible for an old drive on continuous duty; needs a meter | Rails at the drive under load, cold vs warm | Unknown |
| 7 | H6 (bus loading / config) | S | Tested repeatedly at N 4-8 with no effect (E-1.3 #13, #25-27); weak evidence, never strong | Only after ranks 1-5 | No effect |
| 8 | H3 (build regression) | root-mount only | Class R happens before our kernel runs, so a regression could only explain the root-mount panic, and the bus code is unchanged since 3d81693 (E-5) | Old image (aadea2f) after media is settled | No regression |
| 9 | H5 (layout timing) | root-mount only | The upstream kernel and the ROM's ACPTR stalled too, and class R is outside our code; at most it modulates class S's rate | Static cycle count of every timed path in three builds (running) | No period change, or one cycle far inside the margins: killed |

### What would change the plan

- The control disk fails cold at 2 or more of 12: hardware (drive, machine or bus) is implicated before media; next are head cleaning, a meter and a second drive, ahead of any code work.
- The KERNAL-only load of the Breadbin disk is clean but our root mount fails: class S or a regression in our code. The counters say which.
- Everything is clean cold (0 of 48): H1 is the only one left that predicts that; the next session runs the same set again after hours of warm-up.

### In flight (software, no hardware)

- `io/instrument`: counters for reads, retries, failures and blocks without EOI on byte 256, plus the last stall's track, sector, byte, try and ST. Behind `IOSTAT` (default on); `IOSTAT=0` must be byte-identical to main.
- H5: static cycle tables for aadea2f, 8cc3e57 and HEAD.
- H10: VICE DATA-glitch repro (branch `io/h10-frame-vice`, never to be merged).
- Research: the 1541 talker's frame-error path, EOI on byte 256, read-error behavior in LOAD, and the Ultimate's IEC reset.

## 2026-11-07: H5 killed (static analysis, no run)

Builds aadea2f (last good hardware series), 8cc3e57 (failed 2026-11-07), 55fd668, c64fe3a and HEAD were built in scratch worktrees. Cycles were counted from ca65 listings at final addresses. `iec.s` is byte-identical from aadea2f to HEAD. The `blk.s` changes are in `blk_init` only (a9c1c96, 279558c; checked with `git log`).

- No inner poll loop or bit path has a branch that crosses a page differently between builds. `dly` never crosses a page. Timed reads are all `bit PORT`, so the indexed-read page penalty does not apply.
- Differences are confined to ready-wait exits and timeout paths (±1 cycle), plus +1 cycle per byte on the `iec_read1` loop branch in the new builds. By the analyst's hand sum, the per-byte handshake is 126 cycles in both. Either way, a 1-cycle (1 µs) change sits against windows of 20 µs and more.
- Talker timing is the same in every build: set-up 84 µs, valid 94 µs, between bytes about 114 µs, EOI hold 84 µs. The listener samples DATA in the same `bit` read that sees CLK high, 0 to 11 cycles after the edge.
- The machine KERNAL's LOAD of the boot file uses none of this code.

H5: **killed**. Layout did not change bus timing between the good and the bad series. Not modelled: VIC DMA stalls and NMI, which are the same in every build.

## 2026-11-07: the 1541 talker, read in source (research, no run)

Source: the commented Commodore DOS 1541 source (mist64/cbmsrc, `DOS_1541_05`: sertalk, block, jobssf, idlesf). This is a reading of the source, not a run. Full report in the session scratchpad. Only behavior is cited here, not code.

- **The drive does not abandon a byte while holding CLK low.** Its only mid-byte abort is a frame error: DATA is seen low at the start of a bit. That path *releases* every line and goes idle. My H10 as written (frame error then park with CLK low) **does not match the signature.** Retracted in that form.
- **Bits go out on the drive's own fixed timing, with no per-bit handshake.** After the eighth bit the talker holds CLK low and waits, with no time limit, for the listener's frame acknowledge (DATA pulled low). It tests only ATN while it waits.
- **So the stall signature is: the drive sent all 8 bits, and our receiver counted only 2 to 6 of them.** The receiver then waits for a CLK rise that never comes, while the drive waits for an acknowledge that never comes. UNTALK frees it. The pointer only advances after the acknowledge, so a fresh TALK resends the interrupted byte. Bytes 195 + 61 = 256 in the ATN probe fit that.
- **Prediction (by reading, not run):** the resent byte is mangled (shifted, ones in the top bits). Our retry reissues `U1`, which reloads the sector, so the mitigation does not pass corrupt data.
- **EOI comes with the 256th byte of a `U1` buffer.** So the IOSTAT `io_neoi` count should be 0 on a healthy read.
- **A read error during LOAD is not an endless hang.** The drive makes about 30 attempts, with head offsets and a bump, then reports error 2x, roughly 6 to 15 s with the motor on (time UNVERIFIED). The LED toggles on each retry. A `LOADING` hang that never ends therefore needs more than one bad sector, or something else.
- **The Ultimate's FPGA logic never drives IEC RESET (firmware source read).** Whether the board wires the C64 reset to IEC pin 6 is unknown. Do not assume that a REST reset resets the physical drive.

### New lead hypothesis for class S: H11, the C64 CPU is halted for 2 to 6 bit times

Missing 2 to 6 consecutive CLK pulses, and never exactly 1, cannot be badlines. A badline steals about 40 cycles, and the drive holds each bit at least about 25 µs. It needs the 6510 stopped for roughly 150 to 500 µs in the middle of a byte. Interrupts are off in the bit loop. Our NMI handler is a bare `rti`. What remains is DMA: the Ultimate's REST memory access, REU transfers, or the firmware's own use of the bus. That would explain:

- the stall with both our receive code and the ROM's;
- no stall in stock-KERNAL stress runs, if those ran without host polling;
- the pulse histogram looking normal, because it only histograms pulses that were *seen*.

The pulse-histogram conclusion of 2026-10-31 ("not short pulses") stands. What it cannot rule out is pulses that were never seen.

**Kill test (no drive needed, no disk wear):** a C64 probe program with interrupts off reads a free-running CIA timer in a tight loop and records the longest gap and a histogram of gaps. Run it on the Ultimate:

1. idle;
2. while the host issues REST memory reads at the rates the harnesses use;
3. during REU transfers.

Expected if H11 holds: gaps above 100 µs appear, tied to one of these. Expected if dead: the maximum gap is badline-sized (under about 70 µs) in every condition. Then H11 is killed and class S needs another mechanism.
