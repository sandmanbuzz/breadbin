; d81.km: 1581 geometry for c64fs volumes on drives 9-11 (80 tracks of 40 sectors, a .d81).
;
; The kernel maps a c64fs block number to a track and sector with the 1541's zone table
; (blk_to_ts in src/kernel/blk.s). This module makes a drive with 40 sectors on a track
; usable as a mounted c64fs volume: block n is track 1 + n/40, sector n mod 40, which is
; also the block's place in a .d81 image (offset n * 256). Everything else is the kernel's
; own path: the 1581 takes the same "U1"/"U2"/"B-P" commands on a "#" channel.
;
; How it hooks in (no resident bytes; the labels cost nothing): init points four call
; sites at this module and fini puts them back.
;   ts_rd_io, ts_wr_io      (blk.s)  jsr blk_to_ts in the block read and the block write
;   open_mnt_io, open_dio_io (cbm.s) jsr iec_open in mount() and in diskio()
; The open wrapper asks the drive what it is each time a drive is opened, by geometry and
; not by ROM: "U1" of track 1 sector 39 must work and of track 1 sector 40 must not. A
; 1541 or 1571 refuses sector 39 at once (66, ILLEGAL TRACK OR SECTOR: no head movement)
; and keeps the kernel's mapping. The answer is kept per device until its next open, so a
; mounted volume never changes geometry, and a drive that was swapped is asked again.
;
; Limits. The boot drive (device 0) is opened before any module exists and is never asked:
; it stays a 1541. A volume is c64fs format 2 over the whole disk, 3200 blocks: two bitmap
; blocks (377-378), inodes 379-410, and track 40 (the 1581's header, BAM and directory, every
; block allocated) marked used; tools/mkimage.py d81 and `format` (with this module loaded)
; write it, as upstream's tools do. A CBM DOS disk in a 1581 is not handled (cbm.km reads
; the 1541's track 18). A probe that fails on the bus reads as "not a 1581": the mount then
; finds no superblock and fails without writing.
;
; Source and licence. Our own work. The 1581's geometry and its block commands are from
; the Commodore 1581 Disk Drive User's Guide (the track and sector table; the "U1"/"U2"
; and "B-P" commands in the direct access chapter). No drive ROM was read or copied.
.include "../kernel/k.inc"
.include "kexp.inc"

SPT     = 40            ; sectors on every track of a 1581

.segment "HEADER"
        jmp init
        jmp fini
        .word KAPI_HASH
        .byte $43               ; class 3: block driver; high nibble = name id for `mod ls` (the table is in src/bin/mod.s)

.segment "BSS"
dtype:  .res NDEV       ; per device: 0 = the kernel's (1541) mapping, 1 = 40 sectors a track
o_dev:  .res 1

.segment "RODATA"
s_p39:  .byte "U1:2 0 1 39"
s_p40:  .byte "U1:2 0 1 40"
PLEN    = 11

.segment "CODE"
; init is refused unless the kernel is loading the module (as cbm.km), and when the call
; sites are not the kernel's own (a second copy, or another module that took them).
init:   lda mod_busy
        beq no
        lda ts_rd_io+1
        cmp #<blk_to_ts
        bne no
        lda ts_rd_io+2
        cmp #>blk_to_ts
        bne no
        lda open_mnt_io+1
        cmp #<iec_open
        bne no
        lda open_mnt_io+2
        cmp #>iec_open
        bne no
        lda #<d_open
        sta tmp0
        lda #>d_open
        sta tmp1
        lda #<d_ts
        ldx #>d_ts
        bne set             ; (always: the module is not in page 0)
no:     lda #EBUSY
        sec
        rts

; fini: refused while a volume that uses our mapping is mounted; else the call sites back.
fini:   ldx #NDEV-1
@c:     lda dtype,x
        beq @n
        lda dev_present,x
        bne no
@n:     dex
        bpl @c
        lda #<iec_open
        sta tmp0
        lda #>iec_open
        sta tmp1
        lda #<blk_to_ts
        ldx #>blk_to_ts
; set: A/X = where the two block calls go, tmp0/tmp1 = where the two opens go
set:    php
        sei
        sta ts_rd_io+1
        sta ts_wr_io+1
        stx ts_rd_io+2
        stx ts_wr_io+2
        lda tmp0
        sta open_mnt_io+1
        sta open_dio_io+1
        lda tmp1
        sta open_mnt_io+2
        sta open_dio_io+2
        plp
        clc
        rts

; d_open: iec_open (X = dev), then ask the drive for its geometry. Returns what iec_open
; returned: carry set and A = errno when the drive could not be opened.
d_open: stx o_dev
        lda #0
        sta dtype,x         ; until it says otherwise
        jsr iec_open
        bcs @r
        ldx #0              ; track 1 sector 39: there on a 1581 only
        jsr probe
        bcs @ok
        ldx #s_p40-s_p39    ; and sector 40 must not be (a drive with longer tracks is not ours)
        jsr probe
        bcc @ok
        ldx o_dev
        inc dtype,x
@ok:    clc
@r:     rts

; probe: X = offset of the command from s_p39 -> carry clear if the drive ran it (00 or 01)
probe:  ldy #0
@l:     lda s_p39,x
        sta cmdbuf,y
        inx
        iny
        cpy #PLEN
        bne @l
        sty cmdlen
        lda o_dev
        jmp iec_command

; d_ts: rq_dev, rq_lo/hi -> trk/sct, as blk_to_ts
d_ts:   ldx rq_dev
        lda dtype,x
        bne @d81
        jmp blk_to_ts
@d81:   ldx #1              ; the track
        ldy rq_hi
        lda rq_lo
@l:     cpy #0
        bne @sub
        cmp #SPT
        bcc @done
@sub:   sec
        sbc #SPT
        bcs @nb
        dey
@nb:    inx
        bne @l              ; (a block number past 255 tracks: stop, the drive refuses it)
@done:  sta sct
        stx trk
        rts
