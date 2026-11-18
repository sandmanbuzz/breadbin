; eject: let the boot disk out of drive 8 (single-drive systems with an REU and its block cache).
; Reads every used block of the disk into the cache first, so everything under / is served from
; the REU; then drive 8 is free for `mount 8 /mnt`. Writes to / sleep until `reattach`.
.include "../../include/breadbin.inc"
.import eprint, perr
BITMAP = 377                ; c64fs block bitmap: bit n of byte n/8 is set when block n is used
NBMB   = 86                 ; bitmap bytes in use: 683 blocks
blk    = $23                ; the block number being warmed
by     = $25                ; the bitmap byte
bits   = $26                ; its bits, shifted out
.segment "CODE"
        lda #<path          ; the module that does the work (already loaded: EBUSY, fine)
        sta r0
        lda #>path
        sta r0+1
        lda #4
        jsr SYS_CACHE
        bcc @ld
        cmp #EBUSY
        bne @err
@ld:    lda #<bm            ; the bitmap
        sta r0
        lda #>bm
        sta r0+1
        lda #<BITMAP
        sta r1
        lda #>BITMAP
        sta r1+1
        lda #9
        jsr SYS_CACHE
        bcs @err
        lda #0
        sta blk
        sta blk+1
        sta by
@byte:  ldy by
        lda bm,y
        sta bits
        ldx #8
@bit:   txa
        pha
        lsr bits
        bcc @nx
        lda blk+1           ; past the last block (the bitmap's last byte has spare bits)
        cmp #2
        bcc @rd
        lda blk
        cmp #171            ; 683 - 512
        bcs @nx
@rd:    lda #<tmp
        sta r0
        lda #>tmp
        sta r0+1
        lda blk
        sta r1
        lda blk+1
        sta r1+1
        lda #9
        jsr SYS_CACHE
        bcs @err1
@nx:    pla
        tax
        inc blk
        bne @c
        inc blk+1
@c:     dex
        bne @bit
        inc by
        lda by
        cmp #NBMB
        bne @byte
        lda #7              ; eject
        jsr SYS_CACHE
        bcs @err
        rts
@err1:  tax                 ; drop the saved X, keep the error
        pla
        txa
@err:   ldx #0
        ldy #0
        jsr perr
        lda #1
        jmp SYS_EXIT
.segment "RODATA"
path:   .byte "/lib/km/eject", 0
.segment "BSS"
bm:     .res 256
tmp:    .res 256
