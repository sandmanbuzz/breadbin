; Breadbin user library: decimal input
.include "../../include/breadbin.inc"
.include "lib.inc"
.export parse_dec

.segment "CODE"
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
