; con80: soft 80-column console core (POC): hires bitmap, 4x8 glyphs, see docs/design/soft80-spike.md.
;
; Host oracle: tools/soft80_render.py (the same algorithms). Test: tools/test_con80_sim.py, which
; assembles this file with the kernel's zero-page and label addresses and runs it in py65.
;
; Bank 0 layout (the kernel will choose; constants here for the POC):
;   BMP   $2000-$3F3F  bitmap, VIC cell order (40x25 cells x 8 bytes); the BSS sits in the
;                      192 bytes after it ($3F40-$3FFF), which c80_clear zeroes with the bitmap
;   FONT  420 bytes    glyph-major, 4 bytes per screen code 0-$68 (to_screen's 0-$64, sc80's $65-$68): byte j =
;                      row j in the high nibble, row j+4 in the low (4 pixel columns a nibble);
;                      gp unpacks a glyph into the 20-byte gl/gr buffers that put reads
; Stock zero page keeps its meaning: $D3 = column (0-79 here), $D6 = row.
; Scratch: p1/p2 (the con_write buffer), p3/p4 and tmp0-tmp3, all the kernel's.
;
; Console features as con.s: reverse ($C7, ended by LF, cleared by FF), backspace, ESC = R r K C, and
; a cursor (XOR of the half cell; c80_curshow / c80_curhide for the IRQ blink, c80_write hides it
; first). The colour matrix is (fg << 4) | bg from $0286 and $D021, refilled by ESC C.
; Not here yet: the raster wait on scroll.
; Entry points: c80_init, c80_write (r0 = buffer, r1 = count, as con_write), c80_curshow, c80_curhide.
.ifndef BMP
BMP  = $2000
.endif
.ifndef MATRIX
MATRIX = $0400
.endif
.ifndef FONT
FONT = $4000
.endif
.ifndef MODULE
.include "kernel_syms.inc"      ; test-generated: r0 r1 p1-p4 tmp0-tmp3 to_screen
.endif

.export c80_init, c80_go, c80_curshow, c80_curhide, lastpos, esc_st
.ifndef MODULE
.export c80_write
.endif

COLD = $d3
ROWD = $d6
dp   = p3                       ; destination pointer into the bitmap
sp   = p4                       ; source pointer for scroll copies
nl   = tmp2                     ; scratch
xv   = tmp3                     ; put: the nibbles to flip for reverse video
REV  = $c7

; c80_init: colour matrix, then c80_clear
c80_init:
        jsr matrix
        ; fall through

; c80_clear: blank the bitmap (and the BSS after it), home the cursor, reverse off
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
        sty REV
        rts

; matrix: the colour matrix (1000 bytes at MATRIX) = (fg << 4) | bg
matrix: lda $0286
        asl a
        asl a
        asl a
        asl a
        sta nl
        lda $d021
        and #15
        ora nl
        ldy #0
@a:     sta MATRIX,y
        sta MATRIX+$100,y
        sta MATRIX+$200,y
        iny
        bne @a
@b:     sta MATRIX+$300,y
        iny
        cpy #232
        bne @b
        rts

.ifndef MODULE
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
.endif
; c80_go: p1 = buffer, p2 = count
c80_go: jsr c80_curhide
@next:  lda p2
        ora p2+1
        beq @done
        ldy #0
        lda (p1),y
        ldx esc_st
        beq @n0
        jsr escape
        jmp @skip
@n0:    cmp #$0a
        beq @lf
        cmp #$0c
        beq @ff
        cmp #$08
        beq @bs
        cmp #$1b
        beq @esc
        cmp #$09
        beq @run
        cmp #$20
        bcc @skip               ; other controls: ignored
@run:   jsr run
        jmp @next
@ff:    jsr c80_clear
        jmp @skip
@bs:    jsr bs
        jmp @skip
@esc:   inc esc_st
@skip:  jsr adv1
        jmp @next
@done:  clc
        rts

@lf:    jsr adv1
        lda #0
        sta REV                 ; a newline ends reverse
        jsr nextline
        jmp @next

; escape: A = the next byte of an escape sequence, X = esc_st (not 0)
;   ESC = row+32 col+32 | R | r | K | C fg+32 bg+32 border+32 (states 2,3 / 4,5,6)
escape: cpx #2
        bcc @cmd
        sbc #32                 ; (carry set)
        inc esc_st
        cpx #4
        bcc @rc
        beq @fg
        cpx #6
        bcc @bg
        sta $d020
        bcs @end
@rc:    cpx #3
        beq @col
        sta erow
        rts
@col:   cmp #80
        bcc @c1
        lda #79
@c1:    sta COLD
        lda erow
        cmp #25
        bcc @r1
        lda #24
@r1:    sta ROWD
@end:   lda #0
        sta esc_st
        rts
@fg:    and #15
        sta $0286
        jmp matrix
@bg:    sta $d021
        jmp matrix
@cmd:   ldx #0
        stx esc_st
        cmp #'='
        bne @n1
        ldx #2
@set:   stx esc_st
        rts
@n1:    cmp #'C'
        bne @n2
        ldx #4
        bne @set
@n2:    cmp #'r'
        beq @rev                ; (X = 0)
        cmp #'R'
        bne @n3
        ldx #$12
@rev:   stx REV
        rts
@n3:    cmp #'K'
        bne @set                ; (X = 0: esc_st stays 0)
        ; fall through

; eol: blank from the cursor to the end of the row (only as far as the row was drawn), a half
; cell at a time; the high-water mark comes down to the cursor
eol:    lda COLD
        pha
@l:     ldx ROWD
        lda COLD
        cmp lastpos,x
        bcs @d
        jsr cellp
        eor #$ff
        jsr clrh
        inc COLD
        bne @l                  ; (always: COLD < 80)
@d:     pla
        sta COLD
        cmp lastpos,x
        bcs @r
        sta lastpos,x
@r:     rts

; bs: cursor left one column (up a row from column 0), blank that half cell
bs:     lda COLD
        bne @l
        lda ROWD
        beq clrr
        dec ROWD
        lda #80
        sta COLD
@l:     dec COLD
        jsr cellp
        eor #$ff
        ; fall through
; clrh: A = bits to keep: (dp)[0..7] &= A
clrh:   sta nl
        ldy #7
@c:     lda (dp),y
        and nl
        sta (dp),y
        dey
        bpl @c
clrr:   rts

; the cursor: the half cell at (COLD, ROWD) XORed, with a flag
c80_curhide:
        clc
        .byte $24               ; bit zp: skip the sec
c80_curshow:
        sec
; c80_cur: C = wanted state; toggles only when drawn + C = 1. cur_vis is drawn when nonzero (c40_show
; tests it so); a toggle writes it back as 0 or 1, so a stray value can never flip the cursor twice
c80_cur:
        php                     ; C is the wanted state; kept for the write at the end
        lda cur_vis
        beq @z
        lda #1
@z:     adc #0
        lsr a
        bcc cur_none
tog:    jsr cellp
        sta nl
        ldy #7
@l:     lda (dp),y
        eor nl
        sta (dp),y
        dey
        bpl @l
        plp
        lda #0
        adc #0                  ; the wanted state, as 0 or 1
        sta cur_vis
        rts
cur_none: plp
        rts

; sc80: A = ASCII -> screen code, as to_screen (carry set: prints nothing). { | } ~ ($7B-$7E) are
; the glyphs $65-$68, after the kernel's own 101; everything else is to_screen's.
sc80:   cmp #$7b
        bcc @k
        cmp #$7f
        bcs @k
        sec
        sbc #$16
        clc
        rts
@k:     jmp to_screen

; cellp: dp = the cell of (COLD, ROWD); carry = odd column; A = the half's pixel mask ($f0 / $0f)
cellp:  lda ROWD
        ldx #dp
        jsr setp
        lda COLD
        lsr a
        php
        jsr addcell
        plp
        lda #$f0
        bcc @r
        lda #$0f
@r:     rts

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
        beq @d
        cmp #$08
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
        jsr sc80                ; (keeps X, Y)
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
draw:   jsr cellp
        ldx #0
        bcc @pairs
        lda rb                  ; odd column: the first char is the right half of its cell
        ldx #8
        jsr gp
        ldx #0
        jsr cpdp
        lda #$0f
        jsr sx
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
        ldx #0
        jsr gp
        pla
        ldx #8
        jsr gp
        lda #$ff
        jsr sx
        jsr put
        jsr nextcell
        inc di
        inc di
        bne @pl                 ; (always: di < 80)
@last:  tax
        beq @hw                 ; none left
        ldx di
        lda rb,x
        ldx #0
        jsr gp
        ldx #12
        jsr cpdp
        lda #$f0
        jsr sx
        jsr put                 ; the left half: the glyph first, the old cell second
@hw:    lda COLD                ; high-water mark: columns drawn on this row
        clc
        adc rn
        ldx ROWD
        cmp lastpos,x
        bcc @ok
        sta lastpos,x
@ok:    rts

; sx: A = the nibbles of the cell being drawn -> xv = those if reverse video, else 0
sx:     ldx REV
        bne @r
        lda #0
@r:     sta xv
        rts

; put: (dp)[0..7] = (gl & $f0) | (gr & $0f), then ^ xv: gl and gr are 8-byte glyph or old-cell buffers
put:    ldy #7
@l:     lda gr,y
        eor gl,y
        and #$0f
        eor gl,y
        eor xv
        sta (dp),y
        dey
        bpl @l
        rts

; gp: A = screen code, X = buffer (0 = gl, 8 = gr-4) <- that glyph. The font holds 4 bytes a glyph:
; byte j = row j in the high nibble, row j+4 in the low. Stored: byte j at X+j and X+8+j, its nibbles
; swapped at X+4+j, so gl+y has row y in its high nibble and gr+y (= gl+12+y) row y in its low one,
; which is what put reads. (X, Y trashed; the font operand below is patched with the page.)
gp:     asl a
        asl a                   ; C = code >= 64, A = the rest of code*4
        tay
        lda #>FONT
        adc #0
        sta @f+2
@f:     lda FONT,y
        sta gl,x
        sta gl+8,x
        asl a                   ; swap the nibbles
        adc #$80
        rol a
        asl a
        adc #$80
        rol a
        sta gl+4,x
        iny
        inx
        txa
        and #3
        bne @f
        rts

; cpdp: X = buffer (0 = gl / 12 = gr) <- the 8 bytes at (dp), the old cell
cpdp:   ldy #0
@l:     lda (dp),y
        sta gl,x
        inx
        iny
        cpy #8
        bne @l
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
; high-water marks; a row whose source is below the screen copies itself through a zero mask,
; as far as it was drawn, which blanks it.
scroll: sta scn
        ldx #0
@row:   stx srow
        txa
        clc
        adc scn
        ldy #$ff                ; the mask: copy
        cmp #25
        bcc @on
        txa                     ; below the screen: blank (source = dest, mask 0)
        iny
@on:    sta ssrc
        tya
        pha
        ldy ssrc
        lda lastpos,y
        cmp lastpos,x
        bcs @w
        lda lastpos,x
@w:     lsr a
        adc #0
        sta cnt                 ; cells = (columns+1)/2
        lda ssrc
        ldx #sp
        jsr setp
        lda srow
        ldx #dp
        jsr setp
        pla
        sta nl
        jsr copy
        ldx srow
        ldy ssrc
        lda lastpos,y
        and nl
        sta lastpos,x
        inx
        cpx #25
        bne @row
        rts

; copy: cnt cells (8 bytes each) from (sp) to (dp), ANDed with nl, ascending, a cell to the loop
copy:   ldx cnt
        beq @d
        ldy #0
@c:
.repeat 8
        lda (sp),y
        and nl
        sta (dp),y
        iny
.endrepeat
        bne @n                  ; Y wraps every 32 cells
        inc sp+1
        inc dp+1
@n:     dex
        bne @c
@d:     rts

; BSS: the 192 bytes after the bitmap (c80_clear zeroes them with it); lastpos must come first
lastpos = BMP+8000
rb      = lastpos+25            ; the run being drawn, as screen codes (80)
rn      = rb+80
rlim    = rn+1
di      = rlim+1
scn     = di+1
srow    = scn+1
ssrc    = srow+1
cnt     = ssrc+1
esc_st  = cnt+1                 ; escape sequence state (as con.s)
erow    = esc_st+1
gl      = erow+2                ; glyph buffers, 20 bytes (gl, gr = gl+12; erow+1 is cur_vis when standalone)
gr      = gl+12
.ifndef CUR_EXT
cur_vis = erow+1                ; cursor drawn (the kernel's own flag in the module: the IRQ blink reads it)
.endif
