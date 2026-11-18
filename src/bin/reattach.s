; reattach: the boot disk is back in drive 8 (after `eject`). Checks that it is the same disk (label
; and build id), then lets the writers that slept on / carry on. Close and `umount` the disk that
; was in drive 8 first: the drive is the boot disk's again.
.include "../../include/breadbin.inc"
.import perr
.segment "CODE"
        lda #<buf
        sta r0
        lda #>buf
        sta r0+1
        lda #8
        jsr SYS_CACHE
        bcc @ok
        ldx #0
        ldy #0
        jsr perr
        lda #1
        jmp SYS_EXIT
@ok:    rts
.segment "BSS"
buf:    .res 256
