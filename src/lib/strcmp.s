; Breadbin user library: strcmp
.include "../../include/breadbin.inc"
.include "lib.inc"
.export strcmp

.segment "CODE"
; strcmp: (lp1) vs (lp2) -> Z set if equal
strcmp:
        ldy #0
@l:     lda (lp1),y
        cmp (lp2),y
        bne @r
        cmp #0
        beq @r
        iny
        bne @l
@r:     rts
