; eject.km: let the boot disk out of its drive (cache ops 7, 8, 9; root only).
;
; The boot disk is served from the REU block cache while it is out (blk.s, `ejected`), so drive 8
; can take another disk: `mount 8 /mnt`. Loaded by the `eject` program, which warms the cache
; first. The resident kernel keeps only the gate for writers (they sleep on CH_ROOT) and ejv, the
; stub this module's init points at ej_op.
;   7  eject: close the drive's channels, set `ejected`
;   8  reattach: r0 = a 256-byte scratch page. Back in only if the disk in the drive is the one
;      that went out (CBM label and build id equal the cache header), then wake the writers
;   9  r0 = buffer, r1 = block: read a block of the boot disk (cache once ejected); for the warm-up
.include "../kernel/k.inc"
.include "kexp.inc"

.segment "HEADER"
        jmp init
        jmp fini
        .word KAPI_HASH
        .byte $00               ; generic

BAM_BLOCK   = 357
SB_BLOCK    = 376
BAM_LABEL   = $90
SB_BUILD_ID = 15

.segment "CODE"
init:   lda mod_busy            ; refused unless the kernel is loading us (see cbm.s)
        beq @no
        lda ejv+1               ; a second copy: refused
        cmp #<cbm_none
        bne @no
        lda #<ej_op
        sta ejv+1
        lda #>ej_op
        sta ejv+2
        clc
        rts
@no:    lda #EBUSY
        sec
        rts

fini:   lda ejected             ; the disk is out: we are all that can bring it back
        beq @f
        lda #EBUSY
        sec
        rts
@f:     lda #<cbm_none
        sta ejv+1
        lda #>cbm_none
        sta ejv+2
        clc
        rts

ej_op:  cmp #10
        bne @n
        jmp ej_chk
@n:     cmp #8
        beq ej_back
        bcs ej_read
        lda cache_on            ; 7: the cache is all there will be
        beq nodev
        lda ejected
        bne inval
        lda #0                  ; a new build id for this eject: no sibling copy of the disk matches
        sta ep_done
        jsr cache_epoch
        bcs @r7
        ldx #0
        jsr iec_close           ; the drive is free for another disk
        inc ejected
        clc
@r7:    rts
nodev:  lda #ENODEV
        .byte $2c               ; bit abs: skips the next lda
inval:  lda #EINVAL
        sec
        rts

ej_read:
        lda #0
        ldx r1
        ldy r1+1
        jsr bread
        bcs @r
        ldy #0
@c:     lda (bp),y
        sta (r0),y
        iny
        bne @c
        clc
@r:     rts

; ej_busy: carry set if a mount holds the boot drive (its channels are the drive's)
ej_busy:
        ldx #NDEV-1
@m:     lda dev_present,x
        beq @n
        lda dev_drive,x
        cmp dev_drive
        beq @b
@n:     dex
        cpx #1
        bne @m
        clc
        rts
@b:     sec
        rts

; reattach
ej_back:
        lda ejected
        beq inval
        jsr ej_busy
        bcs @busy
        lda r0
        sta bp
        lda r0+1
        sta bp+1
        jsr ej_same
        bcs @r
        lda #0
        sta ejected
        lda #CH_ROOT
        jsr wakeup
        clc
@r:     rts
@busy:  lda #EBUSY
        sec
        rts

; 10, from mount (Y kept): may the disk in the boot drive go on another slot? Carry clear: no, it
; is the ejected disk itself (writes through the mount would leave the cache stale) or the drive is
; already mounted. Carry set: yes (a different disk, or nothing there for the mount to fail on).
ej_chk: tya
        pha
        jsr ej_busy
        bcs @no
        lda #<ebuf
        sta bp
        lda #>ebuf
        sta bp+1
        jsr ej_same
        bcs @ok
        ldx #0
        jsr iec_close
@no:    clc
        bcc @d
@ok:    sec
@d:     pla
        tay
        rts

; ej_same: bp = a page. Opens the boot drive's channels; carry clear and left open if the disk in
; it is the cached one (CBM label and build id equal the cache header), else closed, carry set
ej_same:
        ldx #0
        jsr iec_open
        bcs @r
        lda dev_drive
        sta cur_drv
        lda #<BAM_BLOCK
        sta rq_lo
        lda #>BAM_BLOCK
        sta rq_hi
        jsr iec_read
        bcs @no
        ldx #15
        ldy #BAM_LABEL+15
@l:     lda (bp),y
        cmp c_hdr+8,x
        bne @no
        dey
        dex
        bpl @l
        lda #<SB_BLOCK
        sta rq_lo
        lda #>SB_BLOCK
        sta rq_hi
        jsr iec_read
        bcs @no
        ldx #3
        ldy #SB_BUILD_ID+3
@i:     lda (bp),y
        cmp c_hdr+4,x
        bne @no
        dey
        dex
        bpl @i
        clc
@r:     rts
@no:    ldx #0
        jsr iec_close
        lda #ENODEV             ; not the disk that was taken out
        sec
        rts

ebuf:   .res 256
