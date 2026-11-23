; Breadbin user library: strlen
.include "../../include/breadbin.inc"
.include "lib.inc"
.export strlen

.segment "CODE"
; strlen: A/X = string -> Y = A = length (max 255)
strlen:
        sta lp1
        stx lp1+1
        ldy #0
@l:     lda (lp1),y
        beq @d
        iny
        bne @l
        dey
@d:     tya
        rts
