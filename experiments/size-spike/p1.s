.segment "ZEROPAGE"
tmp0: .res 1
tmp1: .res 1
tmp2: .res 1
.segment "BSS"
rq_lo: .res 1
rq_hi: .res 1
trk: .res 1
sct: .res 1
.segment "CODE"

.export spt, blk_to_ts, ts_block
spt:    lda #21
        cpy #17
        bcc @r
        lda #19
        cpy #24
        bcc @r
        lda #18
        cpy #30
        bcc @r
        lda #17
@r:     rts
blk_to_ts:
        lda rq_lo
        sta tmp0
        lda rq_hi
        sta tmp1
        ldy #0
@l:     jsr spt
        sta tmp2
        lda tmp0
        sec
        sbc tmp2
        tax
        lda tmp1
        sbc #0
        bcc @d
        stx tmp0
        sta tmp1
        iny
        bne @l
@d:     iny
        sty trk
        lda tmp0
        sta sct
        rts
ts_block:
        stx tmp0
        ldx #0
        tay
        dey
@l:     dey
        bmi @d
        jsr spt
        clc
        adc tmp0
        sta tmp0
        bcc @l
        inx
        bcs @l
@d:     txa
        tay
        ldx tmp0
        rts
