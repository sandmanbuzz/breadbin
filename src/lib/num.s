; Breadbin user library: numbers
.include "../../include/breadbin.inc"
.include "lib.inc"
.import print, putc
.export print_dec, print_dec_w, print_hex, parse_dec

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

; print_hex: A as two hex digits
print_hex:
        pha
        lsr a
        lsr a
        lsr a
        lsr a
        jsr @nib
        pla
        and #$0f
@nib:   cmp #10
        bcc @d
        adc #'a'-'0'-11
@d:     adc #'0'
        jmp putc

; parse_dec: A/X = string -> A/X = value; carry set if not a number
parse_dec:
        sta lp1
        stx lp1+1
        lda #0
        sta lval
        sta lval+1
        tay
        lda (lp1),y
        beq @bad
@l:     lda (lp1),y
        beq @ok
        sec
        sbc #'0'
        cmp #10
        bcs @bad
        sta lt0
        ; lval = lval*10 + digit
        lda lval
        ldx lval+1
        asl lval
        rol lval+1
        asl lval
        rol lval+1          ; *4
        clc
        adc lval
        sta lval
        txa
        adc lval+1
        sta lval+1          ; *5
        asl lval
        rol lval+1          ; *10
        lda lval
        clc
        adc lt0
        sta lval
        bcc @n
        inc lval+1
@n:     iny
        bne @l
@ok:    lda lval
        ldx lval+1
        clc
        rts
@bad:   sec
        rts
