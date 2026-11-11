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

## Amendment 2 (2026-11-10, after the owner's answers; before any trial)

- **Trial start.** The drive cannot be power-cycled remotely. Every trial starts from `machine:reboot`, which resets the bus and so the drive; the row records it. The owner power-cycles by hand only on a wedge (LED on after a reboot), and that row and the next say so.
- **Cold baseline.** Several days powered off, all hardware. Block 0 then block 1 run first, before anything else touches the drive. Each row records minutes since power-on, so H1 can be read as a trend within the session.
- **Configuration.** `cfgdump.py` (read-only, network items redacted) runs at session start, after block 0, and at session end; the dumps go with the results, and every item that differs from the firmware default is listed in the log before block 1. No setting is changed in session 1 except the existing per-arm KERNAL/Software IEC changes, which are restored by trap and read back. An IEC/DMA-relevant item that looks wrong becomes a session-2 arm (H13), not a mid-session change.
- **Control disk.** The owner's known-good disk, write-protected, given at bring-up. Media is not a variable in session 1 (owner: no observable difference between disks).
- **Dry run first** (the runner's): one K trial with the owner watching the screen, to confirm the `load` / `run` typing lands before the transfer starts. It is logged as a dry run and not counted.

## Session 2, pre-registered (2026-11-10, written after session 1 and before any session-2 trial)

Question: does REST DMA explain the failures of 2026-11-07, which all ran under the old test backend's `wait_for` (a 1000-byte screen read every 0.5 s from the typing of `load` to the login), while the owner's unpolled manual boot that day passed? And is light polling safe?

Same hardware, configuration, disk (`bb-last-agent`, 8cc3e57 image) and kernels as session 1 block 2/2b (disk kernel for K/J; `iostat-cache0` by DMA for D/Q/P/O). Harness `io/session2-harness` (`plans/session2.plan`). Arms alternate within each block; the order is fixed in the plan.

| Block | Arms x pairs | New arm | Prediction (written now) | Reading |
|---|---|---|---|---|
| 1 | K, J x 8 | J = K plus 1000 B every 0.5 s from the typed load | J fails (LOADING hang, LOAD ERROR or mismatch) in at least 3 of 8; K 0 of 8 | J >= 3 and K 0: H11 explains class R (the 11-07 KERNAL-load failures). J 0 of 8: it does not; class R stays open (H1/H2/H13) |
| 2 | D, Q x 8 | Q = D plus 1000 B every 0.5 s from the start (no pass accepted before 3 s) | Q retries far above P's 5-9 per boot; at least 1 of 8 root-mount panics (retries used up); D 0 retries | Q panics: H11 explains the 11-07 root-mount panic |
| 3 | D, P x 6 | repeat of 2b with the stall record captured | P retries again; record shows lidx 0-255 (inside the data) and lwn 1-8 (bits still to come) or 0 (ready wait) | lwn 2-6 with lidx in the data = the class S signature, caused on demand |
| 4 | D, O x 8 | O = D plus 1 byte ($D6) every 0.1 s | O retries total over 8 boots between 0 and 3 (block 0: 1 halt >= 400 cycles in 600 reads) | O 0: 1-byte polling at this rate is usable for harnesses; O > 3: no DMA at all during IO |

Stopping rules: as session 1; each poll arm stops at 4 failures (P ends its block). Any mechanical symptom stops everything. Worst case 156 min if every trial times out; expected about 110 min.

Power: block 1, if the true J failure rate were 50%, P(J < 3 of 8) = 14%; at 80% (11-07's look), 0.1%.

## Session 3, pre-registered in part (2026-11-10, after session 2 block 2, before any session-3 trial)

- **Arm Z (pause-wrapped polling):** D plus, every 0.5 s from the start, `machine:pause`, one 1000-byte screen read, `machine:resume`. The owner's question: does pause's "good landing" make DMA safe? Prediction: no. Pause lands on a CPU bus cycle, not on an IEC byte boundary; inside a byte the drive clocks bits with no handshake, and a pause lasts the REST round trip (milliseconds), longer than one DMA read. Z panics at least as often as Q (4 of 4 in block 2). Z clean in 8 would refute this and make pause a harness fix. Paired with D, 8 pairs, Z stops at 4 failures.
- **Fixed disksum on hardware** (`io/disksum-vice` 7b0f809), with no DMA during the read: the drive's own reading of the disk, sector by sector. Prediction: 683 of 683, every checksum matching.

Completed 2026-11-10 before any session-3 trial (plan `plans/session3.plan`: blocks `1 DZ 8`, `2 TS 8`, `3 DG 8`, `4 KH 8`; every polled arm stops at 4 failures):

- **Arm T (stock KERNAL, no polling, K otherwise):** control for S. Prediction: 8 of 8 clean, as K was.
- **Arm S (stock KERNAL, J otherwise: the machine's own `load"*",8,1` with 1000 B every 0.5 s):** does the DMA harm need JiffyDOS? Prediction: no. The stock receiver follows the talker's CLK per bit but the talker does not wait for it, so a halt across a bit loses it. S fails (wrong data, a load error or a hang) in at least 1 of 8, fewer than J's 4 of 4 because the stock transfer is slower and spends a smaller share of the time inside a byte. S clean in 8 would make the harm JiffyDOS-specific and weaken the upstream report.
- **Arm G (D plus the bus-idle gate: three 1-byte `$DD00` reads 0.1 s apart, the 1000-byte read only if all show `(v & $F8) == $C0`):** the harness fix (`fix/harness-idle`). Prediction: 0 failures in 8, and skipped reads > 0 in every trial (the root mount is seen as busy). Any G failure blocks `fix/harness-idle` as a fix and leaves it at most a mitigation. Skipped = 0 in every trial would mean `$DD00` by DMA does not show the bus (the gate is blind), whatever the failure count.
- **Arm H (J plus the same gate):** Prediction: at most 1 failure in 8 (a transfer can begin between the last sample and the read). 2 or more refutes the gate for the JiffyDOS load.
- **`$DD00` histogram** (every 1-byte read, arms G and H): no prediction; it records what the port shows by DMA while Breadbin and the JiffyDOS load run.

## Session 4, pre-registered (2026-11-10, after session 3, before any session-4 trial)

Plan `plans/session4.plan`: block `1 KL 8`, L stops at 4 failures. Same kit, disk, drive and config as session 3.

- **Arm L (K plus a 1-byte read of `$D6` every 0.1 s from the typed load):** the rate at which the test harness (`fix/harness-idle`) watches the machine's own load. O showed this rate clean in 264 reads during *our* boot, whose driver handshakes every byte; the JiffyDOS receive clocks bit pairs on fixed timing after one handshake per byte, so a halt inside a byte has no slack. About 80 reads land in each 8 s load, 640 over the arm. Prediction: at least 1 failure (mismatch, load error or hang) in 8. The halt length of a 1-byte DMA on this firmware is unknown; if it is a few cycles the prediction may well fail.
- **Decision rule, fixed now:** L with 1 or more failures in 8: the harness must make no DMA at all during the machine's load (a fixed wait, then the 1-byte ready check and the read-back). L clean in 8: the 1-byte wait stays, guarded by the read-back, and the rate is recorded as clean in 640 reads during the JiffyDOS load (which bounds, not proves, the per-load risk).
