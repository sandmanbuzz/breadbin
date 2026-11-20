; con80: soft 80-column console core (POC): hires bitmap, 4x8 glyphs, see docs/design/soft80-spike.md.
;
; Host oracle: tools/soft80_render.py (the same algorithms). Test: tools/test_con80_sim.py, which
; assembles this file with the kernel's zero-page and label addresses and runs it in py65.
;
; Bank 0 layout (the kernel will choose; constants here for the POC):
;   BMP   $2000-$3F3F  bitmap, VIC cell order (40x25 cells x 8 bytes); the BSS sits in the
;                      192 bytes after it ($3F40-$3FFF), which c80_clear zeroes with the bitmap
;   FONT  808 bytes    glyph-major, 8 bytes per screen code 0-$64 (what to_screen returns), the 4
;                      pixel columns in the high nibble AND the low nibble of every byte; FONT is
;                      page aligned (a glyph pointer is code*8, its low byte alone)
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
.assert <FONT = 0, error, "FONT must be page aligned"
.include "kernel_syms.inc"      ; test-generated: r0 r1 p1-p4 tmp0-tmp3 to_screen

.export c80_init, c80_write, lastpos

COLD = $d3
ROWD = $d6
dp   = p3                       ; destination pointer into the bitmap
sp   = p4                       ; source pointer for scroll copies
pp   = p4                       ; put: first source (shares sp: scroll and draw never overlap)
qq   = tmp0                     ; put: second source (tmp0/tmp1)
nl   = tmp2                     ; scratch

.segment "CODE"
; c80_init: blank the bitmap (and the BSS after it), home the cursor
c80_init:
        ; fall through
c80_clear:
        lda #<BMP
        sta dp
        lda #>BMP
        sta dp+1
        ldx #32                 ; 8192 bytes: the 8000 and the BSS tail (lastpos = 0)
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
        jsr limit               ; nl = bytes to scan
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

; limit: nl = min(255, p2)
limit:  lda p2+1
        beq @a
        lda #255
        .byte $2c               ; bit: skip the next lda
@a:     lda p2
        sta nl
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
        jsr limit
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
        sty nl                  ; consume Y bytes
        tya
        clc
        adc p1
        sta p1
        bcc @1
        inc p1+1
@1:     lda p2
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
draw:   lda ROWD
        ldx #dp
        jsr setp
        lda COLD
        lsr a
        php
        jsr addcell             ; dp += (COLD/2)*8
        plp
        ldx #0
        bcc @pairs
        lda rb                  ; odd column: the first char is the right half of its cell
        ldx #qq
        jsr gp
        ldx #pp
        jsr cpdp
        jsr put
        jsr nextcell
        ldx #1
@pairs: stx di
@pl:    lda rn
        sec
        sbc di
        cmp #2
        bcc @last
        ldx di
        lda rb+1,x
        pha
        lda rb,x
        ldx #pp
        jsr gp
        pla
        ldx #qq
        jsr gp
        jsr put
        jsr nextcell
        inc di
        inc di
        bne @pl                 ; (always: di < 80)
@last:  tax
        beq @hw                 ; none left
        ldx di
        lda rb,x
        ldx #pp
        jsr gp
        ldx #qq
        jsr cpdp
        jsr put                 ; the left half: the glyph first, the old cell second
@hw:    lda COLD                ; high-water mark: columns drawn on this row
        clc
        adc rn
        ldx ROWD
        cmp lastpos,x
        bcc @ok
        sta lastpos,x
@ok:    rts

; put: (dp)[0..7] = (pp & $f0) | (qq & $0f), the eor form so that a half can come from the old
; cell itself (pointing pp or qq at dp)
put:    ldy #7
@l:     lda (qq),y
        eor (pp),y
        and #$0f
        eor (pp),y
        sta (dp),y
        dey
        bpl @l
        rts

; gp: A = screen code, X = zero page pointer -> that pointer = FONT + A*8 (FONT page aligned)
gp:     sta 0,x
        lda #0
        asl 0,x
        rol a
        asl 0,x
        rol a
        asl 0,x
        rol a
        adc #>FONT              ; (carry is clear: A was under 32)
        sta 1,x
        rts

; cpdp: X = zero page pointer -> that pointer = dp
cpdp:   lda dp
        sta 0,x
        lda dp+1
        sta 1,x
        rts

; setp: A = row, X = zero page pointer -> that pointer = BMP + row*320 (= (row*5)<<6)
setp:   sta nl
        asl a
        asl a
        adc nl                  ; 5*row (at most 120)
        pha
        lsr a
        lsr a
        clc
        adc #>BMP
        sta 1,x
        pla
        and #3
        lsr a
        ror a
        ror a
        sta 0,x
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
@w:     jsr cells
        lda ssrc
        ldx #sp
        jsr setp
        lda srow
        ldx #dp
        jsr setp
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
        jsr cells
        lda srow
        ldx #dp
        jsr setp
        jsr fill
        ldx srow
        lda #0
        sta lastpos,x
        inc srow
        lda srow
        cmp #25
        bne @clr
        rts

; cells: A = columns -> A, cnt = cells ((A+1)/2)
cells:  clc
        adc #1
        lsr a
        sta cnt
        rts

; copy: cnt cells (8 bytes each) from (sp) to (dp), ascending, a cell to the loop
copy:   ldx cnt
        beq @d
        ldy #0
@c:
.repeat 8
        lda (sp),y
        sta (dp),y
        iny
.endrepeat
        bne @n                  ; Y wraps every 32 cells
        inc sp+1
        inc dp+1
@n:     dex
        bne @c
@d:     rts

; fill: cnt cells of zeros at (dp)
fill:   ldx cnt
        beq @d
@c:     ldy #7
        lda #0
@b:     sta (dp),y
        dey
        bpl @b
        jsr nextcell
        dex
        bne @c
@d:     rts

.segment "BSS"                  ; link at BMP+8000 (the tail of the bitmap's last page)
lastpos: .res 25                ; first: c80_clear zeroes it with the bitmap
.assert lastpos = BMP+8000, error, "lastpos must be the first byte after the bitmap"
rb:     .res 80                 ; the run being drawn, as screen codes
rn:     .res 1
rlim:   .res 1
di:     .res 1
scn:    .res 1
srow:   .res 1
ssrc:   .res 1
cnt:    .res 1
