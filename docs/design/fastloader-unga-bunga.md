# Stock-1541 software fastloader: the unga-bunga plan

Status: research-backed implementation plan. The target is a **greenfield stock 1541**, with a RAM-resident fastloader that disappears on drive reset. S-JiffyDOS is not required. It may be a later test target if the module uses only stock DOS services.

## 1. The shoulders to stand on

The closest directly reusable prior art is Michael Steil's `fastboot1541`:

- Source: https://github.com/mist64/fastboot1541/blob/master/start.s
- Explanation: https://www.pagetable.com/111
- Licence: "Do anything you want with it", with request for credit and an email to the author.

This is not just a description. The source contains both the C64 and 1541 halves, and the article explains the electrical protocol, timing, sector-read call, bootstrapping and memory layout.

Other useful prior art:
- Dave McMurtrie's documented Epyx FastLoad drive code: https://loadrun64.com/zimmers/c64/diskutil/fastloaders/epyx_fastload_drive_code.html
- Zimmers fastloader source archive: https://www.zimmers.net/anonftp/pub/cbm/c64/diskutil/fastloaders/index.html
- Codebase64's fastloader survey: https://codebase64.c64.org/doku.php?id=base:fastloaders
- Krill's loader and GEOS drive drivers are useful later examples of multi-drive-family and read/write engineering, but are larger systems.

## 2. What the classic software loader actually does

A software fastloader has two cooperating programs, not one magic drive command:

1. The C64 loads a small bootstrap with ordinary KERNAL IEC.
2. The bootstrap sends drive machine code using DOS `M-W` commands (or, in compact bootstraps, uses `M-E` with trailing command bytes, or asks the drive to read a sector containing the next stage).
3. It sends `M-E` to start the drive code.
4. The drive payload announces readiness by setting a known IEC line state.
5. The C64 switches to its matching cycle-counted bus routine.
6. The drive reads sectors using the 1541 DOS machinery, then streams their bytes over the custom bus protocol.
7. A terminator/escape returns the drive to DOS or leaves the resident loop ready for another request. Reset always removes the payload.

This is the standard old software-fastloader pattern. The drive code is uploaded into RAM; it does not patch the ROM permanently.

## 3. The concrete byte-level example: fastboot1541

### Bootstrap

The C64-side source opens channel 15, sends an `M-E` command and waits for the drive to signal that the payload is running. The article also documents two compact deployment tricks:

- `M-W` uploads up to 36 bytes per command (the implementation here should conservatively use 32-byte chunks).
- `M-E` can carry trailing bytes in the command buffer; the execute address can point into those bytes. This permits a tiny first-stage stub without a separate `M-W`.
- A drive-side bootstrap can read the next stage from a known sector using `B-R`/ROM read routines, avoiding the slow upload of a larger payload.

For Breadbin, prefer the boring, robust route first: use `M-W` chunks, check status, then `M-E`. Optimize bootstrap size only after the protocol works.

### Drive payload

The published fastboot1541 drive code is assembled at $0482 and uses:
- $1800: 1541 VIA #1 port A, the IEC lines.
- $0300-$03FF: DOS buffer 0.
- $0006/$0007: track/sector for buffer 0.
- $F9: buffer/job index used by DOS.
- $D586: DOS read-sector routine in the stock 1541 ROM.
- $E9AE: a small ROM helper used to restore/release the clock line after a byte.

The core sequence is visible in the source:

```asm
start1541:
    lda #$08
    sta $1800       ; announce fast code is running

    lda #0
    sta $05         ; sector index
    sta $f9         ; buffer 0
    lda #TRACK
    sta $06         ; buffer 0 track
read_loop:
    ldx $05
    lda sector_table,x
    inc $05
    bmi end
    sta $07         ; buffer 0 sector
    cli
    jsr $D586       ; stock DOS reads and GCR-decodes the sector
    sei
    ; encode and transmit the 256 bytes from $0300
```

The actual byte sender is also in the published source. It encodes a byte using a 16-byte nibble lookup table, advertises readiness by writing $00 to $1800, waits for the C64 to assert its ready state, writes four two-bit pairs to the VIA, then calls $E9AE. The matching C64 receiver samples $DD00 four times, with a raster-safe delay before starting.

**Important:** this is *not* the JiffyDOS byte protocol already implemented in Breadbin's `iec.s`. It is a different, independently handshaken four-pair transfer. It is a strong candidate for adoption because both halves are published and the code is small, but it requires a matching host routine. Do not connect this drive payload to `jif_tx`/`jif_rx` and expect it to work.

### Why the handshake exists

The two CPUs do not share a clock. The 1541 runs slightly faster than the PAL C64, and the VIC-II can steal C64 cycles for badline/sprite DMA. A long unacknowledged stream drifts out of phase. fastboot1541 therefore handshakes each byte and makes the C64 wait for a raster-safe window before sampling. Its source is a compact, understandable demonstration of the whole trick.

The drive-to-host signal levels are inverted through the 1541's IEC output circuitry; the host code compensates for that. The two directions are not electrically symmetric.

## 4. What we should build for Breadbin

Do not build a file loader. Breadbin's block layer already owns block numbers and buffers. Build a **sector RPC engine** with a small resident command loop:

- `PING`: identify protocol/build and prove both directions.
- `READ(track, sector)`: DOS reads a sector into a drive buffer, then streams 256 bytes to the host.
- `WRITE(track, sector, 256 bytes)`: host streams a sector into a drive buffer; drive submits the DOS write job and waits for completion.
- `VERIFY(track, sector)`: verify by DOS job or explicit read-back/compare; return only after completion.
- `EXIT`: release IEC lines and return to DOS initialization/command processing.

The first milestone should implement only PING and READ. WRITE must be a second milestone because it needs the reverse data path and correct drive-job completion semantics.

The payload should be loaded once per drive session, not once per block. Breadbin's host should keep the module alive and issue requests repeatedly. The drive module should not own the filesystem, BAM, directory, or file chains; it is a raw block transport. Breadbin owns allocation and metadata.

## 5. Recommended architecture choice

There are two viable paths; do not conflate them:

### A. Adopt fastboot1541's transfer protocol (recommended first prototype)

- Reuse the published encoder, 16-byte table, drive handshake, and matching C64 receive routine with attribution.
- Generalize its hard-coded `sector_table` into a request header containing track/sector.
- Reuse the stock DOS sector read routine after validating its ABI on the target stock 1541 ROM.
- Add a reverse sender/receiver pair for writes only after reads are proven.
- Implement a Breadbin-specific host API such as `iec_fast_read_ts`, not by calling the JiffyDOS routines.

This is the shortest route to a known-good greenfield stock-1541 prototype.

### B. Implement the JiffyDOS byte protocol on the drive

- Keep Breadbin's existing `jif_tx`/`jif_rx` host side.
- Write a stock-1541 RAM payload that implements the *drive* side of the published JiffyDOS state machine.
- This avoids a second host transfer implementation, but is a clean-room protocol implementation and requires careful bus-trace validation. JiffyDOS detection in the host does not magically make a stock 1541 understand JiffyDOS.

This is a reasonable later experiment, but not the shortest way to a working uploaded drive payload. The host's existing Jiffy routines were written for a JiffyDOS-speaking drive; they are not yet a generic software-fastloader transport.

## 6. Compatibility and ROM calls

The published fastboot1541 example uses $D586 and $E9AE. Those are stock-ROM implementation dependencies, not universal 1541 ABI guarantees. For the first target, define the target as the common stock 1541 DOS ROM revision and verify these addresses in the actual ROM image used by VICE and the physical drive.

Do not assume those addresses work in S-JiffyDOS. Once the stock prototype works, diff the ROMs and validate the entry points independently. If the ROM call differs, use a tiny ROM-specific call table or a second payload build. Do not make the initial module depend on SJD internals.

## 7. First deliverable sequence

1. Assemble a drive payload that only sets the ready line and waits for an EXIT/timeout. This proves M-W/M-E deployment and drive-side execution.
2. Add one-byte PING response in both directions.
3. Add one-sector READ using the published fastboot1541 transfer routine and $D586.
4. Write the Breadbin host-side matching receiver and call it from a standalone diagnostic program.
5. Generalize READ to arbitrary track/sector pairs.
6. Add WRITE and VERIFY.
7. Test stock 1541 in VICE, then physical stock 1541, then S-JiffyDOS and Ultimate emulated drive as separate compatibility targets.

## 8. Scope note on the earlier SJD41 protocol draft

The earlier idea of defining a new $B7/$B8 command framing over the already implemented JiffyDOS stream is superseded as the primary plan. It is still a possible **Option B** implementation, but it is not what the old software fastloader prior art teaches us to do first. The first payload should be a self-contained stock-1541 RAM fastloader, loaded with M-W/M-E, with a matching host protocol.

## Sources

- Michael Steil, fastboot1541 source and licence: https://github.com/mist64/fastboot1541
- Michael Steil, “A 256 Byte Autostart Fast Loader for the Commodore 64”: https://www.pagetable.com/111
- Dave McMurtrie, Epyx FastLoad drive code: https://loadrun64.com/zimmers/c64/diskutil/fastloaders/epyx_fastload_drive_code.html
- Zimmers fastloader archive: https://www.zimmers.net/anonftp/pub/cbm/c64/diskutil/fastloaders/index.html
- Breadbin `docs/design/fast-io.md` and `src/kernel/iec.s`
