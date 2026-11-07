# IO failure evidence inventory (Breadbox / Breadbin, C64 OS)

Compiled 2026-11-07 from the tree at 78fcaa2 (branch docs/why-process). Read-only research; nothing was run on hardware.

Conventions
- HN = docs/hardware-notes.md. A heading is cited as "HN <date> <short title>" (the log is dated by entry, not always in order).
- OBSERVED = a measurement or run was recorded. INFERRED = someone's explanation or hypothesis.
- "the Ultimate" = the C64 Ultimate; "the physical drive" = the real 1541 at device 8. No addresses, hostnames or paths are given here.
- Rates are quoted as the records give them. Where a record lacks a number, that is stated as MISSING.

## 0. Orientation in five lines

- There are two separate bodies of failure: (A) the physical-1541 root-mount stall and its later "LOADING" hangs (sections 1-2); (B) Ultimate-side issues: key drops, DMA-poll corruption, write-back, UCI quirks (section 4).
- The only fix in the kernel is a mitigation (bounded wait plus retry). The root cause is not known. [OBSERVED: CLAUDE.md "Status"; docs/why-this-fork.md "Physical 1541 root-mount stall: mitigated, not root-caused", 2026-11-07]
- The last record (2026-11-07) says the mitigation is not reliable enough: retry budget exhausted once, new LOAD ERROR mode. [OBSERVED: HN 2026-11-07 physical boot after a full power cycle]
- Most hypotheses were tested with 5-8 boots per arm; the notes say that cannot distinguish 25% from 0-50%. [OBSERVED: HN 2026-11-02 correction, point (3)]
- The stall has also been seen with code we did not write (upstream baseline aa58d27). [OBSERVED: HN 2026-10-31 stall predates our work]

## 1. Timeline of the physical-1541 root-mount stall

### 1.1 First seen and baseline rates (before mitigation)

1. 2026-10-30: first contact with a physical 1541 at device 8 (fresh media); at that time the boot failed for an unrelated reason (the Ultimate's emulated drive was on 9, the harness assumed 8). [OBSERVED: HN 2026-10-30 hw-bench at 10dbf3c]
2. 2026-10-31, stage 2 (own IEC driver, Breadbin 45f1a72 kernel) on the physical 1541 (JiffyDOS 5.0 drive ROM, image copied sector by sector by the user with a disk copier): "The boot program loads every time (25 s with the JiffyDOS fast loader)... The root mount then fails most of the time. Attempts: 2 reach the login prompt, 5 stop." [OBSERVED: HN 2026-10-31 stage 2 against the physical 1541]
3. Same entry: with the emulated drive (9) and Software IEC (11) disabled, "1 pass, 3 stops of 4"; the 1581 was attached in all of them. [OBSERVED: same]
4. Rate quoted elsewhere as "5 of 7 boots" stalled. [OBSERVED: docs/wip.md "Hardware session state" 2026-10-31; docs/design/fast-io.md line 137, 2026-10-31]
5. 2026-10-31, after the 1581 was removed: "Counting every clean-bus run so far the original kernel passed about 3 times in 14." [OBSERVED: HN 2026-10-31 state of play]
6. Baseline across series: "5 passes in 20 boots overall, a quarter"; "1 in 4 to 3 in 8 across series"; one series of 8 gave 1 pass, others 3 of 8. [OBSERVED: HN 2026-10-31 stall predates our work; HN 2026-10-31 stalls are not tied to particular blocks; HN 2026-11-01 more negatives]
7. CLAUDE.md and docs/wip.md summarise this as "about 1 boot in 4". [OBSERVED: CLAUDE.md "Status"; docs/wip.md "Known gaps at the first milestone"]

### 1.2 What a stall looks like (state at the stall)

8. Screen ends at the "reu: 32 x 64k" line (or just after the banner); no panic; kernel alive (jiffy clock runs); $BA = 08; $90 = $02 (read timeout); $DD00 = $87, meaning the drive holds CLK low and we hold nothing; the drive's motor stopped, LED steady on. [OBSERVED: HN 2026-10-31 stage 2 against the physical 1541; HN 2026-10-31 stall predates our work]
9. In the original unbounded kernel: kernel sat in bus_acptr's @rdy wait; $90 bit 1 is only set by bus_acptr's timeout exit, so "one timeout, then a hang". [OBSERVED: HN 2026-10-31 state of play]
10. Where inside a byte: bit counter at first timeout was 5, then 2 remaining in two stalls; in nine valid dumps it was 2, 3, 5, 4, 5, 4, 6... remaining, "never 0, 1, 7 or 8". [OBSERVED: HN 2026-10-31 state of play; HN 2026-10-31 later: stall not in our receive loop]
11. Block the kernel was reading at stall: track 3 sec 15; track 16 sec 1 (twice); track 11 sec 11. "Different blocks on different tracks, so no single bad sector." [OBSERVED: HN 2026-10-31 stalls not tied to particular blocks]
12. Stall point within the 256-byte block, measured after the fact: after UNTALK and a fresh TALK the drive sent the rest of its buffer (61, 192, 146 bytes), implying 195, 64, 110 bytes already sent. [OBSERVED: HN 2026-11-01 ATN frees a stalled drive] The "continued from its pointer" part is INFERRED ("if it continued from its pointer, as it appears to").

### 1.3 Experiments tried and results (chronological)

All on the physical 1541 unless stated. Stock-KERNAL host unless stated.

13. Other bus devices: emulated drive 9 and Software IEC 11 disabled: 1 pass of 4 (above). 1581 removed from the bus: user reported loading from device 8 from BASIC then worked; the earlier series (with the 1581 attached, even switched off) "are not trustworthy as a measure of the driver". [OBSERVED: HN 2026-10-31 everything answers OPEN scare; INFERRED that a switched-off attached device loads the lines: "may"]
14. Bit-wait lengthening: wait up to ~0.8 s per received bit instead of ~3 ms (commit 02339eb, 2026-10-31; hypothesis "real 1541 job IRQ stalls CLK low >3 ms"): 2 stalls, 1 pass. Not a fix. [OBSERVED: HN 2026-10-31 state of play; commit 02339eb message "Unproven on hardware"]
15. Shorter blind window between seeing CLK rise and watching it fall (tag archive/iec-bit-waits, 3bf517d, 2026-10-31): "Hardware: inconclusive (pass 1 of 2)"; hw-notes later: 1 stall, 2 passes. Not a fix. [OBSERVED: tag message; HN 2026-10-31 state of play]
16. Pulse-width histogram (tag archive/iec-pulse-hist, bfe1b1c, measurement only): CLK-high time per bit, buckets 1-6 (12-cycle buckets, about 25-85 us), "identical in the passing run and in five stalling runs, and matches VICE's stock 1541". Not "pulses too short". [OBSERVED: tag message; HN 2026-10-31 later: stall not in our receive loop]
17. Interrupts off while waiting for the talker (tag archive/iec-nocli, c27c188, "like the ROM"): did not help; listed as ruled out. [OBSERVED: tag message "hardware pending"; HN 2026-10-31 stall predates our work lists "interrupts off inside bus_acptr" under ruled out via docs/wip.md "Ruled out by experiment on the real drive"]. The sample size for this arm is MISSING.
18. About 10 ms gap before each attention sequence (tag archive/iec-gap, 5aaa753): "looks unhelpful: 2 of 2 stalled". [OBSERVED: docs/wip.md "Hardware session state"]
19. Interrupts off for the whole block read (tag archive/iec-irqoff, 213d5b3): queued/"hardware pending" in the tag; HN 2026-10-31 bisect says "(not yet run)". No result found in any document. [MISSING]
20. Stage 1 control (ROM's own ACPTR inside Breadbin, 44af149/07813bb) also stalls: "1 stall and 1 pass in two tries"; bisect table: stage 1 07813bb 1 pass of 5. Conclusion "The fault is not in bus_acptr." [OBSERVED: HN 2026-10-31 later; HN bisect table]
21. Regression bisect, 5 boots each, interleaved: upstream baseline aa58d27 1/5; M0-1 a5ad5dd 0/5; M0-3 9fd51a0 3/5; M0-4 stage 1 07813bb 1/5. "The stall is not something our changes introduced: the pre-fork upstream kernel has it." Caveat added later: 5 boots cannot tell 25% from 0-50%, so "supported, not shown". [OBSERVED: HN 2026-10-31 stall predates our work; INFERRED: the caveat, HN 2026-11-02 correction (3)]
22. Controls with the stock KERNAL's own code: LOAD of the 14,362-byte boot file 5 of 5 byte-identical (stockload.py); BASIC 393 sequential and 227 random-track U1 block reads, no stall; machine-code stress calling stock KERNAL routines in the kernel's exact sequence: 512 block reads over spread tracks; with EOI-only commands (CR=0): 512, no stall; with a slow IRQ handler (BURN=4, 5.2 ms per tick): 512, no stall; 512 reads of one block (track 16 sector 1): no stall; read of all 683 sectors, 0 errors; 16,000 single-byte GET# attention sequences (561 s), no wedge. Cumulative "1,600+ full block reads" with no stall vs "about one per 25 to 40 block reads under any Breadbin kernel". [OBSERVED: HN 2026-10-31 entries state of play / later / ruled out / not tied to blocks / REU-not-cause; HN 2026-11-01 more negatives; HN 2026-10-31 ROM before OEM swap]
23. Drive ROM: the physical drive's JiffyDOS 5.0 build differs from the Ultimate's JiffyDOS_1541-II.bin image: $FF00 window differs in two bytes (JSR targets at $FF31 and $FF5A); first two 256-byte windows identical to stock. Speed-mode byte $0023 = 00 on both. [OBSERVED: HN 2026-10-31 the physical 1541's ROM before the OEM swap]
24. OEM ROM swap (901229-05 installed, verified by $FF00 hash): "2 passes in 6, the same rate". [OBSERVED: HN 2026-10-31 stall predates our work]
25. REU disabled in the Ultimate (screen shows "reu: none"): 1 pass in 8 (vs 3 in 8 and 5 in 20 with REU on). [OBSERVED: HN 2026-10-31 REU is not the cause]
26. Command Interface (UCI registers) disabled: 1 of 8. [OBSERVED: HN 2026-11-01 more negatives]
27. The 1581's short IEC cable into the 1541's second IEC socket: 1 of 8. [OBSERVED: same]
28. Upstream kernel with its IRQ vector pointed at the ROM's own handler ($EA31): 2 of 8. [OBSERVED: same]
29. Drive RAM test ($0300-$06FF via M-W/M-R, 25 passes of 8 patterns, about 200 KB): 0 mismatches. [OBSERVED: same]
30. State comparison at a stall vs a BASIC machine (envdump.py): CPU port, CIA DDR/control, VIC mode/enable, SID identical; differences cosmetic plus interrupt vectors, KERNAL IEC bookkeeping, timers. [OBSERVED: same]
31. Screen blanking (BLANK=1 in dmaboot.py): round 1 still stalled (one sample); "not yet confirmed that the blanking took effect"; later called contaminated by its own DMA and "proves nothing". [OBSERVED: HN 2026-10-31 state of play; HN 2026-10-31 later]
32. Opus advisor hypothesis (VIC badlines/sprites swallow a ~34 us CLK-high pulse; try UI+ slow mode, M-R $0023, screen off, $DD00 capture): hypothesis only; later "not supported" by the pulse histogram. Tests (a) UI+, (b) M-R $0023 on both drives (done: both 00), (d) straight-line $DD00 capture: UI+ and the $DD00 capture were never run. [INFERRED: HN 2026-10-31 state of play; OBSERVED: the later contradiction in HN 2026-10-31 later]
33. ATN recovery probe (atnprobe.py): after a stall, point IRQ vector to a probe; UNTALK under ATN releases CLK; fresh TALK is answered and the rest of the buffer ends with a proper EOI; 3 stalls, 3 identical outcomes. "ATN is all it needs." [OBSERVED: HN 2026-11-01 ATN frees a stalled drive]
34. Recommendation 2026-11-01 to park the root-cause hunt: "more than 130 boots across about 30 conditions, each eliminating a hypothesis and none localising the cause". [OBSERVED: counts; INFERRED: the "rathole" judgement; HN 2026-11-01 more negatives]

### 1.4 Mitigation and measured rates after

35. Mitigation: `bus_acptr` ready wait bounded to about 2 s (three passes of a 256x256 loop, interrupts enabled; sets ST bit 1) and `iec_read` (blk.s) stops at the first timeout, sends UNTALK under ATN, and re-asks, up to three tries. Commit c2e13ca (as cited in HN) / 3d81693 (the same message, ancestor of this HEAD), authored 2026-10-31; merged as 0afbb8d on 2026-11-01 ("Merge fix/iec-recover ... Not run: VICE tests"). Cost +56 bytes. [OBSERVED: HN 2026-11-01 ATN recovery in the driver; git log]
36. First series: 8 of 8 boots reached login, 52 s each (unmodified kernel: "about 1 in 4 on the same drive and cable"). No counter of how often the retry fired. Image copied with mcdup (683 sectors verified, a little over 25 minutes). [OBSERVED: HN 2026-11-01 ATN recovery in the driver]
37. Cache A/B on main at the merge, make CACHE=0 vs CACHE=2, 5 boots each, alternating: 10 of 10, 52 s each. [OBSERVED: HN 2026-11-01 cache A/B on the physical 1541] Note: this 10 of 10 is not included in the "13 of 13" headline.
38. Module-loader tree 0a4dba1: 5 of 5 (32, 22, 22, 22, 22 s). Drive "still carries the OEM DOS ROM". Login time fell from 52 s to 22 s "not investigated which change did it". [OBSERVED: HN 2026-11-01 recovery fix after the module loader merge] "13 of 13" in CLAUDE.md/docs/wip.md = 8 + 5. [INFERRED: arithmetic; the sources do not break it down]
39. 2026-11-02 reassembled drive (DOS ROM chip swapped back to JiffyDOS, RF shield reseated, original cable, ferrite clamp at the drive end), main 67d0972, alternating kernel with the fix and with the two retry hunks reverted (git revert of c2e13ca): 6 of 6 with the fix (32, 22, 22, 22, 22, 22 s), 6 of 6 without (22 s each). [OBSERVED: HN 2026-11-02 reassembled 1541] Attribution to cable, clamp or ROM/shield reseat unknown. [OBSERVED: same: "which of the three changes ... removed it is not known"] The original text claimed 18% chance of six passes; corrected to 0.25^6 = 0.02% in the later entry "correction: the 12 of 12 arithmetic". [OBSERVED: HN 2026-11-02 correction]
40. 2026-11-02, tip cac322d: one boot 32 s (first boot after write), then 5 of 5 at 22 s. [OBSERVED: HN tip cac322d entries]
41. 2026-11-02, new runner, drive power-cycled by the user, main 939a83f: 5 of 5, 22 s each. Then nibbler write of that image, 1 boot 22 s. [OBSERVED: HN new runner: physical 1541 power-cycled; HN owner-open write]
42. 2026-11-02 earlier: image via nibbler on 71ac25f: 3 of 3 boots (32, 22, 22 s). [OBSERVED: HN our own c64fs image through the nibbler]
43. 2026-11-03, main 9ccef95 (image sha256 prefix 743fd1ac9103fb8b): R8 one boot 32 s. R13 on aadea2f (kernel identical): 5 of 5 (32, 22, 22, 22, 22 s), stopping rule fixed before boot 1. [OBSERVED: HN R8; HN R13]
44. Net after mitigation 2026-11-01..03: no stall recorded in any series. Stall-free runs recorded in HN: 8 + 10 + 5 + 6 + 6 + 1 + 5 + 1 + 5 + 3 + 1 + 5 + 1(+) ~ 57 boots (author's sum of the entries above; the records give no single total). [INFERRED: summation by this report]

### 1.5 After 2026-11-03: failures resume

45. 2026-11-06 (UCI mount run): with the physical 1541 on bus 8 and drive A on 9, the test backend's own boot (`load"*",8,1`, JiffyDOS KERNAL host) "stalled at `run` (no shell in 240 s)". Booting from drive A on bus 9 avoids it. [OBSERVED: HN 2026-11-06 mount uci /u PASS] The cause was not recorded.
46. 2026-11-06 and 2026-11-02: the read-only whole-disk checksum reader (disksum) on the physical drive stalled at sector 0 of 683, 5 times in total (four on 2026-11-02, one on 2026-11-06), with "no status byte from the drive" for the first U1; stock KERNAL host, Software IEC off. Closed by the owner as-is, not retried. See 2.7. [OBSERVED: HN 2026-11-02 disksum entries; HN 2026-11-06 physical-disk checksum read-back]
47. 2026-11-07 (main 8cc3e57, image sha256 prefix e5eba79c): see 2.1-2.5. Owner decision: accept, backlog a follow-up story for the boot path. "Not bisected." [OBSERVED: HN 2026-11-07]

## 2. Recorded failure modes and where in the boot they happen

Boot stages for reference: (a) machine KERNAL (stock or JiffyDOS) LOADs the boot file `breadbin` with `load"*",8,1`, in our code's absence; (b) our kernel starts and mounts root over our IEC driver (reads blocks through `iec_read`); (c) later: program loads and shell use. [INFERRED: stage definition from HN 2026-10-31 stage 2 against the physical 1541 and CLAUDE.md]

1. Root-mount stall (stage b): see 1.2. Reproduced pre-mitigation at about 3 boots in 4. [OBSERVED: HN 2026-10-31]
2. Root-mount "kernel panic: cannot mount root filesystem" (stage b): seen on the Ultimate with the emulated drive in 1 of about 14 harness boots, with $90 = $40 and bus lines released ($DD00 = $C7); attributed to harness DMA polling. [OBSERVED: HN 2026-10-31 stage 2 on hardware; INFERRED: the attribution to the harness]
3. Harness-polling corruption during program loads on the emulated drive (stage c): `sh: clear: exec format error` (stage 1) and stuck shell then `kernel panic: brk` (stage 2) within 3-5 loads of full-screen DMA polls; status $40 (EOI) each time. 1-byte reads: 24 loads, about 9,400 reads, no failure. 40-byte DMAs did not fix it (failed in the fifth load). [OBSERVED: HN 2026-10-31 stage 2 on hardware (hardware session)]
4. 2026-11-07, physical drive, solo on bus 8, after a full machine power cycle (HN 2026-11-07), five attempts:
   - a. Stock-KERNAL boot, one attempt: "stuck at LOADING, motor on, activity light solid" (stage a, the machine's KERNAL LOAD of the boot file). [OBSERVED]
   - b. Scratch-disk boot, one attempt: "stuck at LOADING, same look" (stage a). [OBSERVED]
   - c. Owner's manual boot: login prompt reached. [OBSERVED]
   - d. Agent boot, same config: `kernel panic: cannot mount root filesystem` after the kernel banner, interpreted as "the mitigation's retry budget was exhausted" (stage b). [OBSERVED: the panic; INFERRED: the retry-budget reading, since no retry counter exists]
   - e. Agent boot after next power cycle: "LOAD ERROR shown briefly, then a cleared screen. A new failure mode." Script stopped by the agent, rc 143 (stage a, the machine's KERNAL LOAD). [OBSERVED]
   Per the record, which KERNAL host was used for attempts c-e is not stated beyond "JiffyDOS KERNAL active" for the config. [MISSING: KERNAL host per attempt, order of events in time, time between power cycle and attempt, which drive power state]
5. The two LOADING hangs and the LOAD ERROR occur before our kernel runs (machine KERNAL LOAD of the boot file), so they are not in `iec.s` as shipped. [INFERRED from the words "LOADING", "LOAD ERROR" and the boot stages; the record does not say so]
6. ?FILE NOT FOUND / device-mismatch boot failures (stage a), expected causes not hardware: 2026-10-30 first boot (drive A on 9 vs load of 8); 2026-11-02 "?device not present error" with drive on wrong bus (94.7 s to wait_shell timeout). [OBSERVED: HN 2026-10-30 hw-bench; HN 2026-11-02 hardware owner takeover]
7. disksum reader stalls (outside the boot): the reader (stock-KERNAL calls: CHKOUT, CHROUT per char, CLRCHN, CHKIN 15, CHRIN) never got a status byte for `U1:2 0 01 00`; code read back intact; ZP corruption ruled out; a hand U1 from BASIC "hung once" but another worked; UI reset, directory load and hand U1 all worked afterwards. 2026-11-02 four stalls and 2026-11-06 one. [OBSERVED: HN 2026-11-02 disksum entries; HN 2026-11-06] Not ruled out: the call order vs BASIC and "BASIC-set state that a raw KERNAL sequence doesn't set". [OBSERVED as the record's own statement]
8. Tests ran through on the same hardware in the same period without stall: 2026-11-03 R8 physical boot 32 s; R13 5 of 5. [OBSERVED: see 1.4]

## 3. Hardware and configuration facts

1. Ultimate: C64 Ultimate, firmware 1.1.0, core 1.49 (from the illegal-ops entry); no REST password; reachable over the LAN. [OBSERVED: HN Setup; HN 2026-10-31 cache session request / REU-not-cause entry (core 1.49 in docs/wip.md "Cache session state")]
2. REU: the boot banner shows "reu: 32 x 64k" (= 2 MB; CLAUDE.md says 2 MB REU; LOAD REU tests used the end of 2 MB). The Setup table row "REU: configured size" is blank. [OBSERVED: HN 2026-10-30 tests on hardware; HN 2026-11-02 UCI LOAD REU at end of a 2 MB REU]
3. Command Interface (UCI) enabled; DOS target identifies as "ULTIMATE-II DOS V1.2"; control target "CONTROL TARGET V1.1". [OBSERVED: HN 2026-11-01 UCI as measured]
4. Machine KERNAL: JiffyDOS (`JiffyDOS-C64.bin`) in the normal state; stock KERNAL by setting Kernal ROM to "" and `machine:reboot` ("changing Kernal ROM over the REST config API does not take effect on machine:reset; it needs machine:reboot"). [OBSERVED: HN 2026-10-31 stage 2 on hardware; experiments/iec-stall/README.md "Running a hardware job"]
5. Normal configuration: JiffyDOS KERNAL, Software IEC on (device 11, /USB0/), drive A a 1541 with the JiffyDOS 1541-II ROM (`JiffyDOS_1541-II.bin`) on bus 9, the physical 1541 on bus 8, turbo off. Drive B disabled. "DMA Load Mimics ID" normally 8, set to 9 for ucirun runs. [OBSERVED: experiments/iec-stall/README.md; HN Setup; HN 2026-11-01 UCI v1 first run; HN 2026-10-31]
6. Boot-stall experiments configuration ("clean bus"): Drive A and Software IEC disabled, stock KERNAL host, 1581 removed, root on device 8, kernel loaded by DMA (`plainboot.py`/`dmaboot.py`, `$BA` mimicked as 8); a physical-disk boot via `load"*",8,1` was used in the 2026-11-07 attempts. [OBSERVED: HN various; experiments README]
7. Turbo: Off in experiments; turbo 4/16/48/64 MHz made no difference to the disk code ("the Ultimate holds I/O accesses to 1 MHz timing or the drive sets every pace" is INFERRED); the code needs 1 MHz. [OBSERVED: HN 2026-10-31 stage 2 on hardware; INFERRED: the explanation]
8. Software IEC setting: "Software IEC enabled" in normal state; disabled for clean-bus experiments and for nibbler copies; 2026-11-07 config: "Ultimate Software IEC off, drive A on bus 9 with no image, JiffyDOS KERNAL active". [OBSERVED: HN 2026-11-07; nibsetup.sh]
9. Devices ever on the bus: physical 1541 (device 8), Ultimate drive A, Software IEC (11), a physical 1581 (JiffyDOS 6.0, a "FNX 1581 clone", device 10; removed and "stays off until there is 1581 work"). [OBSERVED: HN 2026-10-30 drive probe; HN 2026-10-31 everything answers OPEN]
10. Drive replies: device 8 physical `73,JIFFYDOS 5.0 1541`; device 9 emulated `73,JIFFYDOS 5.0 1541`; device 10 `73,(C) 1989 JIFFYDOS 6.0 1581`; device 11 `73,U64IEC ULTIMATE DOS V1.1`. With stock ROM the emulated drive answered `73,CBM DOS V2.6 1541`. [OBSERVED: HN 2026-10-30 drive probe; HN 2026-10-31 stage 2 on hardware]
11. Physical drive model: "a long-board 1541 (second revision, twist-lock), JiffyDOS 5.0 installed"; its physical build differs from the emulated image (two JSR targets). [OBSERVED: HN 2026-10-31 the physical 1541's ROM before the OEM swap] The record does not give the drive's serial, motor/head condition beyond "quiet, clamp and head noise healthy", or age/maintenance.
12. Drive history: OEM `901229-05 (C)1983` ROM fitted at some point between 2026-10-31 and 2026-11-01 (8 of 8 and 5 of 5 were run with it); on 2026-11-02 the user put the JiffyDOS chip back (same chip as originally), reseated the RF shield, resealed the case, put back the original cable (long, "a repurposed synth cable", "exonerated earlier") and added a ferrite clamp at the drive end. [OBSERVED: HN 2026-11-02 reassembled 1541; HN 2026-11-01 recovery fix after module loader merge; INFERRED: "long, repurposed synth cable" is in HN 2026-10-31 stall predates our work paragraph on what is left]
13. Media: "fresh media" on first contact; the user's "usual disk" later; scratch disk (2026-11-07). The user said "may be overwritten". The disk is written with the Keymaster nibbler, results: directory lists `"breadbin" prg 58/59` and "0 blocks free" (design, not an error: all blocks marked used in the CBM BAM by mkimage). Whole-disk compare was never completed. [OBSERVED: HN 2026-11-02 entries; experiments README "Why the physical disk says 0 blocks free"]
14. Imagers: (i) a disk copier run by the user (first copy, 2026-10-31 stage-2 test); (ii) mcdup (our own sector-by-sector copier, 683 sectors, 25-27 minutes, verified by read-back; per-sector 2.3 s: 0.67 read source, 1.0 write, 0.67 verify); (iii) Keymaster dual-drive GCR nibbler v1.0 (BBI/Jim Drew, 1986) started by DMA-poke and RUN, 50 s to 3 minutes; copy is "byte-identical" for the files read back but the whole disk is not compared. Under VICE the nibbled disk is not readable (nibbler negative in VICE). [OBSERVED: HN 2026-11-01..02 entries; experiments README]
15. Images used in physical boot series (build ids): 45f1a72 (first), fix/iec-recover (c2e13ca/3d81693), 0a4dba1, 67d0972, 71ac25f, cac322d, 939a83f, 9ccef95/aadea2f (sha256 prefix 743fd1ac9103fb8b), 4ec614f/2a27321 (sha256 prefix bf504d94 in 2026-11-06 entries), 8cc3e57 (sha256 prefix e5eba79c, 2026-11-07). [OBSERVED]
16. Power/uptime state: no record of the Ultimate's uptime or of the drive's warm/cold state in the earlier series. Known: drive power-cycled by the user before the 2026-11-02 new-runner series; "full machine power cycle" before the 2026-11-07 attempts; nibbler renumbering is in drive RAM and reverts on reboot/UI. The runner host's load average was sampled once on 2026-11-02 (not the Ultimate). [OBSERVED: HN 2026-11-02; HN 2026-11-07; INFERRED/MISSING: whether warm vs cold drive matters; the 2026-10-31 cheap test "boot twice without power-cycling the drive" was suggested but no result is recorded]
17. PAL machine ("PAL, so count prints about every 1.2 s"); clocks at 1 MHz. [OBSERVED: HN 2026-10-30 tests on hardware]

## 4. Ultimate-side findings

### 4.1 Key drop

1. No key injection on the C64 Ultimate firmware 1.1.0: `POST /v1/machine:input` answers 404 (and a PUT probe). Real-keystroke tests (test_keyboard: xtype, xkey, xdown) cannot run on this product; the harness types by writing PETSCII to the key buffer ($0277, count $C6) by DMA. [OBSERVED: HN 2026-10-30 tests on hardware; HN 2026-10-31 key injection (the 404)]
2. The "key drop" on hardware: "The hardware drop is reproduced once (Ultimate, Boot test_09_errors); it is not yet reproduced on demand." On the Ultimate "the first character of a second 8-byte chunk was dropped once ('cat /nop' | 'e')". Rate "low", mechanism unknown. [OBSERVED: docs/testing.md Known issues, "Keyboard key loss: two classes", added 2026-11-06 in commit 465a89b] docs/why-this-fork.md: "A key drop on hardware has been seen once and not reproduced on demand." [OBSERVED]
3. In VICE the key-buffer boundary loss was "1 in 5 trials" (the Return of an 8-byte write); the capacity hypothesis (10-key buffer overflow) was tested (max 8 pending, no loss in 8 trials) and "is not supported". The count was taken through the monitor, which pauses the machine, "so it is a lower bound". [OBSERVED: docs/testing.md Known issues]
4. Separate class in VICE: xdotool-delivered keys after TAB completion not counted by the matrix scan; test_tab_no_match_does_not_fire red in setUp, a story since 2026-11-07. Delivery of xdotool events into VICE "is not confirmed". [OBSERVED: docs/testing.md; docs/wip.md Open items]
5. Earlier (2026-10-31) VICE keyboard loss, 2 in about 20 runs of test_keyboard, theory: xdotool press/release within ms in warp mode; fix keydown/60 ms/keyup (INFERRED). [OBSERVED: HN 2026-10-31 a flaky test seen under VICE; docs/wip.md "Known gaps" "lost keys twice in about 20 runs"]
6. Harness hazards for key writes: `keybuf` pauses the machine and resumes; a run that dies between pause and resume leaves the machine paused and `reset` does not unpause (fixed in UltimateTarget.boot). H6: "No glitch seen over about 15 runs of key-buffer typing." [OBSERVED: HN 2026-10-30 tests on hardware; HN Open questions H6]
7. DMA reads halt the CPU: a 1000-byte screen read during a disk transfer corrupted loads (see 2.3). Rule: no long DMA during a disk transfer. [OBSERVED: HN 2026-10-31 stage 2 on hardware]

### 4.2 Write-back (U2 not reaching the mounted image)

8. 2026-11-01, drive A (bus 9), image `/Temp/wb.d64` (RAM disk) mounted read/write, drive reset, `U2:2 0 1 1` answered `00, OK`; image fetched every second: "The block did not appear in the file": not within 45 s, not after closing channels, not within 30 s after unmount. [OBSERVED: HN 2026-11-01 image write-back timing]
9. 2026-11-02, drive B (bus 10), 512-byte image copy on the RAM disk, `U2` status `00, OK`; not in the file after 45 s, after 300 s, after a drive reset, or after unmount. "Q6 is closed as: no write-back of drive-modified images under these conditions." Not tried: SD-card image, a different write (full track, directory entry), a different host path. [OBSERVED: HN 2026-11-02 Q6 and Q6 variants] The cause is not established (emulated drive memory only / needs menu action / RAM disk handling differ) [INFERRED, listed as possibilities in HN 2026-11-01].
10. Related positive: formatting drive B (bus 10) from Breadbin via `format 10 c64fs` wrote "C64FS" at image offset 96256-96260 (R13e, 2026-11-04) when the image was mounted readwrite; the earlier R13d FAIL was a retracted misreading (format refused on a mounted drive). So some writes did reach the file in that run. [OBSERVED: HN R13e; HN R13d correction] The relation between R13e success and Q6 non-write-back is not discussed in the record. [MISSING]

### 4.3 UCI results (firmware 1.1.0, Command Interface on)

11. Latency: IDENTIFY 2.4 ms, OPEN 4.3-4.8 ms, CREATE about 55 ms, CLOSE about 1 ms. Throughput (tight loop): read 44.0-44.8 KB/s (status per byte), 61.6-63.3 KB/s blind; write 64.8-65.1 KB/s; LOAD REU 32 KB 6.2 ms, 512 KB 44.4 ms (11.8 MB/s). The first 16 KB/s figure was "my measuring loop, not the interface". [OBSERVED: HN 2026-11-01 UCI entries]
12. Interrupt on completion "not usable as documented": the interface did not return to idle and the next command timed out (100 s); poll instead. DMA bit ($DF1C bit 7) is accepted and harmless but gives no data path. [OBSERVED: HN 2026-11-01 UCI as measured; UCI control bit 7]
13. FILE STAT by name answers `82,FILE NOT FOUND` for just-written files and for relative names after CHANGE DIR; absolute names work for directories; cause not found. OPEN DIR ignores its path and lists the current directory. READ DIR returns one entry per chunk (23 chunks, 217 bytes, status $30 more / $20 last), re-lists every call; ABORT stops a listing after its chunk; names to 15 chars come back whole. RENAME onto an existing name answers FILE EXISTS. LOAD REU of 512 bytes at $1FFF00 (256 past 2 MB) answers `00,OK` with 512 reported; behavior of the overrun not measured. DELETE on a non-empty directory answers ACCESS DENIED. [OBSERVED: HN 2026-11-01 UCI v1 assumptions; HN 2026-11-02 UCI directory commands / READ DIR / ABORT / Q4 / Q7]
14. Kernel UCI v1 module on the real Ultimate: `mkdir /u`, `mount uci /u`, `ls /u` (SD Flash Temp), `cat`, `cp` both directions (35,840 bytes byte-identical), `rmdir`, `umount` freeing the module; with Command Interface disabled `mount uci /u` answers "no such device or no disk". 2026-11-06 repeat on main 2a27321: PASS. [OBSERVED: HN 2026-11-01 UCI v1 in the real kernel; HN 2026-11-01 kernel module loader and exec; HN 2026-11-06 mount uci /u PASS]
15. A 40,000-byte cp stopped at the c64fs file size limit (35,840 bytes kept, "cp: file too large"). [OBSERVED: same]
16. UCI disk-full (Q4) and Q9 (turbo with UCI) remain open. [OBSERVED: docs/wip.md Open items]
17. Effect of the UCI registers on the 1541 path: none seen (stall rate same with Command Interface disabled, 1 of 8). [OBSERVED: HN 2026-11-01 UCI as measured item 7]

### 4.4 What passes on the Ultimate; what is unverified

18. Boot (4 tests: test_02_echo, test_07_directories, test_10_mv_cp, test_13_ctrl_c_blocked_reader) all OK: 160.7 s (tip cac322d, 2026-11-02); R8 4 of 4 with physical drive renumbered (2026-11-03, 9ccef95, together 274 s with console). Console (6 tests) all OK: 137.5 s. [OBSERVED: HN 2026-11-02 informal timings; HN R8]
19. Stage-2 driver against the emulated 1541 with JiffyDOS and stock ROMs: boots to login. Times: stage 1 JiffyDOS 46.5 s / stage 2 JiffyDOS 75.5 s; stock ROMs 122 s both. Stage 2 is about 2x slower than stage 1 on JiffyDOS (stage 1 used JiffyDOS fast protocol). [OBSERVED: HN 2026-10-31 stage-2 driver on hardware]
20. Illegal opcodes: 21 of 21 pass; unstable ones not checked. [OBSERVED: HN 2026-10-31 REU is not the cause]
21. `mount 10 /mnt` + `format 10 c64fs` + magic read-back (R13e): PASS 2026-11-04. [OBSERVED]
22. Untested or impossible on the Ultimate (as recorded): `tests.test_keyboard` (impossible, H2); Exec/Modules/Persistence/Cache/REU/Pool/Drives classes (VICE-only: `Vice(...)` in tests/test_system.py; "all 7 errored" when pointed at the Ultimate); JiffyDOS-ROM test set on hardware; warm-cache boot benefit on hardware (CACHE=1, second boot); `format` on physical media; `mount 9 /mnt` of a second drive; video stream (H9); 1581 from Breadbin (H10); a full Boot class beyond the four tests; the whole-disk compare of the physical disk; more than 1 boot of main at the 2026-11-07 tip that succeeded in automation. [OBSERVED: HN various "Not run" lines; docs/wip.md; docs/testing.md]
23. Firmware quirks: Kernal ROM change needs machine:reboot not reset; runners:run_prg/load_prg reset the machine and un-renumber a software-renumbered 1541; 1581 or a switched-off attached device changed results. [OBSERVED: HN various]

## 5. What our IEC code does (src/kernel/iec.s, src/kernel/blk.s at 78fcaa2)

General: standard protocol only, no JiffyDOS or fast-loader handshakes; bit-bang on CIA2 port A ($DD00); written "from the published protocol and timing table (the CBM IEC bus description in MAME's cbmiec.cpp), not from the KERNAL" (iec.s lines 1-26). Needs a 1 MHz CPU; "turn turbo off around bus use" (iec.s line 25). The file last changed on 2026-11-04 (a9c1c96, REU root); the bus-level code is unchanged since 3d81693 (2026-10-31). The commit ff69a25 (2026-11-02, "catches a fast drive's short CLK pulse at the talk turnaround", polling CLK every 11 cycles) and 7bc197a (fast reads from drive 8) are NOT ancestors of this HEAD (they exist on upstream refs only); docs/why-this-fork.md lists them as upstream's. [OBSERVED: git merge-base checks; commit message of ff69a25]

### 5.1 Mitigations, with locations

1. Bounded ready wait in `bus_acptr`: iec.s lines 346-364 (`cli`; `io_n`=3; Y and X count from 0; `@rdy` loop at 355-360; `dec io_n` 361; on exhaustion `sei` and `jmp @tmo`). Loop is `bit PORT` (4) `bvs` (2 not taken) `dex` (2) `bne` (3) = 11 cycles, 3 x 65,536 passes, about 2.2 s at 1 MHz (computed by this report; the source comment says "about 2 s"). Assumes: a busy drive may take "as long as it likes" to finish a command (about 100 ms per block read, per docs/roadmap.md M0-4) and a stalled drive holds CLK until ATN. [OBSERVED: source; INFERRED: the 2.2 s computation]
2. Per-bit waits inside a byte: `ldy #0` 256-iteration loops (iec.s 396-412), each about 256 x 12 cycles = 3.1 ms; on expiry `@tmo` sets ST bit 1 (line 420-422). Assumes the talker's inter-bit gap is under about 3 ms. The 0.8 s variant (02339eb) was reverted. [OBSERVED: source, commit 02339eb; INFERRED: cycle arithmetic]
3. EOI detection window: `ldy #90` (iec.s 369-373) about 1.1 ms; after EOI the wait for CLK low is 256 x 256 passes (iec.s 385-393) about 0.7 s then `@tmo`. Assumes the talker answers within 200 us unless EOI ("wait ~1 ms to be sure"). [OBSERVED: source comment]
4. Retry with UNTALK in blk.s: `iec_read` (about lines 569-582) loads `rd_try`=3, calls `iec_read1` (584-608: sends `U1:2 0 t s` via `cmd_send`, reads the drive status via `cmd_status`, `iec_in_begin` with secondary 2, 256 bytes through `iec_in_byte`, testing ST bit 1 after each byte); on failure `@redo` calls `iec_in_end` (= `bus_untlk`, iec.s 321-327, UNTALK $5F under ATN via `io_last`) then retries; on the third failure returns carry set. No delay between the UNTALK and the re-issued U1. Only ST bit 1 (timeout) is tested; ST bit 6 (EOI) on byte 256 is not tested; a bit sampled wrongly without a timeout would pass silently. [OBSERVED: source; the silent-error limits OBSERVED as "Nothing in the driver changed for these" in HN 2026-11-02 correction]
5. No retry counter or diagnostic of how often the retry fires. [OBSERVED: HN 2026-11-01 "no counter"]
6. `cmd_status` (blk.s ~543-566): reads the error channel, ends with `iec_in_end` (UNTALK). Unbounded elsewhere: `bus_tksa`'s wait for the device to take the clock (iec.s 261-263, `bit PORT / bvs @w`, no count; comment "it has answered both bytes, so wait as long as it takes") and `io_tx`'s wait for listener ready when `io_inf`=1 (lines 120-123, "a device that has answered ATN is there, only busy"), and the format-style waits with interrupts off. So a stall at the talk turnaround or in a command send can still hang forever. [OBSERVED: source; INFERRED: the consequence "can still hang", not recorded as seen]
7. Interrupt use: `cli` only in the `bus_acptr` ready wait; otherwise `sei` during bus transactions (bus_first, bus_second, bus_tksa, bus_ciout, bus_unlsn, bus_untlk). A busy drive can stop the clock and keyboard. Interrupts are off while talker so "an interrupt in that window would corrupt the transfer" (iec.s 20-24). [OBSERVED: source comments]
8. ATN start: `io_atn_begin` (82-100) waits `ldy #96` (about 1 ms) for a device to pull DATA, preceded by `dly` D_TBB. [OBSERVED: source]

### 5.2 Timing constants

Delay routine `dly` (iec.s 71-73): X x 5 cycles plus about 14 for the call (iec.s line 33).
| Constant | Value | Approx time (computed) | Spec comment in source |
|---|---|---|---|
| D_TS | 8 | 54 us | bit set-up (>= 20 us) |
| D_TV | 10 | 64 us | bit valid (>= 20 us, 60 for a talker) |
| D_TBB | 20 | 114 us | between bytes (>= 100 us) |
| D_TR | 4 | 34 us | frame to release of ATN (>= 20 us) |
| D_EOIH | 14 | 84 us | hold DATA to acknowledge EOI (>= 60 us) |
[OBSERVED: source constants and comments; INFERRED: the microsecond figures were computed by this report at 1 MHz, the notes quote "set-up about 55 us, valid about 65 us" in HN 2026-10-31 request for the hardware session]
Other loop counts: `io_tx` listener-ready wait `io_to`=4 x 65,536 passes about 2.9 s then fail unless `io_inf` (lines 108-125); EOI wait 200 passes (about 2.4 ms) then 96 (about 1.1 ms) for the listener's DATA release (lines 128-139); ack wait 200 passes (lines 169-175). [OBSERVED: source; INFERRED: ms computed]

Tuning: HN states the bit timing is "the middle of the published windows" and assumes a 1 MHz CPU. The constants are tuned to the published (stock) windows, not to a JiffyDOS drive. The three JiffyDOS-drive problems found under VICE (talk turnaround as one write; wait without limit for a busy device; about 1 ms EOI window) were protocol corrections validated against JiffyDOS 6.01 drive ROM images in VICE, not a timing retune. The stock-vs-JiffyDOS result on the real physical drive: stall observed with the JiffyDOS 5.0 drive ROM and with the OEM ROM at the same rate. [OBSERVED: iec.s header; docs/roadmap.md M0-4 "What the JiffyDOS drive ROM taught us"; HN 2026-10-31 stall predates our work]

Drive-side: a talker sends a byte in about 1.8 ms; a block read about 0.55 s; boot reads about 70 blocks. [OBSERVED: docs/roadmap.md "Disk speed"]

## 6. Open questions the records flag, and contradictions

### 6.1 Open questions stated in the records

1. Root cause of the physical-1541 stall: "mitigated, not root-caused". [CLAUDE.md; wip.md]
2. Which of {original cable restored, ferrite clamp, ROM chip reseated + RF shield} removed the stall on 2026-11-02; proposed experiment: undo one factor at a time, 8 boots per arm on the unfixed kernel. Not run. [HN 2026-11-02 correction]
3. Why login time dropped from 52 s to 22 s between the early series and 0a4dba1 (OEM ROM still fitted). Not investigated. [HN 2026-11-02 correction; HN 2026-11-01 recovery fix]
4. How often the retry fires in boots; whether a stall can complete silently with wrong bytes (single DATA read per bit; EOI on byte 256 not tested; logging bit 6 on byte 256 suggested). [HN 2026-11-02 correction]
5. Were the stock-KERNAL stress runs started after a reset into a drive state different from the DMA-loaded Breadbin runs? How each was started is not recorded. The converse test (stock stress with Breadbin's IRQ handler) was not run. [HN 2026-11-02 correction, points (1), (2)]
6. A second physical 1541 or another C64: "the cheapest high-value datum there is"; not done. [HN 2026-11-01 recommendation]
7. Reopen conditions for the hunt: (1) second drive/C64; (2) Classic reliability becomes a ship criterion; (3) fast-loader work needs the bus understood; (4) stall on emulated drive or UCI design. [HN 2026-11-01 more negatives]
8. Whether the 1581 is the cause of earlier results: "the 1541 stall results are not trustworthy" with the 1581 attached. [HN 2026-10-31 OPEN scare]
9. The 2026-11-07 failures: not bisected; whether the 2 LOADING hangs and the LOAD ERROR are the same as the old stall; whether the power cycle matters; follow-up story backlogged (details MISSING). [HN 2026-11-07]
10. Physical-disk contents never compared sector-by-sector: disksum reader stalls at sector 0; cause unknown; closed by the owner as-is. [HN 2026-11-02, 2026-11-06; docs/wip.md "Physical-disk compare: parked"]
11. Write-back path (Q6) is closed under tested conditions; SD-card image and other writes untested. [HN Q6]
12. The 25-minute copy: fast write path wanted (owner). Nibbler path partly replaces it (50 s to 3 min). [docs/wip.md Known gaps]
13. JiffyDOS-drive series and JiffyDOS-ROM test subset on the final tip are "the open milestone gates" (CLAUDE.md "Status"); hardware list not run at the final tip except boot, test_02 etc. [CLAUDE.md]
14. Hardware key drop: seen once, not reproduced; mechanism unknown. [docs/testing.md]
15. Whether `mount 9 /mnt`, `format`, JiffyDOS drive tests etc. on the physical drive; and the drive's cleanliness/maintenance. [HN various]

### 6.2 Contradictions and stale statements between documents

1. JiffyDOS drive ROM version: docs/roadmap.md M0-4 says "the Ultimate's drives all run JiffyDOS 6.01". HN 2026-10-30 drive probe: emulated drive A and the physical drive answer `73,JIFFYDOS 5.0 1541`; only the 1581 answers JiffyDOS 6.0. (The 6.01 figure could be the ROM-image name used in VICE tests; the records do not reconcile it.)
2. docs/wip.md "Known gaps at the first milestone" (written 2026-11-01) says "Agent 2's JiffyDOS-drive A/B (with and without the mitigation) is the open test"; HN 2026-11-02 "the reassembled 1541 with the JiffyDOS ROM" records it (6 of 6 with and 6 of 6 without). The wip text is stale and its page header says the state blocks are "history, kept as written".
3. CLAUDE.md "Status" says the mitigation "took it from about 1 boot in 4 to 13 of 13"; the latest record (HN 2026-11-07) says it is "not reliable enough to call solid", and docs/why-this-fork.md (updated for 2026-11-07) says the release "does not claim an automated physical-1541 boot". CLAUDE.md is not updated for 2026-11-07.
4. docs/wip.md "Snapshot (main 45eacff, 2026-11-03)" says the physical 1541 "boots the tip image to login in 22 s (5 of 5 on 2026-11-02...)"; the same wip snapshot says the whole-disk reader "stalled four times at sector 0"; HN 2026-11-06 adds a fifth. Counts differ by date, not inconsistent.
5. 13 of 13: CLAUDE.md does not say it was run with the OEM DOS ROM fitted (8 of 8 inferred, 5 of 5 stated); docs/wip.md calls the open item the "JiffyDOS-drive A/B". The 13 includes no 10-of-10 cache A/B and no 6-of-6 JiffyDOS-ROM runs. [INFERRED from HN]
6. Commit ids: HN cites the mitigation as c2e13ca; this HEAD contains 3d81693 (same message) and merge 0afbb8d. c2e13ca is not an ancestor of HEAD. The tag archive/iec-bit-waits message says "shorter blind window" while docs/wip.md lists `iec-bit-waits` as "0.8 s bit waits"; 02339eb is the 0.8 s change, 3bf517d reverts it.
7. docs/roadmap.md M0-4: "a device that has answered attention is waited for without a limit"; the mitigation bounded `bus_acptr`'s ready wait but `bus_tksa` and `io_tx` (inf) still wait without limit (source). Roadmap does not mention the bound. [source vs doc]
8. docs/wip.md "Hardware session state" says the stall hits "most boots" and "about one boot in four or five passes either way"; HN gives 5 of 20 overall and series ranging 1 to 3 of 8. Consistent in rate, but 3 of 14 vs 5 of 20 vs "1 in 4" differ in how counted.
9. HN 2026-10-31 "state of play" says the likely cause could be missing short CLK pulses; the "later" entry of the same day says this is "not supported" (pulse histogram). The "state of play" text is kept (append-only log) but superseded.
10. HN header "Setup" table leaves REU size, Command Interface, Turbo and run-host rows blank while later entries and CLAUDE.md give 2 MB REU, Command Interface enabled, turbo Off. Stale table.
11. HN 2026-11-02 "disksum" says the reader stalled "before the first status byte" using stock KERNAL calls; elsewhere stock KERNAL code is the "control" that never stalls (HN 2026-10-31). The records do not reconcile this (they list the call order as unruled-out).
12. Entries out of order: the 12-of-12/18% correction appears at the end of the log, after the 2026-11-04 entries, although dated 2026-11-02. Also HN contains a duplicated "Cache, REU, Pool: 11 of 11 OK, 735 s" paragraph within the 2026-11-02 milestone-gate entry. [HN]
13. docs/testing.md says the Ultimate key drop occurred in Boot test_09_errors; HN has no entry for it; the date is undocumented there (the section was added 2026-11-06 in 465a89b).
14. docs/design/fast-io.md line 137 repeats the earlier "5 of 7" and "stock-KERNAL control in progress" wording; superseded.

## 7. Tools in the repo for hardware experiments

### 7.1 Rules
1. Lock: `tools/with-lock -r ultimate -- <command>`; one holder at a time; `-t SECONDS` limits the wait (exit 75 on timeout; default wait an hour); lock files in `$BREADBIN_LOCKDIR` (default `/tmp/breadbin-locks`). Hardware runs "announce the write first, restore the configuration by trap, and read it back". [OBSERVED: tools/with-lock header; docs/process.md "The machine lock"; docs/wip.md "Rules of the road"; experiments/iec-stall/README.md]
2. Never read the screen with long DMA during a disk transfer; do not run other VICE instances during timing tests. [experiments README; CLAUDE.md]
3. Address: via `BREADBIN_ULTIMATE` or gitignored `.breadbin-local.env` at the repo root (read by tools/ultimate.py `load_local_env`). Never commit it. [tools/ultimate.py; experiments README]
4. A/B method: alternate variants on the same drive, at least five of each; "one run says nothing". Fix count and stopping rule before boot 1 (R13). [experiments README; HN R13]
5. Normal state to restore after every run: JiffyDOS KERNAL (`JiffyDOS-C64.bin`), Software IEC on, drive A 1541 JiffyDOS 1541-II ROM on bus 9, physical 1541 on bus 8, turbo off, "DMA Load Mimics ID" 8. Kernal ROM change needs `machine:reboot`. [experiments README]
6. Physical-disk writes: owner's go needed per write (write-physical.sh header); the physical disk is overwritten.

### 7.2 Scripts (experiments/iec-stall/, all take `BREADBIN_ULTIMATE`)
- `plainboot.py IMAGE.prg`: DMA boot, root on device 8, reports "OK login after Ns" or STUCK (170 s limit) and appends a stall dump if the kernel has the IEC variables. No DMA read for the first 20 s.
- `dmaboot.py IMAGE.prg` (+ `IMAGE.lbl`): like plainboot, dumps IEC variables and stack on stall; `BLANK=1` turns the screen off.
- `decode.py IMAGE.prg`: decodes stall dumps. `stockload.py build/breadbin.prg`: control, 5 stock-KERNAL loads compared byte-for-byte.
- `cabletest.sh LABEL [N] [IMAGE.prg]`: N plainboot runs, appends `RESULT LABEL: k of N passed` to a results file, config restored by `trap restore EXIT`.
- `bisect.sh COMMIT [N]`: builds a commit in a worktree, writes its image with mcdup, boots N times, restore trap.
- `atnprobe.py`, `romwin.py`, `envdump.py`, `drvram.sh/.s/.py`, `mcscan.s/.py`, `bench_basic.py` (feed/screen helpers), `uci.s`/`uci.py`/`ucirun.py`/`ucirun.sh` (UCI bench; ucirun.sh sets DMA Load Mimics ID 9 and restores by trap).
- Disk copy: `mcdup.sh`/`mcdup.py` (slow, verifying, 683 sectors 25-27 min; `--base IMAGE` copies only differing sectors), `nibsetup.sh up|down`, `nibtest.py`, `nibcopy.py`, `write-physical.sh IMAGE.d64` (preflight, takes the lock itself, EXIT-trap restore; exit 0/1/2). Nibbler PRG (not in git) via `NIBBLER=<local path>`.
- `disksum/disksum.py` + `disksum.s` (read-only whole-disk checksum compare; stalls at sector 0; host test `python3 -m unittest experiments/iec-stall/disksum/test_disksum.py`, 8 tests).
- `tools/ultimate.py`: REST client (`Ultimate`, `from_env`, mount/readmem/writemem/pause/resume/reset/reboot/run_prg/drives etc.). `tools/ultimatetest.py`: `UltimateTarget` (same interface as `tools/vicetest.py`; `boot()` mounts image, resets, types `load"*",<BREADBIN_ULTIMATE_BUS or 8>,1`, `run`); `tools/fake_ultimate.py` is the test fake.
- Tag-archived kernel experiments: `archive/iec-bit-waits`, `iec-gap`, `iec-irqoff`, `iec-nocli`, `iec-pulse-hist` (each one commit; see 1.3).

### 7.3 How a run is started (commands only)
- Host tests first: `make test-host`.
- Boot-series on the physical drive (stock KERNAL, clean bus):
  `tools/with-lock -r ultimate -- sh -c 'BREADBIN_ULTIMATE=<set> python3 experiments/iec-stall/plainboot.py build/breadbin.prg'`
  (configuration by hand or via `cabletest.sh LABEL N IMAGE.prg`, which sets it and restores).
- Write an image to the physical disk:
  `BREADBIN_ULTIMATE=<set> NIBBLER=<local nibbler PRG> experiments/iec-stall/write-physical.sh build/breadbin.d64`
- Boot Breadbin on the Ultimate without keys: `ucirun.sh 'cmd' ...`; tests: `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=<set> python3 -m unittest tests.test_system.Boot.test_02_echo ...` (run from the `tests/` directory per HN R8), with `BREADBIN_ULTIMATE_BUS=9` if drive A is on 9. Hardware list: HN "Hardware list".
- Check a class's target (`grep -n "Vice(\|make_target" tests/test_system.py`) before a hardware run: only Boot, keyboard, console use `make_target`.

## 8. Biggest gaps in the records (summary; also in the final message)
1. No record explains which environmental change (cable, clamp, ROM reseat, power state) or which code behavior produced or removed the stall; the 2026-11-02 one-factor-at-a-time undo experiment and a second drive/C64 were never run, and the 2026-11-07 failures were not bisected or characterised (no KERNAL host per attempt, no timeline, no counter for retries).
2. No instrumentation of the mitigation: no retry counter, no EOI/byte-256 check, no logging of where the stall occurs now; so "13 of 13" and "5 of 5" cannot say how often the stall still occurs or whether retries fire, and the whole-disk compare of the physical disk was never completed.
3. Ultimate-side: the key drop is one sighting with no repro and no hardware keyboard-scan test possible (no key injection); write-back lacks the SD-card/other-write variants and does not reconcile with the successful R13e format write; no uptime, power or thermal state recorded for the Ultimate or drive.
