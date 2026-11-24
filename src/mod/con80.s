; con80.km: an 80 x 25 soft console (hires bitmap, 4 x 8 glyphs). `mod load /lib/km/con80` points
; the four console stubs of con.s at it and switches the VIC to the bitmap; `mod unload` puts the
; 40-column console back. Nothing of it is resident until loaded (docs/design/soft80-spike.md,
; docs/design/soft80-memory.md).
;
; Memory: its own pages (code and font, top of the pool) plus the fixed pages $20-$3F, claimed in
; the allocator by init (bitmap $2000-$3F3F, driver variables in the 192 bytes after it). The
; screen matrix is the text screen at $0400. Init fails with ENOMEM if a process holds a page in
; $20-$3F: unload or exit it first.
;
; The font (con80.font: 105 glyphs, screen codes 0-$68 (sc80 maps { | } ~ to $65-$68), 4 bytes each, packed one nibble per row
; pair; gp unpacks it) is the Novaterm 9.6 80-column font (misc/font80.novaterm), reordered to Breadbin's
; screen codes by tools/soft80_render.py. Source: novaterm-source.tgz at
; zimmers.net/pub/cbm/c64/comm/Novaterm/. Evidence for adopting it: owner-asserted public release
; of the source by its author, 2026-11-20; the tarball has no licence text. Credit: Novaterm's
; author Nick Rossi (public release c. 2000), and greetings to the Novaterm scene. Screen codes $1E and
; $1F (the up and down arrows) are our own redraw, a head on a stem, so they read at 4 x 8 and inverted.
MODULE  = 1
CUR_EXT = 1
FONT    = fontdata
.include "../../include/breadbin.inc"
.include "kexp.inc"

; p3..tmp3 are what the driver uses and what a console call may not disturb
.assert p4+5 = tmp0, error, "p3..tmp3 must be contiguous (k_a k_x k_n between p4 and tmp0)"
.assert tmp3-p3 = 10, error, "p3..tmp3 must be 11 bytes"

.include "con80.inc"

.segment "HEADER"
        jmp init
        jmp fini
        .word KAPI_HASH
        .byte $52               ; class 2: character device; name id 5 (src/bin/mod.s)

.segment "BSS"
cb:     .res 1                  ; the byte con_putc is writing

.segment "CODE"
; init is refused unless the kernel is loading the module (mod_busy), and for a second copy.
init:   lda mod_busy
        beq @no
        lda con_putc+1
        cmp #<c40_putc
        bne @no
        ldx #$18                ; pool pages $20-$3F are indices $18-$37
@f:     lda pg_used,x
        bne @nomem
        inx
        cpx #$38
        bne @f
        ldx #$18
        lda #1
@c:     sta pg_used,x
        inx
        cpx #$38
        bne @c
        lda free_pages
        sec
        sbc #32
        sta free_pages
        inc con_busy            ; no blink between the hide and the switch
        jsr cursor_hide         ; the 40-column cursor is on screen RAM we are about to reuse
        lda #$0b
        sta $d011               ; screen off while the matrix (screen RAM) and the bitmap are built
        jsr c80_init            ; matrix and a clear bitmap, before the VIC looks at them
        ldy #0
        jsr patch
        lda #$18                ; matrix $0400, bitmap $2000
        sta $d018
        lda #$3b                ; hires bitmap
        sta $d011
        dec con_busy
        clc
        rts
@nomem: lda #ENOMEM
        .byte $2c               ; bit abs: skip the lda below
@no:    lda #EBUSY
        sec
        rts

fini:   inc con_busy
        jsr c80_curhide
        ldy #8
        jsr patch               ; the stubs run the 40-column code again
        lda #$1b                ; text mode, lowercase set, screen at $0400
        sta $d011
        lda #$16
        sta $d018
        lda #$20
        ldy #32
        jsr page_free
        lda $0286
        jsr scr_color
        lda #$0c
        jsr con_putc            ; clear the screen (it is full of colour matrix)
        dec con_busy
        clc
        rts

; patch: Y = 0 (point the stubs at us) or 8 (back at the kernel's own code). The stubs are
; four consecutive jmps; the IRQ blink calls two of them.
patch:  php
        sei
        ldx #0
@l:     lda tab,y
        sta cursor_hide+1,x
        iny
        lda tab,y
        sta cursor_hide+2,x
        iny
        inx
        inx
        inx
        cpx #12
        bne @l
        plp
        rts

; con_write: r0 = buffer, r1 = count
m_write:
        lda r0
        sta p1
        lda r0+1
        sta p1+1
        lda r1
        sta p2
        lda r1+1
        sta p2+1
; run p1/p2 with the output flag up (no blink) and the driver's scratch saved
core:   inc con_busy
        ldx #10
@s:     lda p3,x
        pha
        dex
        bpl @s
        jsr c80_go
        ldx #0
@r:     pla
        sta p3,x
        inx
        cpx #11
        bne @r
        dec con_busy
        ldy #0                  ; as c40_write returns
        rts

; con_putc: A = the byte. Preserves A, X, Y and p1/p2.
m_putc: sta cb
        txa
        pha
        tya
        pha
        ldx #3
@s:     lda p1,x
        pha
        dex
        bpl @s
        lda #<cb
        sta p1
        lda #>cb
        sta p1+1
        lda #1
        sta p2
        lda #0
        sta p2+1
        jsr core
        ldx #0
@r:     pla
        sta p1,x
        inx
        cpx #4
        bne @r
        pla
        tay
        pla
        tax
        lda cb
        rts

; cursor_hide / cursor_show (also from the IRQ blink): X, Y and p3/tmp2 preserved
h_hide: clc
        .byte $24               ; bit zp: skip the sec
h_show: sec
        tya
        pha
        txa
        pha
        lda p3
        pha
        lda p3+1
        pha
        lda tmp2
        pha
        jsr c80_cur             ; (C as set above)
        pla
        sta tmp2
        pla
        sta p3+1
        pla
        sta p3
        pla
        tax
        pla
        tay
        rts

.segment "RODATA"
tab:    .word h_hide, h_show, m_putc, m_write           ; ours
        .word c40_hide, c40_show, c40_putc, c40_write   ; the kernel's
fontdata:
        .incbin "con80.font"
