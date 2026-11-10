# IO attack: trial protocol, session 1 (draft for the owner, 2026-11-07)

Fixed before trial 1. Nothing here is run until the owner has read it and said go. Results go in `io-attack-log.md`; a deviation from this page is logged as a deviation, not absorbed.

## Why this design

Session 1 is the first contact after the cooldown, so it carries two jobs that cannot be redone later: the **cold baseline** (H1) and the **localisation by stage** (class R vs class S, see the log entry of 2026-11-07). It needs no physical-disk write and no new kernel behavior. The only kernel difference from main is the IOSTAT counters (measurement only, `io/instrument`), and the image hash goes on every row.

One disk serves three arms that split the boot by stage, so a disk swap is not needed per trial:

| Arm | What runs | Stage tested | Whose code reads the disk | Pass |
|---|---|---|---|---|
| **C** control | Owner's known-good, non-Breadbin disk: `load"<file>",8` by the machine's KERNAL (JiffyDOS host, as normal) | a, on other media | machine KERNAL + drive | `READY.` within the limit, length and checksum equal to trial C1's |
| **K** kernal-load | Breadbin disk: `load"*",8,1` only, no `run`; bytes compared with the image's `breadbin` file (as `stockload.py`) | a, on our media | machine KERNAL + drive | `READY.`, every byte equal |
| **B** boot | Breadbin disk: `load"*",8,1`, `run`, to the login prompt; IOSTAT counters read after login | a + b | KERNAL, then our IEC driver | login within the limit |
| **D** root-mount | Kernel put in memory by DMA, root mounted from the disk by our driver (`plainboot.py`) | b only | our IEC driver | login within the limit |

## Configuration (every row records it)

Normal configuration (experiments README) except where noted: JiffyDOS KERNAL host, physical 1541 alone on bus 8, drive A on bus 9 with no disk, Software IEC off, turbo off, REU on, 1581 off the bus. The Ultimate's `Serial Bus Mode` and `Burst Mode Patch` settings are read back and recorded (never recorded before). The JiffyDOS drive ROM stays fitted. Columns per row: session, block, trial index, arm, start time, minutes since the drive was powered on, image sha256 prefix, kernel commit, disk id, outcome, seconds, IOSTAT counters (B and D), stall dump if any.

Outcomes: `pass`, `LOADING hang`, `LOAD ERROR`, `root-mount panic`, `stall` (class S signature in the dump), `mismatch` (bytes differ: silent corruption, the worst outcome), `other` (described).

## Order and counts (pre-registered)

0a. **Block 0, CPU-halt probe (H11), no drive needed.** Physical drive off or unplugged from the bus, so it takes no wear. `haltprobe` (branch `io/haltprobe`) runs five arms of 60 s each in a fixed order: idle with no host traffic; 1-byte REST reads every 1 s; every 0.1 s; one 1000-byte read every 2 s; REU transfers. Pass condition: the longest gap is badline-sized (65 cycles or less) in every arm. Any gap of 150 cycles or more, in any arm, is reported before block 1. If one shows up, block 2's harness polling changes before block 2 is run, and that change is logged as a deviation. This block can run while the drive is still cooling down, if the Ultimate itself is not part of the cooldown.
0. **Cold record.** Hours powered off, room temperature if known. Owner powers on the drive, then the Ultimate. Nothing else touches the drive.
1. **Block 1, control, cold:** C x 12. One disk insertion.
2. **Block 2, Breadbin disk:** the cycle K, B, D repeated 10 times (30 trials). One disk swap.
3. **Block 3, control, warm:** C x 6. One disk swap.

About 2 hours in all with `--poll-mode none` (no memory reads during a trial; every trial runs to its limit), plus 5 minutes for block 0; three hand actions, plus a drive power cycle after any wedge.

**Limits:** C and K 120 s, B 150 s, D 170 s (the existing `plainboot` limit). On a timeout: stall dump with short DMA reads only (no screen-sized read during a transfer), then a machine reset. If the drive is still busy (LED on), the owner power-cycles it, and the row and the next row say so.

**Stopping rules:**
- Stop everything at once on any mechanical symptom (knocking, grinding, smell, a motor that will not stop). The drive is decades old: data is worth less than the drive.
- An arm that reaches 5 failures stops; the other arms continue. Five failures in at most 12 already puts its rate well above the post-mitigation record, and further trials would only wear the drive.
- Three wedges in a row that need hands: stop the block and log it.
- Nothing else is run in the session, even if an idea comes up. Ideas go to session 2.

## What each result means (written before the data)

Power: with a true failure rate of 25% (the pre-mitigation stall), 0 failures in 12 has a probability of 3%, and 0 in 10 of 6%. With the rate of 2026-11-07 (about 4 in 5) a clean arm cannot happen by luck. With 10% (a slowly worn drive), 0 in 12 happens 28% of the time, so a clean session does **not** rule out a low rate; acceptance is a later, larger set (the done criterion).

| Result | Reading | Next |
|---|---|---|
| C fails at least 2 of 12 cold | The drive, the machine or the bus fails on media that is not ours: hardware, H1/H6/H7 | Head cleaning as an arm, rail voltages, a second drive or C64 if one can be had. No code work. |
| C clean, K fails at least 2 | Our disk (media or image) fails under the machine's own loader: H2 | Fresh media, crossed with the two imagers (session 2); a read-only sector scan of the failing disk |
| C, K clean, B or D fails | Our stage b: class S, or a regression. The counters and dumps localise it | H9/H10 experiments, then H3 (old image) |
| All clean, counters show retries | Class S still occurs and the mitigation hides it | The retry rate becomes the metric: rate per block read, cold vs warm |
| All clean, no retries | Cold hardware is healthy: H1 survives as the only explanation for 2026-11-07 | Session 2: the same set after 4 hours or more powered on (warm). If it stays clean, H1 is dead too, and we are back to a rate too low to see in 48 trials |
| C clean cold, failing warm (block 3) | Supports H1 directly | Warm-up series with time stamps |

## What the owner is asked to supply (hands, last and one at a time)

1. A known-good, non-Breadbin disk with one program file of 10 KB or more, which you are happy to have read about 20 times. Read-only: write-protect it.
2. The Breadbin disk to use. If the two disks that "failed" on 2026-11-07 failed by visible damage or errors in another drive, use neither, and session 1 waits for a fresh disk written with your go (that write is itself a drive test: `mcdup` verifies each sector).
3. Can the drive's power be switched without hands (a switched socket)? If yes, every trial in block 2 can start from a drive power cycle, as the brief's trial definition asks. If not, trials start from a machine reset and that is recorded.
4. The hours of cooldown at the start of the session.

## Amendment 1 (2026-11-10, lead restart; before any trial, for the owner)

- **Block 0 is ready.** `haltprobe` (io/haltprobe 4e999fe) is proven in VICE: screen blanked, no stolen cycles; screen on, at most 58 (badlines); injected REU halts of 150, 256, 600 and 1200 bytes land in the 101-200, 201-400, 401-800 and 801-1600 buckets, every one. VICE shows the probe detects a halt; only the Ultimate shows what its DMA does. Pre-registered reading: a REST read that steals 150 cycles or more in any arm keeps H11 alive; under 100 in every arm kills H11 for the read sizes tested.
- **Block 2b, causal poll arm (H11), after block 2.** Arm D only, 8 pairs, alternating `none` / `poll`, with `poll` = one 1000-byte screen read every 2 s from 3 s after the start to the limit. IOSTAT counters on every row. Predicted under H11: retries or stalls in `poll`, none in `none`. Stopping: `poll` reaching 4 failures ends the block (the point is made, the drive is spared). Power: if `poll` fails at 50% and `none` at 0%, 8 pairs show it with p of about 0.004 (0 vs 4 or more); a 10% rate difference is not resolvable at this N, and is not the question.
- **Every stall dump records the kernel's uptime** (jiffy clock), so onset relative to the first DMA read is known.
