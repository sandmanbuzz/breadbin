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
