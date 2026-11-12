# A send to a drive that fails part way

What the kernel does when a send to a drive stops part way: a byte is not accepted, so the drive got
only part of it. The code is `iec_out_end`, `io_flush` and `out_sa` in `src/kernel/iec.s`, and
`iec_open`, `iec_write`, `iec_read`, `cmd_status`, `bwrite` and `blk_init` in `src/kernel/blk.s`.
The test is `tests/test_iec_fault.py`.

## The problem

A 1541 keeps the bytes of a command that arrived without EOI and puts the next command after them.
"U2" followed by "U1:2 0 t s" is a U2 to t/s. "B-P" followed by "U1:..." returns a stale buffer.
"U" followed by "U1:..." is U5, a jump into drive RAM. OPEN does not reset the buffer either, so a
half command also gets the next OPEN's name appended: "S:*" followed by "i0" scratches every file.

## What the kernel does

- **The mark.** `iec_out_end` marks the drive (`io_dirty`) when a byte was not accepted. The mark is
  kept per drive number & 3, so devices 4-7 and 12-15 would share the marks of 8-11; every caller
  uses `dev_drive` (8-11), so they do not meet.
- **The flush.** Every LISTEN to a marked drive (`out_sa`) first sends its command channel 42
  spaces with EOI (`io_flush`). The mark is cleared only when the flush arrived. If the flush fails,
  the mark stays and the call returns EIO: nothing else goes to channel 15 of that drive, since a
  command after a half command could run as one ("S:*" + "i0"). If the flush's LISTEN or
  secondary is not taken (ST bit 7) the mark stays too and the flush says ENODEV: a present drive
  can miss one frame ack, and a drive switched off stays marked, which costs nothing (the flush is
  tried again on each send, and fails the same way while it is off).
- **LISTEN not taken.** `out_sa` tries the flush and its own LISTEN and secondary three times
  before it says ENODEV, so a present drive that missed one frame ack is not taken for absent (at
  boot that would adopt the REU root). An absent drive costs three tries of about a millisecond.
- **At boot and mount.** `blk_init` (INIT code) marks all four drives (8-11), so the first send to
  each in a boot is flushed first. `iec_open` (every mount: the boot drive, `mount 9 /mnt` and the
  like) sends OPEN 15 "i0" and OPEN 2 "#" and tries three times. A lost name byte marks the drive,
  so the next try is flushed first. It returns ENODEV only when the LISTEN or secondary was not
  taken three times in a row (`out_sa`); any other failure, after three tries, is EIO. `blk_init` adopts the REU root only on ENODEV; on
  EIO the drive is still the root and the mount fails loudly ("cannot mount root"). The cbm module
  opens its files after the mount, so they come after the flush.
- **Why at boot.** A C64-only restart does not reset the drive. On the Ultimate a C64 reset leaves
  the physical drive alone (`docs/hardware-notes.md`), so a half command sent before the reset is
  still in the drive's buffer when Breadbin starts again.
- **Reads.** A block read (`iec_read`: U1, then the data) is tried three times when the bus failed
  (a byte not accepted, a timeout, a status read that did not arrive). A lost byte costs one retry
  and no error.
- **Writes.** `iec_write` sends B-P, reads its status, sends the data, then the U2 and its status.
  B-P, its status and the data are tried three times, as a read is: nothing is on the disk yet.
  When a byte of the U2 itself is lost on the bus there is no retry: a U2 cut on the bus might
  run as a prefix ("U2:2 0 1" for "U2:2 0 19 10"), a write to another
  block, and a retry that succeeds would hide it. That is EIO. A U2 that went out whole (only its
  UNLISTEN not taken: `test_u2_unlisten_lost`), or whose status read then failed on the bus
  (`test_u2_status_timeout`) (the physical 1541 can go quiet mid-byte,
  `docs/hardware-notes.md`), is tried again, the whole write: it writes the same block again. A 2x
  status stays final (below). On EIO `bwrite` drops the buffer (`b_valid`, new in this work) and
  the REU cache's copy of the target block (`cache_inval` at `@we`, which predates it).
- **The superblock's new build id.** With the REU cache on, the boot's first write first gives the
  disk a new build id (`cache_epoch`). If that read or write fails the write does not go ahead and
  the next write tries the epoch again (`ep_done` is cleared), so the cache never takes a changed
  disk for the pristine one.
- **Drive errors.** An error the drive itself reported on its status channel as a 2x (20-29 media
  errors, 26 WRITE PROTECT ON) is not retried: `cmd_status` ends the tries, since a retry would
  only knock the head again. Other codes are retried. IOSTAT counts read retries and give-ups in
  `io_nretry`/`io_nfail` and write ones in `io_nwretry`/`io_nwfail`. `IecDosError` tests both
  kinds of drive error.
- **UNLISTEN.** On a data channel `iec_out_end` does not fail on an UNLISTEN nobody answered (ST
  bit 7) once every byte arrived: the bytes are in, and `cbm_write` would otherwise report EIO for
  data that was written, and a caller that tries again would write it twice. On channel 15 it is a
  failure: the drive runs a command at UNLISTEN, so it may not have run it, and the status read
  would answer for the one before. Measured under VICE (`test_u2_unlisten_lost`): the drive saw the
  UNLISTEN's ATN but the `$3F` byte was not acknowledged, and the 1541 ran the U2 anyway; a lost ATN
  edge itself is not measured. The cost of the rule: a channel-15 command that did run is reported as
  EIO. For the U2 that is a retry (same block); for `cbm_scratch` and `cbm_rename` (`iec_command`)
  the user sees "i/o error" although the file is gone or renamed, and a second try answers FILE NOT
  FOUND: loud, not silent, but wrong in its message. An OPEN on a data channel also runs at
  UNLISTEN and is not given the same rule: a lost UNLISTEN there reads as success, and is caught
  only if the `iec_status` after it does not read an older 00 (open; not measured). (The flush's own UNLISTEN is checked against the caller's
  channel; a flush whose UNLISTEN is lost leaves a full buffer, 42 bytes, so the next command is
  dropped and answered 32, a retry, never run: reasoned from the buffer limit, not measured.)

## What was measured under VICE (1541 DOS ROM)

- **A spurious EOI in the middle of a command does nothing.** The K-th byte of a U1, U2 or B-P sent
  with EOI and the rest after it (`test_u1_eoi`, `test_u2_eoi`, `test_bp_eoi`, K from 3 to 10): the
  1541 runs the whole command at UNLISTEN. The copies are right, nothing retried, no block changed
  that no U2 named, on this tree and on 236a044. An earlier theory here (the drive runs both parts,
  so a halt that reads as EOI cuts a command) was wrong for this drive.
- **EOI, then the byte lost.** The drive sees the EOI of a command's last byte, then the C64 gives
  up before the bits (`test_*_eoi_lost`). For a U1 or a B-P the C64 knows the byte failed: one
  retry, quiet. For a U2 it is now EIO (loud, no retry). On 236a044, which retried, the drive's job
  headers (t/s of buffers 0-4, `$06-$0F`) did not change between the cut U2 and the retry, for
  "U2:2 0 19 10" cut to "U2:2 0 19 1", "U2:2 0 19 8" cut to "U2:2 0 19 " and "U2:2 0 16 12" cut to
  "U2:2 0 16 1": the cut U2 ran no job, and the retry wrote the right block. The no-retry rule
  stays anyway: this is one drive model under an emulator, and a wrong-block write is silent.
- **A byte lost without EOI** leaves a half command, which the flush (42 spaces) turns into a line
  too long, rejected without being parsed (below). `test_u1`, `test_u2`, `test_bp`,
  `test_data_phase` at `FAULT_K`; the U2 case is loud (EIO) by the rule above.
- **Every block the kernel's U2s did not name** is compared with the image before the run
  (`foreign_writes`); any change must come with a loud step.

## Which restarts are covered

- **Covered: a start that sends nothing to the drive first.** The machine is reset (C64 only) and
  Breadbin is started without a KERNAL OPEN or LOAD to that drive before it: from the Ultimate's
  menu (DMA load), a cartridge, or a monitor `g`. Breadbin's first command is the flushed one.
  `IecRestart` tests this for drive 8 and for a drive 9 mounted later, with a half command poked
  into the drive (`S:*`), with the flush itself faulted on its last byte once, and on its first byte
  twice (the third try clears it), and three times on either (the mount fails loudly, the
  directory is unchanged; on 236a044 the boot went on silently after three failed flushes, and
  when they had lost their first byte its "i0" ran as "S:*i0": the boot file BREADBIN was
  scratched), and
  with a real U2 send cut off by a C64 reset after K bytes (`FAULT_K`, default 9: on a tree
  without the flush, "U2:2 0 19" followed by the boot's "i0" panics at the root mount).
  `IecOpenFault` drops the "i0" or "#" of the boot's OPEN once (a retry, a quiet boot from the
  drive while the REU holds a root image), three times (EIO, "cannot mount root", the REU root not
  adopted), and the "i0" of `mount 9` once. `test_flush_listen_missed` misses the flush's LISTEN
  once with "S:*" in the drive (on d0639fb the mark was dropped and "i0" followed);
  `test_listen_missed_twice` misses the first two LISTENs with an REU root image (on d0639fb the
  REU root was adopted). On 236a044 one lost byte made the boot adopt the REU
  root, and failed `mount 9`.
- **Not covered: `LOAD"BREADBIN",8` from the KERNAL after the reset.** The KERNAL sends the name
  first, so it is appended to the half command before Breadbin runs: a leftover "U2:2 0 1" with
  "BREADBIN" after it is a name that does not exist (FILE NOT FOUND), and the load fails loudly.
  What a leftover "S:*" in front of the name does on a LOAD is not tested. Nothing
  in Breadbin can run before that LOAD, so this is not fixed here; it predates this change. The
  user's way out is to switch the drive off and on: a KERNAL command such as "UI" would be appended
  to the half command too. Drives 9-11 have the same hazard only for a KERNAL command sent to
  them before Breadbin starts.

## Limits

- **The flush relies on the 1541's command buffer.** The 1541 holds 42 bytes and drops the rest
  (CFDF). At the EOI it finds a command of 42 bytes and answers 32, SYNTAX ERROR, without parsing it
  (C2CE), then empties the buffer (E645). The JiffyDOS 1541 ROM is the same in these ranges. A drive
  with a larger buffer (sd2iec, for example) would instead run the half command followed by spaces.
  A 1581 or another drive must be checked before this is relied on, as must the measurements above.
- **`cbm_write` gives no count.** A CBM DOS file write (channel 3, the cbm module) that fails part
  way returns EIO. The bytes before the failure may already be in the file, and the caller is not
  told how many. It is a stream, so it is not retried.
- **A marked drive that cannot be flushed stays unusable until it is reset.** Every call to it
  returns EIO while the flush fails. A drive that does not answer LISTEN keeps its mark and the
  flush answers ENODEV (it may still hold a half command); the mark is cleared by the first flush
  that gets through.
- **A U2 cut on the bus that did write another block is not caught.** Under VICE a cut U2 ran no
  job (above), and the write fails loudly with EIO; but if some drive did run the prefix, the
  other block's buffer in the kernel and its REU cache copy would still hold the old contents, and
  the disk the new. Only the target block is dropped.
- **A create whose directory write fails leaks the new inode.** `sys_open` with `O_CREAT` takes an
  inode (`ialloc`), then adds the directory entry; if that write fails (EIO now that a cut U2 is
  not retried) the inode stays taken and no entry names it. The call reports EIO (it reported the
  inode's number before 9f356ce). This is read from the code (`ialloc` writes the inode's type
  first), not measured; it predates the change and is not fixed here.
