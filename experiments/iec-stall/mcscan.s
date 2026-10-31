; mcscan: the kernel's block-read sequence at machine speed, through the stock KERNAL's own routines,
; in the stock environment (screen on, KERNAL IRQ running). Isolates "cadence of bus operations" from
; "Breadbin's C64 state". Per block: U1:2 0 t s on channel 15, read the status, read 256 bytes from
; channel 2 (open on "#"). 512 blocks over a spread of tracks. Progress: cnt ($C7F1/2), done ($C7F0).
; Assemble: ca65 mcscan.s -o mcscan.o && ld65 -t none -S 0xC000 -o mcscan.bin mcscan.o   (see mcscan.py)
CHROUT = $FFD2
CHRIN  = $FFCF
OPEN   = $FFC0
SETLFS = $FFBA
SETNAM = $FFBD
CHKIN  = $FFC6
CHKOUT = $FFC9
CLRCHN = $FFCC

burn = $C7E0                ; 0 = off; else every IRQ tick burns burn * ~1.3 ms before the stock handler
crflag = $C7E5             ; nonzero: end each command with a carriage return (BASIC does); zero: only EOI (the kernel does)
oldirq = $C7E2              ; the vector we replaced (2 bytes)
done = $C7F0
cnt  = $C7F1                ; 2 bytes
buf  = $C800
tt   = $FB
ss   = $FC
idx  = $FD

        .segment "CODE"
start:  lda burn
        beq @noirq
        sei
        lda $0314
        sta oldirq
        lda $0315
        sta oldirq+1
        lda #<slow
        sta $0314
        lda #>slow
        sta $0315
        cli
@noirq: lda #0
        sta done
        sta cnt
        sta cnt+1
        lda #15             ; OPEN 15,8,15
        ldx #8
        ldy #15
        jsr SETLFS
        lda #0
        jsr SETNAM
        jsr OPEN
        lda #2              ; OPEN 2,8,2,"#"
        ldx #8
        ldy #2
        jsr SETLFS
        lda #1
        ldx #<hash
        ldy #>hash
        jsr SETNAM
        jsr OPEN
loop:   lda cnt             ; track = (13 * cnt) mod 35 + 1
        asl a
        asl a
        sta idx
        asl a
        clc
        adc idx
        clc
        adc cnt
@m:     cmp #35
        bcc @md
        sbc #35
        bcs @m
@md:    clc
        adc #1
        sta tt
        lda cnt             ; sector = (7 * cnt) mod 17
        asl a
        asl a
        asl a
        sec
        sbc cnt
@n:     cmp #17
        bcc @nd
        sbc #17
        bcs @n
@nd:    sta ss
        ldx #15             ; the command
        jsr CHKOUT
        lda #0
        sta idx
@c:     ldy idx
        lda cmd,y
        beq @e
        jsr CHROUT
        inc idx
        bne @c
@e:     lda tt
        jsr pr2
        lda #' '
        jsr CHROUT
        lda ss
        jsr pr2
        lda crflag
        beq @nocr
        lda #13
        jsr CHROUT
@nocr:  jsr CLRCHN
        ldx #15             ; the status
        jsr CHKIN
@s:     jsr CHRIN
        cmp #13
        bne @s
        jsr CLRCHN
        ldx #2              ; the block
        jsr CHKIN
        lda #0
        sta idx
@d:     jsr CHRIN
        ldy idx
        sta buf,y
        inc idx
        bne @d
        jsr CLRCHN
        inc cnt
        bne @k
        inc cnt+1
@k:     lda cnt+1
        cmp #2
        bcs @fin
        jmp loop
@fin:   lda #1
        sta done
        rts

slow:   ldx burn            ; the IRQ handler under test: waste burn * ~1.3 ms, then the stock one
@o:     ldy #0
@i:     dey
        bne @i
        dex
        bne @o
        jmp (oldirq)

pr2:    ldx #'0'            ; A = 0..99 as two decimal digits
@t:     cmp #10
        bcc @u
        sbc #10
        inx
        bne @t
@u:     pha
        txa
        jsr CHROUT
        pla
        clc
        adc #'0'
        jmp CHROUT

cmd:    .byte "U1:2 0 ", 0
hash:   .byte "#"
