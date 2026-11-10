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

## 2026-11-07: VICE confirms the drive's side of the stall (branch io/h10-frame-vice, e85124e, 8 VICE boots, stock ROMs)

The experiment-only build `make H10=1` pulls DATA low partway through the 5th block read of the boot, at byte 100, after bit 3. The injection runs in the receive path, so while it runs the C64 is not watching CLK.

| Glitch | Bits the C64 counted | CLK at timeout | Drive CPU | Retry |
|---|---|---|---|---|
| none (control) | – (33 reads, 0 retries) | – | – | – |
| 20 µs | 7 | held low ($DD00 $87) | ack-wait loop $E987-$E9C8 (polls DATA and ATN) | not tried |
| 100 µs | 7 | held low ($87) | same loop | recovered in 1 retry, login |
| 1 ms, at bit 3 | 3 | released ($C7) | not sampled (drive abandoned the byte) | disabled: panic |
| 100 µs, at bit 0 | 0 | released ($C7) | normal DOS code | not tried |

Reading:

- **Short glitches.** When the C64 is busy for about one bit time, it misses one CLK pulse. The drive finishes all 8 bits and parks in the after-the-last-bit acknowledge wait, with CLK held low. That is exactly the hardware signature's drive state, now seen directly in the drive monitor rather than inferred from source. The retry recovers it.
- **Long glitches, or one at the start of a byte.** This is a frame error: the drive releases CLK. It is a different signature, and the hardware never showed it.
- **What this means for hardware.** The hardware's "2 to 6 bits counted" means the C64 missed 2 to 6 pulses while the drive went on clocking. The C64 receiver was either not polling, or not seeing CLK, for several bit times.
- **What it does not show.** Whether ATN frees the drive in VICE, and whether a TALK resends from the pointer, were not tested. Neither was the mangled-byte prediction.

Effect on the hypotheses:

- **H10 (an outside glitch on DATA) is downgraded.** A DATA glitch alone does not make the C64 miss pulses. In this run the C64 missed a bit only because the injection kept it busy.
- **Class S becomes "the receiver misses CLK pulses".** Two candidates remain:
  - **H11:** the CPU is halted (DMA).
  - **H12 (new):** CLK pulses do not reach the C64's CIA. They could be filtered or delayed in the C64 Ultimate's bus logic (`Serial Bus Mode` routing), or lost to the line.

The halt probe separates the two: CPU gaps over 150 cycles in step with the stalls means H11; no gaps means H12.

## 2026-11-10: lead restart; H11 promoted to the lead hypothesis for both classes (reading, no run)

The previous lead session ended with work in flight. State taken over: `io/instrument` 8c7a2c0 (IOSTAT, hater review never returned), `io/haltprobe` (probe uncommitted, unproven), `io/trial-harness` 293ed52 (`--poll-mode none`), `io/h10-frame-vice` (experiment only). The owner's session-1 answers are still open. Restarted: the haltprobe proof in VICE, the IOSTAT hater review with a forced retry (H10 flag on top of IOSTAT), and a retrospective audit of what every recorded hardware series' harness read over DMA during disk transfers.

Why H11 moves up. Three facts already in the evidence point the same way:

- DMA halts the C64 CPU and a 1000-byte read during a transfer has corrupted loads on the emulated drive (E-4.1 #7, E-2.3); the class S signature needs the receiver to miss 2-6 CLK pulses while the drive goes on clocking (2026-11-07 VICE entry). A CPU halt of roughly 150-500 µs mid-byte does exactly that; nothing in our code can.
- The asymmetry "stalls under any Breadbin boot, including with the ROM's own ACPTR, never in 1,600+ stock-KERNAL block reads" (E-1.3 #20, #22) is a difference in how the runs were driven, not in the receive code. Breadbin boots ran under harnesses that read the screen; how the stock runs were driven is what the audit is checking.
- On 2026-11-07 the only attempt with no harness at all, the owner's manual boot, is the only one that reached login (E-2.4 c). The three stage-a failures happened in the machine's KERNAL LOAD (JiffyDOS host, a cycle-timed protocol) while an agent's harness was driving.

If H11 holds, both classes are one cause, the drive and media are not implicated, and the release claim changes: the failure is in our test tooling on the Ultimate, and a user booting by hand never sees it. It is not yet shown: one manual pass is not a rate, and H1/H2 still predict 2026-11-07 as well. What would kill it: the halt probe shows no halt over about 100 cycles for the read sizes the harnesses use; or the audit finds failing series with provably no DMA during the transfer; or the protocol's poll arm (below) fails no more often than the no-poll arm.

Planned protocol amendment, for the owner before session 1: a causal arm. D (DMA boot, root mount by our driver) run in pairs, `--poll-mode none` against a fixed screen read of 1000 bytes every 2 s during the mount, alternating, IOSTAT counters on every row. Predicted under H11: retries or stalls in the poll arm, zero retries in the no-poll arm. The drive is read either way, so the arm costs reads, not writes.

## 2026-11-10: H11 retrospective audit (records only, no run); H11 narrowed

A read-only audit took each recorded hardware series and asked what the harness read over DMA during the disk transfer at that date (scripts at their commits, HN entries). Summary table in the session; the rows that matter:

- **Fits:** 2026-11-06 "stalled at run" ran through the Ultimate test backend, which reads the 1000-byte screen every 0.5 s through LOAD and the mount (`tools/ultimatetest.py`@e7f4613). On the emulated drive: 2 of 14 failures with bench polling, corruption within 3-5 loads under continuous 1000-byte polling, 0 of 7 quiet (HN@14ba949). The 22 s boots of 2026-11-01..03 (about 40, all clean) had no DMA during any transfer: the first read at 20 s already saw login.
- **Contradicts:** the `disksum` control run of 2026-11-02 (one read at 180 s, after the typing) still stalled at sector 0, with no DMA during its transfer. That is reader code, not a boot, and its signature ("no status byte" for the first U1) is not class S's, but it shows the physical drive and bus can wedge without DMA. Also, the Boot and Console runs of 2026-11-02/03 on the emulated drive were 10 of 10 clean under 0.5 s polling.
- **Unknown, and the weak point:** the pre-mitigation class S stalls (about 3 in 4) ran under `plainboot`/`dmaboot`, which read nothing for the first 20 s, then 1000 bytes every 10 s. The stall onset was never timestamped. The stalls sat at the start of the mount (screen ends at the `reu:` line) after about 25-40 block reads, which at the mount's rate may be inside the read-free window. If it was, H11 cannot explain class S.
- **Unknown:** which script drove 2026-11-07 a, b, d and e (`plainboot` cannot show `LOADING`; it loads by DMA). Asked of the owner.

Effect: H11 is **alive for class R and the 2026-11-06 run, doubtful for class S**, and not the single cause the earlier entry today proposed. That entry's "both classes are one cause" is withdrawn as stated. The halt probe still decides whether the 0.5 s screen reads can halt the CPU long enough; the poll arm still decides it causally. New, cheap: every future stall dump records the kernel's uptime (jiffy clock) at the stall, so onset relative to the first DMA is known.

## 2026-11-10: halt probe proven in VICE (io/haltprobe 4e999fe; host test 4 OK, VICE 5 OK; no hardware)

Blanked: 0 stolen cycles in 342,016 loops. Screen on: max 58 stolen (badline). Injected REU halts of 150/256/600/1200 bytes: every transfer in its bucket (max stolen 129/250/594/1194). Limits: about 10% bucket accuracy; a halt inside the probe's slow path or housekeeping is missed; gaps of 65,536 cycles or more alias; VICE's REU is not the Ultimate's DMA. Protocol amendment 1 adds the block-0 reading and the causal poll arm (block 2b).

## 2026-11-10: IOSTAT fixed and reviewed (io/instrument 2a63d2b; VICE only)

First hostile review of 8c7a2c0 blocked on the stall record: `io_lidx` reset at every try (a good retry wiped it) and `io_lwn`/`io_lst` captured after UNTALK. Fixed in 2a63d2b. Forced retry in a scratch merge with `H10=1` (VICE, stock ROMs): nread 33, nretry 1, nfail 0, lidx $64 (the injected byte 100), ltrk 9, lsct 1, ltry 1, lst $02, lwn 1, matching the injection's own bit count. The `io_neoi` increment had to be dropped from that scratch build to fit, so neoi is unproven under a forced retry. Room above BSS 26 bytes (208 on main), below $CF00 445 (unchanged). IOSTAT=0 is byte-identical to main (prg, d64, lbl). make test-host OK, test-smoke 4 OK, test_29 OK. Second review: PASS, low findings only (comment on `lwn` semantics: 0 = ready wait expired, 1-8 = bits left in the bit loop; on the pre-data path `lst`/`lwn` are leftovers and `lidx` $FF marks them unreliable). Full VICE suite on 2a63d2b running (exclusive).

H8: the instrument exists; it is undecided until hardware rows carry counters.

## 2026-11-10: owner's answers; new H13 (configuration after the Ultimate's config reset)

Owner, from memory (soft evidence, dated):
- Cooldown: several days, all hardware (drive, C64 Ultimate, everything). Session 1 is therefore the cold baseline the brief asks for.
- The drive cannot be power-cycled remotely; `machine:reboot` resets the bus, which resets the drive. Trials start from a reboot; the owner power-cycles by hand when asked.
- Media: plenty, blank sacrificial disks too; no observable difference between disks in any use. The 11-07 disks showed no visible failure. A known-good control disk is provided at bring-up.
- 11-07, scripted boots: `LOADING` then a hang (never seen before); `?LOAD ERROR` and an immediate clear to `READY.` (looks like RUN/STOP-RESTORE); a root-mount panic. **Every manual test succeeded**, without cooldown, with soft resets and power cycles. Mid-cooldown, a known-good game booted and ran twice with expected speed, and the Breadbin image in the drive at the time.
- **The rise in failures and the new failure mode coincided with a full configuration reset of the Ultimate and a manual reconfiguration.** The owner aimed for the same configuration; the result is the desired state either way.
- IOSTAT stays on by default; it can come out once stable.

Reading. Two variables changed on or before 11-07 and only one failure condition is known: scripted runs failed, hand runs did not, after a config reset. That points at the harness (H11) or at the configuration (new H13), not at the drive or media (H1, H2), though one manual series is not a rate and H1 is tested by session 1's cold start anyway.

**H13: an IEC- or DMA-relevant Ultimate setting differs from before the reset**, and that setting matters only under the harness's access pattern or only for class R. No full dump exists from before the reset; only scattered items are recorded (Kernal ROM, Software IEC, drive A bus ID, turbo, REU, DMA Load Mimics ID; `Serial Bus Mode` and `Burst Mode Patch` never). Falsifier: a full read-only dump at bring-up (`cfgdump.py`, in progress on `io/trial-harness`), every item that differs from the firmware default listed and each IEC/DMA/timing one judged; if the owner has a saved configuration file from before the reset, diff against it. H13 is killed for an item only by a trial that varies that item; a plausible item becomes an arm in session 2, not session 1.

Note on `?LOAD ERROR` then an immediate clear to `READY.`: the KERNAL does not clear the screen on a load error. A clear to `READY.` is what an NMI (RESTORE) or the BASIC warm start after a BRK does, or a host action (reset with a fast boot, or a key-buffer write). Ask of the 11-07 transcript, if found: what the script did right after it detected the error.

## 2026-11-10: a pre-reset configuration exists (owner)

The owner saved the configuration to the Ultimate's flash before the reset and expects to find that file. The reason for the reset is not remembered; possibly an Ultimate-specific feature had become flaky where it had not been before. Not recorded at the time, and the agents of that period cannot be asked.

Effect: H13 can be tested by a diff rather than by inference: `cfgdump.py fromcfg` (in progress) converts the saved file with the same redaction, then `cfgdump.py diff` against the bring-up dump. The raw file contains network settings: it stays out of the repository and out of any message; only the redacted JSON and the diff are used. A second note for H1: if an Ultimate feature was already getting flaky before the reset, the Ultimate itself (not only the drive) is a candidate for "tired hardware"; the halt probe and the control disk are the first readings of it.
