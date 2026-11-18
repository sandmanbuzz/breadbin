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
        jsr pname
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
        and #$0f
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
; pname: print " (name)" for the slot at idx, from the high nibble of its class byte; nothing if 0
pname:  ldx idx
        lda buf+2,x         ; the class byte: high nibble = module name id (0 = unnamed)
        lsr a
        lsr a
        lsr a
        lsr a
        beq @r
        cmp #5
        bcc @nm
        lda #0              ; unknown id: "?"
@nm:    asl a
        sta nid
        lda #<s_op
        ldx #>s_op
        jsr print
        ldx nid
        lda names,x
        pha
        lda names+1,x
        tax
        pla
        jsr print
        lda #<s_cp
        ldx #>s_cp
        jsr print
@r:     rts
.segment "RODATA"
usage:  .byte "usage: mod [ls | load PATH | unload SLOT]", 10, 0
s_slot: .byte "slot ", 0
s_page: .byte ": page ", 0
s_np:   .byte ", pages ", 0
s_op:   .byte " (", 0
s_cp:   .byte ")", 0
n_unk:  .byte "?", 0
n_cbm:  .byte "cbm", 0
n_uci:  .byte "uci", 0
n_fast: .byte "fast", 0
n_d81:  .byte "d81", 0
names:  .word n_unk, n_cbm, n_uci, n_fast, n_d81
s_cls:  .byte ", class ", 0
.segment "BSS"
buf: .res 12
nid: .res 1
