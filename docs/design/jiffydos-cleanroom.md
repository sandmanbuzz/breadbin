# JiffyDOS host protocol: clean-room sketch

Status: paper. Source of truth: Michael Steil, *Commodore Peripheral Bus, Part 7: JiffyDOS* (`mist64/cbmbus_doc`, "7 JiffyDOS.md"), which gives the state machines and cycle tables for the C64 and the 1541. This is a sketch of a ca65 implementation for `iec.s`, not code.

**Clean-room hygiene.** While scoping, the author of this sketch read the LGPLv3 open-roms implementation (`jiffydos_tx_byte.s`, `jiffydos_rx_byte.s`, `jiffydos_detect.s`). Under the licence policy in `CLAUDE.md` (no LGPL) that makes this session a poor place to *write* the routines. The numbers below were taken from the cbmbus_doc tables, but the implementation should be written by an agent or person who sees only this file and cbmbus_doc, and checked against a bus trace from VICE with the JiffyDOS ROMs, not against open-roms.

## 1. What `iec.s` already has

`$DD00`: outputs bit 4 = CLK out, bit 5 = DATA out, 1 = assert (line low); inputs bit 6 = CLK in, bit 7 = DATA in, true level (1 = line high/released). VIC bank bits 0..1 and the other bits must be kept. `io_set`, `dly`, `bus_listen`, `bus_talk`, `bus_second`, `bus_tksa`, `bus_ciout`, `bus_acptr`, `io_inf` (ATN bytes, unbounded wait), per-device state in BSS. Interrupts are already off on the send path.

## 2. Detection (per TALK/LISTEN, valid until UNLISTEN/UNTALK)

Spec: before the last (8th) bit of the TALK/LISTEN byte, with CLK released, hold for about 400 us instead of 60 us (cbmbus_doc footnote: ~410 cycles NTSC). A JiffyDOS device in that window pulls DATA for about 100 us. Others ignore it.

Sketch: in the ATN byte loop, at bit 7 (the last) of a command byte whose high bits are `%001`/`%010` (LISTEN/TALK; the code point is known before the loop starts), replace the 60 us hold by a polling loop: about 36 iterations of `lda $DD00 / bmi-or-bpl / dey / bne` (11 cycles) sampling DATA; if DATA goes low inside the window, note `jiffy_seen`, wait for it to release, continue with the last bit. After the command completes, store `dev_jiffy[dev] = jiffy_seen` (one flag byte per active talker/listener, or a single "current session is jiffy" flag, since only one device is addressed at a time).

Cost: +400 us per TALK/LISTEN. Our protocol already pays about 1.8 ms per byte, so the overhead is noise. The side effect is harmless to non-JiffyDOS devices by the spec (the standard protocol only fixes a minimum delay).

**Bench caveat** (corrected 2026-10-31): the hardware session first reported that every device number answers ATN, then retracted it (the test sent nothing on the bus). The open item is a stall on the physical 1541, not yet localised. A false JiffyDOS positive is still possible with a noisy DATA line, so the rule stands: the session flag is set only if the *device also acknowledged the command byte normally* (the existing present check), and the first real transfer must succeed; any error in a jiffy transfer clears the flag and retries once on the standard protocol.

## 3. Byte send (LISTEN session, controller to device)

Spec states S0..S8. Wire values below are line levels (1 = released/high); the C64 output bits are the inverse (1 = assert), so each output byte is `base | ((~data_pair) << 4)`, with CLK at bit 4 and DATA at bit 5.

| Step | Controller does | Pair on the wires (CLK, DATA) | Hold (cycles, C64 column) |
|---|---|---|---|
| S1 | wait for device to release DATA (ready) | | any |
| S2 | *Go*: release CLK | | ≥30 after S1 is seen |
| S3 | first pair | CLK=#4, DATA=#5 | 11 |
| S4 | second pair | CLK=#6, DATA=#7 | 13 |
| S5 | third pair | CLK=#3, DATA=#1 | 11 |
| S6 | fourth pair | CLK=#2, DATA=#0 | 13 |
| S7 | EOI/!EOI: pull CLK (no EOI) or keep released (EOI), then DATA released/pulled as the spec's S7/S7a describes | | 13 to 14, longer for EOI |
| S8 | read the device's OK: DATA pulled = OK, released = error | | sample ~19 cycles after S7 |

The sender precomputes four output bytes before S1 (with the stores spaced by NOPs to at least the hold times above; a plain `lda zp / sta $DD00` pair takes 7 cycles and is too fast), so the window itself contains only stores. Pair S3 is simply `(~data) & $30` (bits 4,5 of the data byte already sit at bits 4,5); S4 is `((~data) >> 2) & $30`; S5 and S6 need the low nibble shuffled (bit3,bit1 and bit2,bit0), best done with two 16-byte tables indexed by `data & $0F`, which also folds the inversion in.

The 63 us window requires: interrupts off (already the case), sprites off (their DMA steals cycles; save `$D015`, write 0, restore), no badline in the window (wait on `$D012` for a line where `(line & 7) != 3` style safe positions, or blank the screen with `$D011` bit 4; open question below), and 1 MHz CPU.

## 4. Byte receive (TALK session, device to controller)

| Step | Who | What |
|---|---|---|
| R1 | device | releases CLK when it has the byte |
| R2 | controller | *Go*: release DATA (≥31 cycles after R1 seen, in a clear window) |
| R3..R6 | device | puts four pairs on CLK/DATA: (#0,#1), (#2,#3), (#4,#5), (#6,#7), **all inverted** |
| R7 | device | EOI/!EOI on CLK, DATA |
| R8 | controller | pull DATA again (3 cycles after the window) |

The controller samples `$DD00` four times at about 16, 10, 11, 11 cycles after Go, with no processing in between (store each in a register or zero page). Our inputs are true levels, so the bit values are the inverted levels: with samples `s0..s3`, each holding DATA in bit 7 and CLK in bit 6,

```
byte = ~( (s0 >> 6) | ((s1 >> 4) & $0C) | ((s2 >> 2) & $30) | (s3 & $C0) )
```

(derivation: the pair (CLK=NOT bit0, DATA=NOT bit1) lands at bits 6,7 = bits 0,1 after `>> 6`; the others shift likewise). Everything after the fourth sample is outside the window and can use ordinary code. EOI and error are decoded from the last sample as the spec's R7 / "both released means error" rules say; the exact encoding must be settled against a bus trace, since the text of the spec differs slightly between its prose and its table.

## 5. LOAD

Not needed. `blk.s` reads blocks, the LOAD protocol skips the load address and holds the CPU in a busy-wait. Out of scope.

## 6. Integration points

- A flag `bus_jiffy` (BSS, one byte). `bus_ciout` branches to `jif_tx` when set; `bus_acptr` branches to `jif_rx` when set. All other code (`iec_ch_*`, `blk.s`) is unchanged.
- `bus_talk`/`bus_listen` run detection (section 2). `bus_unlsn`/`bus_untlk` clear the flag.
- A kernel option to disable the whole thing (a one-line constant) so that tests can compare the two protocols on the same JiffyDOS ROM.
- Size estimate: tx 90 to 110 bytes, rx 90 to 110, detection 40, tables 32, glue 30: **about 300 bytes**, and the common helpers (sprite save/restore, safe-line wait) are shared by any future drive-side loader.

## 7. Verification plan

1. **Reference trace.** VICE with the JiffyDOS ROMs, true drive emulation, a tiny program that does a standard JiffyDOS-ROM LOAD / reads a file. Capture CLK/DATA edges with timestamps (VICE `-iecdevice`/monitor trace or the `serial.c` debug log; for exact cycles, a patched VICE or `-moncommands` breakpoints on `$DD00` accesses). The point is to get the real bytes-on-the-wire for the first few bytes, including EOI.
2. **Host unit test** in `make test-host`: a Python model of the send/receive state machines driven by those traces; verifies the bit order tables (`jif_tx` pair values for all 256 bytes) without an emulator.
3. **VICE test** with the JiffyDOS ROMs in the drive and the standard C64 ROM: boot, `ls`, `cat` of the biggest file, compare content with the standard protocol; boot time.
4. **VICE negative tests:** stock drive ROM: detection negative, standard protocol used, no timeouts. No drive: unchanged behaviour.
5. **Hardware** (the bench): real 1541 with JiffyDOS ROM; the Ultimate's emulated drive with JiffyDOS ROM loaded (`drives/a:load_rom`). Expected: boot time down from 75.5 s toward the stage-1 figure of 46.5 s or better.

## 8. Open questions

1. Safe window on a PAL/NTSC C64 with the screen on: wait for a raster line, or blank for the transfer? The device waits indefinitely at S2, so waiting for a safe line costs time but not correctness; the decision is empirical.
2. Do we keep the jiffy clock (`$A0..$A2`) and keyboard scan accurate across a window? Interrupts are off for ~60 us per byte, which is invisible, but the per-byte setup (about 150 us) adds up over a block; at 256 bytes that is 40 ms with interrupts off between windows if we do not re-enable them. Re-enable between bytes (`cli`/`sei` pair) or accept a 50 ms stall per block (the same trade the original JiffyDOS makes).
3. EOI / error encodings: settle with the trace.
4. The physical-1541 stall (hardware session, in progress); the probe must not make it worse.
