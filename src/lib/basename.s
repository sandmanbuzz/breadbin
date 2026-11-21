; Breadbin user library: basename
.include "../../include/breadbin.inc"
.include "lib.inc"
.export basename

.segment "CODE"
; basename: A/X = path -> A/X = part after the last '/'
basename:
        sta lp1
        stx lp1+1
        ldy #0
        sty lt0
@l:     lda (lp1),y
        beq @d
        iny
        cmp #'/'
        bne @l
        sty lt0
        jmp @l
@d:     lda lp1
        clc
        adc lt0
        ldx lp1+1
        bcc @r
        inx
@r:     rts
