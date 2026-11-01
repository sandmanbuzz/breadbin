; mod [ls | load PATH | unload SLOT]: kernel modules (root only for load and unload)
.include "../../include/breadbin.inc"
.import argn, eprint, print, print_dec_w, newline, perr, parse_dec
ptr = $23
idx = $25
.segment "CODE"
        lda argc
        cmp #1
        beq @ls
        lda #1
        jsr argn
        stx ptr+1
        sta ptr
        ldy #0
        lda (ptr),y
        cmp #'l'
        bne @notl
        iny
        lda (ptr),y
        cmp #'s'
        beq @ls
        cmp #'o'
        beq @load
        bne @usage
@notl:  cmp #'u'
        beq @unload
@usage: lda #<usage
        ldx #>usage
        jsr eprint
        lda #1
        jmp SYS_EXIT
@load:  lda argc
        cmp #3
        bne @usage
        lda #2
        jsr argn
        sta r0
        stx r0+1
        lda #4
        jsr SYS_CACHE
        bcc @ok
        ldx #0
        ldy #0
        jsr perr
        lda #1
        jmp SYS_EXIT
@unload: lda argc
        cmp #3
        bne @usage
        lda #2
        jsr argn
        jsr parse_dec
        bcs @usage
        tax
        lda #5
        jsr SYS_CACHE
        bcc @ok
        ldx #0
        ldy #0
        jsr perr
        lda #1
        jmp SYS_EXIT
@ok:    rts
@ls:    lda #<buf
        sta r0
        lda #>buf
        sta r0+1
        lda #6
        jsr SYS_CACHE
        ldx #0
@l:     lda buf,x
        beq @next
        stx idx
        lda #<s_slot
        ldx #>s_slot
        jsr print
        lda idx
        ; slot number = idx / 3
        lda idx
        ldy #0
@d:     cmp #3
        bcc @dd
        sbc #3
        iny
        bne @d
@dd:    tya
        ldx #0
        ldy #1
        jsr print_dec_w
        lda #<s_page
        ldx #>s_page
        jsr print
        ldx idx
        lda buf,x
        ldx #0
        ldy #1
        jsr print_dec_w
        lda #<s_np
        ldx #>s_np
        jsr print
        ldx idx
        lda buf+1,x
        ldx #0
        ldy #1
        jsr print_dec_w
        lda #<s_cls
        ldx #>s_cls
        jsr print
        ldx idx
        lda buf+2,x
        ldx #0
        ldy #1
        jsr print_dec_w
        jsr newline
        ldx idx
@next:  inx
        inx
        inx
        cpx #12
        bcc @l
        rts
.segment "RODATA"
usage:  .byte "usage: mod [ls | load PATH | unload SLOT]", 10, 0
s_slot: .byte "slot ", 0
s_page: .byte ": page ", 0
s_np:   .byte ", pages ", 0
s_cls:  .byte ", class ", 0
.segment "BSS"
buf: .res 12
