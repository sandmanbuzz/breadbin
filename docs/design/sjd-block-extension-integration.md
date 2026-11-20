# S-JiffyDOS integration: Breadbin host path

Status: design correction based on the author's SJD41 instructions. SJD41 is a transparent JiffyDOS 1541 DOS replacement, not a new host-side byte protocol.

## What is already implemented

src/kernel/iec.s contains a clean-room JiffyDOS byte transport. jif_first probes each TALK/LISTEN session; io_jif records whether that session is using JiffyDOS. bus_ciout and bus_acptr select JiffyDOS transmit/receive for data bytes when that session was detected. The command/ATN phase remains ordinary IEC.

src/kernel/blk.s reads and writes 256-byte blocks using DOS U1/U2 and data channel 2. These commands already use JiffyDOS byte framing when the drive answers the JiffyDOS probe. No SJD-specific host framing is needed.

## What SJD41 actually promises

Jochen Adler's SJD41 instructions say that SJD41 is a patch for JiffyDOS 1541, uses the original JD IEC bus routines, and works with ordinary JiffyDOS computers and speeder cartridges. SJD41 and the C64-side SJD64 are independent. The SJD41 drive ROM adds faster DOS operations (including fast open/load/save, scratch and validate) and GCR-to-HD optimizations while retaining the JD IEC transport.

Therefore, for operations SJD41 accelerates through its normal DOS entry points, Breadbin should simply continue issuing the same ordinary DOS commands over the existing JiffyDOS transport. The host should not invent a new SJD handshake or assume a private block RPC exists.

## What remains to prove for Breadbin

The current Breadbin block path uses U1/U2. The SJD41 documentation describes fast save/load and other DOS operations, but does not explicitly promise that U1/U2 are accelerated in the way Breadbin needs. We must test that exact path against JD41 and SJD41 before deciding whether a Breadbin-specific drive hook is needed.

Test matrix:

- same C64/JiffyDOS host, same drive, same disk image;
- plain JD41 vs SJD41 drive ROM;
- Breadbin's U1 read path and U2/B-P write path;
- compare returned 256-byte checksums, status bytes, write verification, and elapsed time;
- also test ordinary DOS SAVE/LOAD to distinguish the author's advertised fast paths from our block API.

If U1/U2 already take the optimized SJD41 internal paths, the correct integration is almost nothing in the host: keep existing commands and benefit transparently. If they do not, then and only then design a Breadbin-specific command/hook, with an explicit versioned capability probe and safe fallback.

## S-ifier work

The current ROM composer is a safe image-layout/patching scaffold, not a functional S-ifier. The next reverse-engineering work is to compare the user's JD 1541 ROM with the SJD41 1541C ROM, map changed entry points and extension-bank routines, and obtain the actual SJD41 generator disk. The uploaded ajnsjd64.d64 is the SJD64/C64 generator disk and is not that drive-side generator.

Do not infer the SJD41 transformation from the SJD64 C2/C3 programs. The drive-side instructions describe a separate SJD41 generator workflow and separate interim files.

## Compatibility and fallback

- A stock drive continues to use the standard IEC byte protocol and ordinary DOS commands.
- A JiffyDOS drive continues to use the existing JiffyDOS byte protocol.
- An SJD41 drive should be transparent to the same host protocol; it is still a JiffyDOS drive.
- Any future Breadbin-only drive command must be separately negotiated. A plain JiffyDOS drive must never receive it.
- A failed optional extension operation must not silently retry a possibly partial write through the ordinary path.

## Non-goals

- Do not change the stock-drive uploaded-loader path.
- Do not require the C64-side SJD64 KERNAL.
- Do not copy JiffyDOS or SJD41 ROM code into Breadbin or commit generated derivatives.
- Do not treat JiffyDOS byte framing as a generic block RPC.

## Sources

- Jochen Adler, S-JiffyDOS 1541 instructions: https://retro-bobbel.de/nlq/ajnsjd41.html
- Jochen Adler, S-JiffyDOS home page: https://retro-bobbel.de/nlq/ajnhome.html