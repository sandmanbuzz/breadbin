# SJD41 drive-side block module: field notes and proposed contract

Status: research/implementation branch, **not hardware validated**. This document deliberately separates facts established from the supplied S-JiffyDOS 1541C image and public documentation from the proposed Breadbin extension.

## 1. The intended layering

Breadbin already implements the *controller* side of the JiffyDOS byte protocol in `src/kernel/iec.s` (the `jif_first`, `jif_tx`, and `jif_rx` paths). Do not add another host transport.

The proposed drive module is an application protocol carried *inside* that byte transport:

1. Breadbin opens a normal drive channel using the existing IEC channel layer.
2. Breadbin uploads a small 1541-side program with DOS `M-W` (memory write), in chunks.
3. Breadbin starts it with `M-E` (memory execute).
4. The module receives a request byte stream over the existing JiffyDOS byte protocol, performs a DOS block operation, and returns a response stream the same way.
5. The host ends the session with UNTALK/UNLISTEN and returns to the normal DOS path.

This is an extension protocol. It is not an undocumented feature that SJD41 already exposes.

## 2. Facts established

### SJD41 compatibility and ROM layout

The supplied file is a 32 KiB ROM image, SHA-256:

```
5a8d9dc8f44e9e3469587d78bba2eb6dfb54932e37387f1e16a4d938fbe06974
```

Its 6502 vectors at the end of the image decode to NMI=$FF01, RESET=$EAA0, IRQ=$FF67. It is mapped at $8000-$FFFF for the SJD41 1541C/1541-II build represented by the filename/image. Do not treat this hash as a universal SJD41 revision identifier.

Jochen Adler's SJD41 notes say:
- SJD41 is a patch for JD41.
- It uses the original JD41 IEC bus routines.
- SJD41 occupies $8000-$FFFF on 1541C and 1541-II; the old 1541 has EPROM-layout qualifications.
- The DOS patches are concentrated largely in $C000-$DFFF.
- The enhanced DOS features include special LOAD paths, faster OPEN gap, fast SCRATCH/VALIDATE, bad-block checking and other DOS changes.
- Fast SAVE uses the original C64 routines and verifies written blocks.

Source: https://commodore.ca/manuals/funet/cbm/c64/diskutil/misc/s-jiffydos1541.html

### Breadbin's host protocol

The checked-in host implementation is in `src/kernel/iec.s`. The JiffyDOS byte transfer is selected only after the device answers the JiffyDOS probe. The code implements the published two-bit-pair transfer, including the timing-sensitive window, EOI handling and session cleanup. The project documentation says this was written from Michael Steil's public protocol description, not copied from a JiffyDOS ROM.

Important operational constraints already encoded/documented there:
- 1 MHz CPU during transfers.
- Interrupts off for the timing-critical sender/receiver window.
- No sprite DMA and no VIC badline in the critical window.
- The drive may be busy for a long time; the host must not turn a bounded wait into an unbounded hang.
- Standard IEC remains the fallback.

The byte protocol is a byte pipe, not a block command set. It does not tell the drive what READ or WRITE means.

### Standard drive-RAM bootstrap

The ordinary 1541 DOS memory commands are the bootstrap mechanism:
- `M-W` writes bytes to drive RAM.
- `M-E` transfers execution to a drive RAM address.

The upload must be chunked to fit the 1541 command buffer. Use 32-byte payload chunks in the first implementation; the command is `M-W`, address low, address high, count, then payload. Keep each command comfortably below the 42-byte DOS command-buffer capacity. The loader must read and check channel-15 status after each command (or at minimum after each bounded batch), then issue `M-E` only after the complete image is present.

This is ordinary DOS behavior, not an SJD41-specific facility.

## 3. Proposed Breadbin wire contract (new; not yet implemented)

Use one explicit, versioned request per drive session. All multibyte values are little-endian. Sector payloads are exactly 256 bytes.

### Request

| Byte(s) | Meaning |
|---|---|
| 0 | Magic: $B7 |
| 1 | Protocol version: $01 |
| 2 | Opcode: $01 READ, $02 WRITE, $03 VERIFY, $7F PING |
| 3 | Track |
| 4 | Sector |
| 5 | Sequence number, echoed in response |
| 6 | Reserved, must be zero |

For WRITE, the host sends the 256-byte sector immediately after the seven-byte header. For READ and VERIFY, no request payload follows.

### Response

| Byte(s) | Meaning |
|---|---|
| 0 | Magic: $B8 |
| 1 | Protocol version: $01 |
| 2 | Status: $00 success; nonzero module/DOS error |
| 3 | Sequence number |
| 4 | Payload length low |
| 5 | Payload length high |
| 6.. | Payload |

READ returns 256 bytes on success. WRITE and VERIFY return no payload. PING returns the module version and build marker as a short payload. The module must never emit a success response before the DOS job has completed.

Proposed status values:
- $00 success
- $01 bad magic/version/opcode
- $02 invalid track/sector
- $03 DOS read job failed
- $04 DOS write job failed
- $05 verify mismatch / DOS verify failure
- $06 malformed or incomplete request
- $07 internal state/buffer error

These values are Breadbin protocol assignments, not SJD41 status codes.

## 4. Drive-side implementation strategy

The first implementation should be conservative and synchronous:

1. Receive and validate the fixed request header.
2. Validate track/sector against 1541 geometry (35-track default; geometry extension later).
3. For READ, allocate/select a DOS buffer, set its track/sector, submit a READ job, wait for completion, then send exactly 256 bytes.
4. For WRITE, receive exactly 256 bytes into a DOS buffer, submit a WRITE job, wait for completion, then return status.
5. For VERIFY, use the DOS verify operation or read-back and compare. Do not report success merely because the write job was accepted.
6. Return to a defined idle state after every response and error.

The stock DOS job queue and buffer layout are useful implementation references, but addresses and call conventions must be re-derived against this exact SJD41 image before the module calls into them. In particular, do not cargo-cult an internal routine address from a stock 1541 disassembly.

## 5. What is deliberately not claimed yet

The following are **not** established by the public SJD41 notes or the source inspected so far:
- The callable entry ABI (register inputs/outputs, flags, preserved registers) of the SJD41 JiffyDOS send/receive routines.
- Whether those routines are callable as ordinary subroutines from uploaded RAM code, or require hidden state established by the resident DOS command path.
- A safe RAM range for the uploaded module that is free across supported drive configurations and does not collide with DOS buffers, BAM, stack, or transient code.
- A complete resident module entry/return convention.
- The exact JiffyDOS byte-level entry/exit state required on the drive side for an independently started module.
- Whether the Ultimate's emulated SJD41 drive behaves identically to this physical-ROM image.

The old notes' candidate addresses ($FF8B, $FBD8, $E9D0) are leads, not a callable ABI. They must be checked by disassembling the actual image and tracing callers/callees. No source in this branch should call them until that work is done.


### Additional static check on candidate transport addresses

A byte-level scan of this exact 32 KiB image found no absolute `JSR $FF8B`, `JMP $FF8B`, `JSR $FBD8`, `JMP $FBD8`, `JSR $E9D0`, or `JMP $E9D0` instruction encodings. This does **not** prove the addresses are wrong: they may be reached by fall-through, indirect control flow, or a different entry point. It does mean they cannot be presented as established public subroutine entry points. The disassembly task must include control-flow and caller tracing, not just dumping bytes at those offsets.

## 6. Bring-up sequence

1. Confirm ROM identity on the target drive (readable ROM bytes/hash or a known revision signature).
2. Confirm `M-W` and `M-E` on that drive with a harmless RAM test and a one-byte return stub; verify the target RAM survives the command path.
3. Disassemble the supplied SJD41 image around candidate IEC routines and identify every caller. Record entry/exit line states, registers, flags, zero-page globals and stack expectations.
4. Build a diagnostic module that only PINGs and returns a fixed response.
5. Validate byte-for-byte request and response transfers with Breadbin's existing JiffyDOS client, first in VICE, then on the Ultimate emulated drive, then on physical SJD41 hardware.
6. Add READ, then WRITE, then VERIFY. Compare every result against the existing U1/U2 path. Keep the old path as fallback.

## 7. References

- Jochen Adler, S-JiffyDOS 1541 notes: https://commodore.ca/manuals/funet/cbm/c64/diskutil/misc/s-jiffydos1541.html
- Michael Steil, Commodore Peripheral Bus, Part 7: JiffyDOS: https://github.com/mist64/cbmbus_doc
- Breadbin host implementation: `src/kernel/iec.s`
- Breadbin block layer: `src/kernel/blk.s`
- Breadbin earlier design and constraints: `docs/design/fast-io.md`, `docs/design/jiffydos-cleanroom.md`

---
This document is a concrete proposed protocol and bring-up plan, not a claim that a working SJD41 drive binary has been produced. The next engineering step is ABI archaeology against the supplied ROM image; only then should the executable module be frozen.
