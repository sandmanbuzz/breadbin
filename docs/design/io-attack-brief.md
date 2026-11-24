# IO failure attack: brief for the lead

> **Historical (2026-11-23): the IO effort is closed (harness DMA; `docs/design/io-attack-log.md`, closing entry).**

Status: draft for the owner, 2026-11-07, against main `1c7268f` (tag `v0.1`). The evidence behind every statement is in `docs/design/io-evidence.md` (cited below as E-n.m). Read it after this page; this page does not repeat it.

## 1. Mission

Boot and IO on real hardware fail intermittently. Breadbox is positioned as "Ultimate first" and is meant to keep booting on a stock C64 with a 1541, so this is a product-direction risk, not a nuisance. The mission is to find the cause, or to make the failure so rare that it is indistinguishable from gone, and to prove it with numbers that were fixed before they were seen.

Everything is in scope: our kernel, the Ultimate's firmware and configuration, the machine's KERNAL (JiffyDOS), the drive and its ROM, the cable, the power supply, the media, the imagers, and the test harness. If every piece of software we control is exonerated, the work moves to the hardware and the screwdrivers come out. Hardware is an object we own, not a fixed fact.

Budget is the owner's to spend by hand. There is no fleet budget behind this work. Plan cheap-first (section 6) and expect a bounded number of strong-model turns.

## 2. What is known (short form)

- The physical-1541 root-mount stall predates our work: the upstream baseline (`aa58d27`) stalled too (E-1.3 #21). Before mitigation about 3 boots in 4 stalled (E-1.1).
- A mitigation (bounded `bus_acptr` wait, up to three `iec_read` tries with UNTALK, `3d81693`) was followed by no recorded stall for about 57 boots between 2026-11-01 and 2026-11-03 (E-1.4 #44). That count is the author of the inventory's own sum, not a single recorded total. "13 of 13" in CLAUDE.md is 8 + 5 and was run with the OEM drive ROM fitted (E-6.2 #5).
- On 2026-11-02 the drive was reassembled (ROM chip reseated, RF shield reseated, original cable, ferrite clamp at the drive end). After that, runs with and without the mitigation both passed (6 of 6 and 6 of 6, E-1.4 #39). Which of the changes mattered is unknown.
- After 2026-11-03 the failures came back (E-1.5): a UCI-run boot stalled at `run` on 2026-11-06; the read-only whole-disk reader has stalled at sector 0 five times (never completed); on 2026-11-07, five attempts after a full power cycle gave two `LOADING` hangs, a root-mount panic, a `LOAD ERROR` (rc 143), and one manual boot by the owner that reached login (E-2.4). The cause of these is not known and they were not bisected.
- The two `LOADING` hangs and the `LOAD ERROR` happen in the machine's own KERNAL load of the boot file, before our kernel runs. That is an inference from the words on screen, not a recorded fact (E-2.5). If it holds, our IEC driver cannot be the cause of those three. The root-mount panic is in our kernel.
- Nothing in the records measures how often the mitigation's retry fires, whether a stall can end silently with wrong bytes, or what the drive's or machine's power and thermal state was.

## 3. The owner's firsthand history (soft evidence, dated 2026-11-07)

This is not in the docs in this detail. Treat it as testimony: weigh it, test it, do not cite it as measured.

- Before mitigation the stall was chased with a cable swap, a ROM swap and a media swap. None changed it. The heads have not been cleaned, but the failures do not look like signal weakness (that shows as loss of sync and the drive hammering), which has never been observed.
- The stall never fired more than once in two weeks, and never unexpectedly, in the period before.
- After mitigation we declared it good enough and moved on. The failure rate has risen over time, not fallen. Acceptance began because the investigation was already deep and a mitigation was in hand, not because the cause was understood.
- Until 2026-11-07 there was no evidence of a KERNAL-based load failure. The owner had not seen a `LOADING` hang or a `?LOAD ERROR` since the 1980s.
- The drive and the machine have been powered on since they joined the CI loop, with one break in a non-dev period. That is not a designed duty cycle for a 1541. The owner has seen far longer uptimes on real hardware, but not recently. The prior owner's history of the drive is unknown. The last time this drive saw this kind of use was probably over twenty years ago.
- Both pieces of media used for the project failed on 2026-11-07. More media is available.
- A slow, bespoke sector-by-sector imager (`mcdup`) was used before the nibbler was introduced and can be folded into the tests.
- Hypothesis from the owner: tired hardware. If the failures return to baseline after the hardware has been allowed to cool down, that supports it more strongly.

## 4. Hypotheses and what would kill each

Each hypothesis has a test that can fail it. Write down the expected outcome before running.

| Id | Hypothesis | Falsifier (cheap first) |
|---|---|---|
| H1 | Aging or heat-stressed hardware (drive, its power supply, the C64 or the Ultimate) after continuous power | After a full cooldown (hours, powered off), the same trial set returns to the early baseline; then a controlled warm-up shows the rate rising with time powered. If it does not rise, H1 is dead. |
| H2 | Media or imager (a nibbler-written disk is marginal; read-back of a written disk already stalled) | Cross two media with both imagers (nibbler and `mcdup`) in a balanced design. If the rate follows the imager or the disk, H2 holds; if it follows neither, H2 is dead. |
| H3 | A build regression since the last good series (2026-11-03, image from `aadea2f`, sha256 prefix `743fd1ac9103fb8b`) | Boot that exact old image on the same hardware today, same disk, same power state, same N. A good rate for old and bad for new is a regression and a bisect between them follows. A bad rate for the old image means the hardware changed. |
| H4 | The three `LOADING`/`LOAD ERROR` failures are the machine's or drive's, not ours | A non-Breadbin control disk (any known-good disk, unmodified) loaded by the machine's KERNAL, N trials in the same loop. Failures there remove our software from the frame for that stage entirely. |
| H5 | Layout-dependent timing in our bus code | Our timing loops in `iec.s` are cycle-counted. A taken branch that crosses a page costs one more cycle, and `KSTART` moved up one page since the last good series (`55fd668`). VICE is cycle-exact: measure the bit-wait and EOI loop times at several kernel placements by padding. If a loop's period changes by a cycle at a boundary and the margin is thin, H5 is alive; then test the same placements on hardware. |
| H6 | Bus loading or configuration: Software IEC state, drive A on bus 9, device ID mimicry, a second device, the long cable | Vary one factor at a time on the control disk (H4's set), then on Breadbin. |
| H7 | Power: a weak or drifting supply to the drive or the C64 | Measure rail voltages at the drive and C64 under load before and after cooldown; compare with spec; swap a known-good supply. |
| H8 | The mitigation is hiding a faster-rising failure (retries absorbing more over time) | Instrument first (section 6, step 2): a retry counter, EOI check on byte 256, log where the stall occurs. If the retry count has been climbing, the trend is in the drive or bus, not the boot path. |

H5 and H8 are software-side and cheap. H1, H2, H4, H6 and H7 need the hardware and should wait until the protocol in section 5 is written.

## 5. The protocol, fixed before the first trial

- **Trial.** One trial is: full power cycle of the drive, a stated rest time, then one automated boot to a login prompt, with the outcome recorded as one of `login`, `LOADING hang`, `LOAD ERROR`, `root-mount panic`, `other (describe)`, plus the time to login. The machine's KERNAL host (stock or JiffyDOS), the media id, the imager, the image sha256, the build commit, the bus layout and the drive's power-on hours since the last cooldown go on every row.
- **Denominator.** Fix N and the stopping rule before trial 1 (the R13 practice, E-7.1 #4). Alternate the arms in a fixed order set before the run. Five trials per arm cannot tell 25% from a 0-50% band (E-0, line 16); use enough trials that the result separates the hypotheses you actually have, and say the power in advance.
- **Baseline.** Reconstruct the failure counts for 2026-11-07 and the 2026-11-03 run from `docs/hardware-notes.md` and ask the hardware agent for the missing denominators (how many trials the 2026-11-07 attempts represent, in what order, with which KERNAL host). Do not compare a new rate against a baseline with an unknown denominator.
- **Cooldown test.** Record the hours powered off. After cooldown, run the same trial set as the baseline first, before any other experiment touches the drive.
- **Controls first.** Run the non-Breadbin control disk (H4) in the same loop as the Breadbin disk, interleaved, so drift over the session shows in both.
- **Exoneration standard.** "Not our software" requires an experiment that would have failed if it were. Absence of findings does not exonerate. State for each piece (our `iec.s`, `blk.s`, the kernel boot, the harness, the Ultimate's firmware, the KERNAL) what test cleared it, with the rate.

## 6. Order of work

1. **Read** `docs/design/io-evidence.md` end to end (265 lines) and the gaps it names (its section 8). Reconcile the contradictions in its section 6.2 where cheap.
2. **Instrument the mitigation (software only, reproducible in VICE).** A retry counter and a stall log (where in the block, which byte, which try), an EOI/status check on byte 256 of each block, a counter exposed through a command or a fixed RAM address. Keep it small: kernel room below `$CF00` is 445 bytes, above the BSS 208. Prove it in VICE. Ship it behind a build constant if it costs space. This turns every future hardware run into data on how often the mitigation fires.
3. **H5 in VICE.** Pad the kernel to move the bus loops across page boundaries; measure loop periods and boundary effects with the cycle-exact emulator; read the loops in `iec.s` against the 6502 branch-penalty rules. Cheap, parallelisable, no hardware.
4. **Write the trial protocol** (section 5) with N, arms, order and stopping rules. Send it to the owner before any hardware time is used.
5. **Hardware, in this order:** the control disk (H4) with the machine's KERNAL; the 2026-11-03 image on the same hardware (H3); the cross of media and imagers (H2); the cooldown comparison (H1); then H6 and H7 with a meter and a swap.
6. **Fix or mitigate** what the evidence points at, with a hater review and the full suite before landing (`CLAUDE.md`). A kernel fix needs `make test-host`, the smoke test, the targeted VICE tests for what it touches, and a full run on a frozen tip. A hardware fix needs the exact change, the measurement before and after, and the denominator.

## 7. Rules (non-negotiable)

- Hardware use goes through `tools/with-lock -r ultimate`; one holder at a time; announce the write first; restore the configuration by trap and read it back; asks that need human hands go last in a run. Physical-disk writes need the owner's go for each write. No long DMA reads during disk transfers (E-4.1 #7).
- The Ultimate's network address is private. Never write it, a hostname, a username or a home path into a file in the repository, a commit message or an artifact.
- No push, tag or release without the owner's go. Commits are signed, authored as `sandmanbuzz` (check `git var GIT_AUTHOR_IDENT`), with no model identifier and no `Co-Authored-By` trailer. Land with `tools/with-lock -r land -- sh tools/land.sh BRANCH "message"` from a worktree; the primary clone stays on `main` and nobody works in it.
- Delegate cheaply. Contextless Sonnet or Haiku agents do harnesses, builds, bisects, trial runs and evidence gathering; the lead designs, decides and judges. Every change gets a hater review whose brief says to find every reason to block it and gives it the touched-area test list as well as the diff.

## 8. Deliverables

- `docs/design/io-attack-log.md`: an append-only log. Every entry has the date, the commit, the configuration, the trial rows, the denominator, and one sentence on what the result does to each hypothesis.
- The trial protocol (section 5) as a committed file before the first hardware trial.
- A verdict page per hypothesis: killed, alive, or undecided, each with its experiment and rate.
- The fix or the hardware change, with the before and after rates and N.
- An updated `docs/hardware-notes.md`, `docs/wip.md` and the README's real-hardware paragraph.

## 9. Done means

One of: (a) a cause found, fixed, and shown by a pre-registered trial set whose result separates old from new; (b) the cause shown to be hardware, how it was proved, and the hardware fix applied and shown by the same kind of trial set; or (c) the failure rate reduced so far that a pre-registered trial set of the owner's choosing shows none, with the instrumentation in place so a return would be seen. Until one of these, report, do not declare.

## 10. What not to do

- Do not chase the stall by re-running the old A/B series with five trials per arm and reading the noise.
- Do not conclude "hardware" or "not hardware" from the absence of a failure in a short run.
- Do not trust the `13 of 13` figure, the 5-of-5 series, or any rate whose denominator the records do not give.
- Do not change the kernel's bus timing on a hunch. Every change needs an experiment that could have shown it was wrong.
