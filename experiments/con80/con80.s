; con80: soft 80-column console core (POC): hires bitmap, 4x8 glyphs, see docs/design/soft80-spike.md.
;
; Host oracle: tools/soft80_render.py (the same algorithms). Test: tools/test_con80_sim.py, which
; assembles this file with the kernel's zero-page and label addresses and runs it in py65.
;
; Bank 0 layout (the kernel will choose; constants here for the POC):
;   BMP   $2000-$3F3F  bitmap, VIC cell order (40x25 cells x 8 bytes)
;   FONT  8 pages      row-planar: page I holds glyph row I of all 256 screen codes (kernel
;                      order, what to_screen returns), the 4 pixel columns in the high nibble
;                      AND the low nibble of every byte
; Stock zero page keeps its meaning: $D3 = column (0-79 here), $D6 = row.
; Scratch: p1/p2 (the con_write buffer), p3/p4 and tmp0-tmp3, all the kernel's.
;
; Not here yet: reverse video, cursor, ESC and backspace, the raster wait on scroll, colour RAM.
; Entry points: c80_init, c80_write (r0 = buffer, r1 = count, as con_write).
.ifndef BMP
BMP  = $2000
.endif
.ifndef FONT
FONT = $4000
.endif
.include "kernel_syms.inc"      ; test-generated: r0 r1 p1-p4 tmp0-tmp3 to_screen

.export c80_init, c80_write, lastpos

COLD = $d3
ROWD = $d6
dp   = p3                       ; destination pointer into the bitmap
sp   = p4                       ; source pointer for scroll copies
lc   = tmp0                     ; left glyph code
rc   = tmp1                     ; right glyph code
mk   = tmp2                     ; mask of the half being drawn
nl   = tmp3                     ; scratch

.segment "CODE"
; c80_init: blank the bitmap, home the cursor
c80_init:
        ; fall through
c80_clear:
        lda #<BMP
        sta dp
        lda #>BMP
        sta dp+1
        ldx #32                 ; 8192 bytes: the 8000 and the rest of the page
        ldy #0
        tya
@p:     sta (dp),y
        iny
        bne @p
        inc dp+1
        dex
        bne @p
        sty COLD
        sty ROWD
        ldx #24
@l:     tya
        sta lastpos,x
        dex
        bpl @l
        rts

; c80_write: r0 = buffer, r1 = count
c80_write:
        lda r0
        sta p1
        lda r0+1
        sta p1+1
        lda r1
        sta p2
        lda r1+1
        sta p2+1
@next:  lda p2
        ora p2+1
        beq @done
        ldy #0
        lda (p1),y
        cmp #$0a
        beq @lf
        cmp #$0c
        beq @ff
        cmp #$09
        beq @run
        cmp #$20
        bcc @skip               ; other controls: ignored for now
@run:   jsr run
        jmp @next
@ff:    jsr c80_clear
@skip:  jsr adv1
        jmp @next
@done:  clc
        rts

@lf:    jsr adv1
        jsr nextline
        jmp @next

; nextline: column 0 of the next row. At the bottom, scroll for the LFs still waiting in the
; buffer too, in one pass; the cursor lands n-1 rows above the bottom, so those LFs only move it.
nextline:
        lda #0
        sta COLD
        lda ROWD
        cmp #24
        bcs @sc
        inc ROWD
        rts
@sc:    jsr lookahead           ; A = rows to scroll
        pha
        jsr scroll
        pla
        eor #$ff
        sec
        adc #25                 ; row = 25 - n
        sta ROWD
        rts

; lookahead: A = 1 + the LFs waiting in the next 255 buffer bytes (at most 24 in all);
; FF and ESC end the scan (the screen is about to change under us)
lookahead:
        ldx #1
        ldy #0
        lda p2+1
        beq @l
        lda #255
        .byte $2c               ; bit: skip the next lda
@l:     lda p2
        sta nl                  ; bytes to scan
@s:     cpy nl
        bcs @d
        lda (p1),y
        iny
        cmp #$0a
        bne @n
        inx
        cpx #24
        beq @d
        bne @s
@n:     cmp #$0c
        beq @d
        cmp #$1b
        bne @s
@d:     txa
        rts

; adv1: one byte of the buffer consumed (keeps X, Y)
adv1:   inc p1
        bne @a
        inc p1+1
@a:     lda p2
        bne @b
        dec p2+1
@b:     dec p2
        rts

; run: collect printable chars from the buffer up to the end of this row, then draw them
run:    lda #80
        sec
        sbc COLD
        sta rlim
        lda p2+1                ; scan at most 255 bytes of the buffer
        beq @a
        lda #255
        .byte $2c
@a:     lda p2
        sta nl
        ldx #0                  ; X = chars collected, Y = bytes consumed
        ldy #0
@c:     cpy nl
        bcs @e
        lda (p1),y
        cmp #$09
        bne @n
        lda #$20                ; tab is a space
@n:     cmp #$20
        bcc @e                  ; a control char ends the run
        cpx rlim
        bcs @e                  ; the row is full
        iny
        jsr to_screen           ; (keeps X, Y)
        bcs @c                  ; prints nothing
        sta rb,x
        inx
        jmp @c
@e:     stx rn
        tya                     ; consume Y bytes
        clc
        adc p1
        sta p1
        bcc @1
        inc p1+1
@1:     sty nl
        lda p2
        sec
        sbc nl
        sta p2
        bcs @2
        dec p2+1
@2:     lda rn
        beq @r
        jsr draw
        lda COLD
        clc
        adc rn
        sta COLD
        cmp #80
        bcc @r
        jmp nextline            ; wrapped
@r:     rts

; draw: rb[0..rn) at (COLD, ROWD): an odd first char, whole pairs, an odd last char
draw:   ldx ROWD
        jsr setdp
        lda COLD
        lsr a
        jsr addcell             ; dp += (COLD/2)*8
        ldx #0
        lda COLD
        and #1
        beq @pairs
        lda rb                  ; first char is the right half of its cell
        sta lc
        lda #$0f
        jsr one
        jsr nextcell
        ldx #1
@pairs: stx di
@pl:    lda rn
        sec
        sbc di
        cmp #2
        bcc @last
        ldx di
        lda rb,x
        sta lc
        lda rb+1,x
        sta rc
        jsr pair
        jsr nextcell
        inc di
        inc di
        jmp @pl
@last:  tax
        beq @hw                 ; none left
        ldx di
        lda rb,x
        sta lc
        lda #$f0
        jsr one
@hw:    lda COLD                ; high-water mark: columns drawn on this row
        clc
        adc rn
        ldx ROWD
        cmp lastpos,x
        bcc @ok
        sta lastpos,x
@ok:    rts

; setdp: X = row -> dp = its first cell
setdp:  lda rowlo,x
        sta dp
        lda rowhi,x
        sta dp+1
        rts

; addcell: dp += A*8 (A = 0-39)
addcell:
        sta di
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        sta nl                  ; high byte of A*8
        lda di
        asl a
        asl a
        asl a
        clc
        adc dp
        sta dp
        lda dp+1
        adc nl
        sta dp+1
        rts

nextcell:
        lda dp
        clc
        adc #8
        sta dp
        bcc @r
        inc dp+1
@r:     rts

; pair: lc, rc -> the cell at dp, whole bytes, no read
pair:
.repeat 8, I
        ldx lc
        lda FONT+256*I,x
        and #$f0
        sta mk
        ldx rc
        lda FONT+256*I,x
        and #$0f
        ora mk
        ldy #I
        sta (dp),y
.endrepeat
        rts

; one: lc drawn into the half of the cell at dp that A masks ($f0 left, $0f right)
one:    sta mk
        eor #$ff
        sta mi
        ldx lc
.repeat 8, I
        lda FONT+256*I,x
        and mk
        sta nl
        ldy #I
        lda (dp),y
        and mi
        ora nl
        sta (dp),y
.endrepeat
        rts

; scroll: A = rows (1-24) up. Each row copies only as far as the wider of the two rows'
; high-water marks; the rows left at the bottom are blanked as far as they were drawn.
scroll: sta scn
        lda #0
        sta srow
@row:   lda srow
        clc
        adc scn
        sta ssrc
        tay
        lda lastpos,y
        ldx srow
        cmp lastpos,x
        bcs @w
        lda lastpos,x
@w:     jsr bytes               ; cnt = bytes to move
        ldx ssrc
        lda rowlo,x
        sta sp
        lda rowhi,x
        sta sp+1
        ldx srow
        jsr setdp
        jsr copy
        ldx srow
        ldy ssrc
        lda lastpos,y
        sta lastpos,x
        inc srow
        lda #25
        sec
        sbc scn
        cmp srow
        bne @row
@clr:   ldx srow
        lda lastpos,x
        jsr bytes
        ldx srow
        jsr setdp
        jsr fill
        ldx srow
        lda #0
        sta lastpos,x
        inc srow
        lda srow
        cmp #25
        bne @clr
        rts

; bytes: A = columns -> cnt = ((A+1)/2)*8
bytes:  clc
        adc #1
        lsr a
        sta cnt
        lda #0
        sta cnt+1
        asl cnt
        rol cnt+1
        asl cnt
        rol cnt+1
        asl cnt
        rol cnt+1
        rts

; copy: cnt bytes (a multiple of 8) from (sp) to (dp), ascending, eight to the loop
copy:   ldx cnt+1
        beq @rem
@pg:    ldy #0
@p:
.repeat 8
        lda (sp),y
        sta (dp),y
        iny
.endrepeat
        bne @p
        inc sp+1
        inc dp+1
        dex
        bne @pg
@rem:   lda cnt
        beq @d
        ldy #0
@r:
.repeat 8
        lda (sp),y
        sta (dp),y
        iny
.endrepeat
        cpy cnt
        bne @r
@d:     rts

; fill: cnt zero bytes at (dp)
fill:   ldx cnt+1
        beq @rem
@pg:    ldy #0
        tya
@p:     sta (dp),y
        iny
        bne @p
        inc dp+1
        dex
        bne @pg
@rem:   ldy cnt
        beq @d
        lda #0
@r:     dey
        sta (dp),y
        bne @r
@d:     rts

.segment "RODATA"
rowlo:  .repeat 25, I
        .byte <(BMP+I*320)
        .endrepeat
rowhi:  .repeat 25, I
        .byte >(BMP+I*320)
        .endrepeat

.segment "BSS"
lastpos: .res 25
rb:     .res 80                 ; the run being drawn, as screen codes
rn:     .res 1
rlim:   .res 1
di:     .res 1
mi:     .res 1
scn:    .res 1
srow:   .res 1
ssrc:   .res 1
cnt:    .res 2
