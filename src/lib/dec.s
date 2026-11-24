; Breadbin user library: decimal output
.include "../../include/breadbin.inc"
.include "lib.inc"
.import print, putc
.export print_dec, print_dec_w, dec_str

.segment "BSS"
ldec:   .res 7

.segment "CODE"
; dec_str: A/X -> ldec, returns A/X pointer to first digit, Y = length
dec_str:
        sta lval
        stx lval+1
        ldy #6
        lda #0
        sta ldec+6
@dg:    lda #0
        ldx #16
@dv:    asl lval
        rol lval+1
        rol a
        cmp #10
        bcc @n
        sbc #10
        inc lval
@n:     dex
        bne @dv
        ora #'0'
        dey
        sta ldec,y
        lda lval
        ora lval+1
        bne @dg
        sty lt1
        lda #6
        sec
        sbc lt1
        tay
        lda lt1
        clc
        adc #<ldec
        ldx #>ldec
        bcc @r
        inx
@r:     rts

; print_dec: A/X unsigned to stdout
print_dec:
        jsr dec_str
        jmp print

; print_dec_w: A/X unsigned, right aligned in Y columns
print_dec_w:
        sty lt2
        jsr dec_str
        sta lp2
        stx lp2+1
        sty lt3
@pad:   lda lt3
        cmp lt2
        bcs @p
        lda #' '
        jsr putc
        inc lt3
        jmp @pad
@p:     lda lp2
        ldx lp2+1
        jmp print
