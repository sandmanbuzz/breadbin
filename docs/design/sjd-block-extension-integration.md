# S-JiffyDOS integration: host-side plan

Status: integration design; no drive ABI or ROM hooks are claimed yet.

## Goal

Use the existing Breadbin JiffyDOS host transport when the addressed drive is JiffyDOS, and transparently select a Breadbin drive-ROM extension when the drive advertises it. A plain JiffyDOS drive must continue to use the existing DOS U1/U2 block path. A stock drive continues to use standard IEC.

This is an optional capability layered on the existing transport, not a replacement for JiffyDOS and not the stock-drive uploaded-loader path.

## What is already implemented

src/kernel/iec.s contains a clean-room JiffyDOS byte transport. jif_first probes each TALK/LISTEN session; io_jif records whether that session is using JiffyDOS. bus_ciout and bus_acptr select JiffyDOS transmit/receive for data bytes when that session was detected. The command/ATN phase remains standard IEC.

src/kernel/blk.s currently reads and writes 256-byte blocks using DOS U1/U2 and data channel 2. Since iec_ch_open, iec_in_*, and iec_out_* already select JiffyDOS at the IEC byte layer, the existing block path already gets ordinary JiffyDOS byte acceleration without any S-JiffyDOS-specific host code.

## Required distinction: JiffyDOS vs Breadbin extension

There are two independent questions:

1. Does this addressed drive support the JiffyDOS byte protocol? The existing per-session IEC probe answers this.
2. Does it also implement the Breadbin drive extension? This needs a separate, explicit capability handshake.

Do not infer (2) from (1), from the drive model, or from a ROM size. Never send an extension command until the handshake has positively identified the extension and its ABI version.

## Proposed host state

Maintain per-device capability state for IEC drives 8–11:

- unknown: not probed since reset / device change
- plain: no Breadbin extension (includes stock and ordinary JiffyDOS drives)
- BBX v1: extension positively identified and version accepted
- disabled: extension failed during a transfer; do not retry it until reprobed/reset

The existing JiffyDOS session selection remains authoritative for byte framing. Capability state only chooses the block operation.

## Probe and fallback semantics

The drive-side ROM extension must expose a harmless query operation that can be issued through the ordinary DOS command channel. It must return a fixed magic, protocol major/minor, and capability bits. The query must not alter disk state, the DOS job queue, channel state beyond the command/status exchange, or the current track/sector buffer.

The exact command spelling and hook address are intentionally not frozen until the ROM dispatch path is reverse-engineered. The probe response must be unambiguous; a DOS syntax error, timeout, malformed response, unknown major version, or absent response means plain drive, not a fatal boot error.

After a positive probe, the host may select the extension for block reads/writes. Any transfer timeout or malformed completion disables the extension for that device and returns an I/O error for the current operation; it must not silently retry a possibly partial write through DOS. Reads may be retried through the plain path only after the extension has explicitly aborted/reset the transfer and the host knows the drive is back at a clean command boundary.

## Block ABI requirements

The extension needs sector-level operations, not a second file protocol:

- READ: device, track, sector -> exactly 256 data bytes plus an explicit completion/status result.
- WRITE: device, track, sector, exactly 256 data bytes -> completion/status result.
- The extension must preserve normal 1541 DOS semantics outside the extension operation.
- It must report write protection, missing header/sector, checksum failure, and write verification failure distinctly enough for the host to map to EIO.
- A write is not successful until the drive has completed the physical write and any required verify.
- The host retains ownership of retry policy and must know whether a failed operation may already have modified media.

The data phase should use the existing JiffyDOS byte transport. The extension must not introduce a new C64-side bit protocol. It may use the drive's fast GCR/bit-cell routines internally to read/write sectors, then stream the sector over the already-established JiffyDOS channel.

## Integration point in Breadbin

Keep the public block API (bread/bwrite) unchanged. Add an internal backend selection below iec_read/iec_write:

- no BBX capability: existing U1/U2 path unchanged;
- BBX READ/WRITE capability: invoke the extension's sector operation;
- operation-level failure: apply the explicit failure policy above.

Probe lazily on first block I/O to each drive, or during the existing drive initialization if that is guaranteed to happen before all block access. Do not probe every sector.

The JiffyDOS detection is per TALK/LISTEN session in iec.s; the BBX capability is per physical IEC device in blk.s. Keep these state lifetimes separate.

## Reverse-engineering gates before implementation

1. Finish tracing the S-JiffyDOS generator's C3 and EPROM-GEN stages so we understand how the extension is assembled and mapped.
2. Identify the exact JiffyDOS 6.01 drive-side dispatch points for command handling, channel open/talk/listen, and DOS block read/write.
3. Trace the corresponding S-JiffyDOS changes to establish which hooks are necessary and which are merely SJD features unrelated to Breadbin.
4. Implement a minimal PING/INFO extension first; prove the host can negotiate it while ordinary JiffyDOS remains unchanged.
5. Implement READ, test against known sectors and checksums, then WRITE with write-protect and read-back verification tests.
6. Build private ROM images only from the user's local ROM inputs; never check ROMs or generated derivatives into the repository.

## Non-goals

- Do not change the stock-drive fastboot1541-style path.
- Do not make the host require S-JiffyDOS for ordinary JiffyDOS.
- Do not copy S-JiffyDOS or JiffyDOS ROM code into Breadbin.
- Do not treat the existing JiffyDOS byte transport as a generic block RPC; the drive-side operation ABI is new work.
