; con80 tech demo: a standalone PRG that runs the con80 core on a bare C64 and plays a script
; (built by tools/con80_demo.py, which also generates kernel_syms.inc and the font/script data).
; It takes the machine over: SEI, VIC bank 0, hires bitmap at $2000, colour matrix at $0400.
; No KERNAL, no IEC, no disk. `to_screen` below is con.s's, copied (the kernel's is not linked here).
.include "con80.s"

.segment "FONTSEG"
        .incbin "font_glyph.bin"        ; 808 bytes (101 glyphs), written by the tool; the code follows it

.segment "GLUE"
sptr    = $60
dly     = $62
tl      = $63

start:  sei
        cld
        ldx #$ff
        txs
        lda #$03
        sta $dd02
        lda $dd00
        ora #$03                ; VIC bank 0
        sta $dd00
        lda #$18                ; matrix $0400, bitmap $2000
        sta $d018
        lda #$08
        sta $d016
        lda #$3b                ; bitmap mode, 25 rows, display on
        sta $d011
        lda #DEMO_BORDER
        sta $d020
        lda #DEMO_COLOUR >> 4   ; c80_init fills the colour matrix from $0286 (fg) and $d021 (bg)
        sta $0286
        lda #DEMO_COLOUR & 15
        sta $d021
        lda #<script
        sta sptr
        lda #>script
        sta sptr+1
        jsr c80_init
play:   jsr fetch
        cmp #1
        beq @wait
        cmp #2
        beq @clr
        cmp #3
        beq @wr
        cmp #4
        beq @ty
        jmp *                   ; end of script: hold the last screen
@wait:  jsr fetch
        tax
        jsr frames
        jmp play
@clr:   lda #$0c
        sta chbuf
        lda #<chbuf
        sta r0
        lda #>chbuf
        sta r0+1
        lda #1
        sta r1
        lda #0
        sta r1+1
        jsr c80_write
        jmp play
@wr:    jsr fetch
        sta r1
        lda #0
        sta r1+1
        lda sptr
        sta r0
        lda sptr+1
        sta r0+1
        jsr c80_write
        lda sptr                ; skip the chunk
        clc
        adc r1
        sta sptr
        bcc play
        inc sptr+1
        jmp play
@ty:    jsr fetch
        sta dly
        jsr fetch
        sta tl
@t:     lda sptr
        sta r0
        lda sptr+1
        sta r0+1
        lda #1
        sta r1
        lda #0
        sta r1+1
        jsr c80_write
        jsr fetch               ; step over the char
        ldx dly
        jsr frames
        dec tl
        bne @t
        jmp play

fetch:  ldy #0
        lda (sptr),y
        inc sptr
        bne @r
        inc sptr+1
@r:     rts

; frames: wait X frames (X >= 1) by watching the raster pass line $FB
frames: lda $d012
        cmp #$fb
        bne frames
@g:     lda $d012
        cmp #$fb
        beq @g
        dex
        bne frames
        rts

; to_screen: ASCII (A) -> screen code in the lowercase set. Carry set if it prints nothing.
to_screen:
        cmp #$20
        bcc @none
        cmp #$40
        bcc @same
        beq @at
        cmp #$5b
        bcc @same
        cmp #$5f
        bcc @m1f
        beq @under
        cmp #$61
        bcc @none
        cmp #$7b
        bcc @m1f
        cmp #$7c
        beq @bar
        lda #$3f
@same:  clc
        rts
@none:  sec
        rts
@at:    lda #0
        clc
        rts
@m1f:   and #$1f
        clc
        rts
@under: lda #$64
        clc
        rts
@bar:   lda #$5d
        clc
        rts

.segment "BSS"
chbuf:  .res 1

.segment "GLUE"
script:                         ; the tool appends the compiled script here
        .incbin "script.bin"
