; drvram: pattern test of a drive's RAM through M-W / M-R, from the C64, with the stock KERNAL's routines.
; Tests $0300-$06FF of the drive (its four channel buffers: free while no channel is open; the zero page,
; stack, $0200 variables and the BAM buffer at $0700 are left alone). Eight patterns per pass: $00, $FF, $55,
; $AA, $0F, $F0, the low byte of the index, and its complement. Also exercises M-W and M-R bus traffic.
; Variables (read by DMA): drive $C7E1 (set before SYS 49152), passes $C7E0 (0 = 256); done $C7F0, passes
; finished $C7F1/2, mismatching bytes $C7F3/4, first mismatch address $C7F5/6, expected $C7F7, got $C7F8.
; Assemble: ca65 drvram.s -o drvram.o && ld65 -t none -S 0xC000 -o drvram.bin drvram.o   (see drvram.py)
CHROUT = $FFD2
CHRIN  = $FFCF
OPEN   = $FFC0
SETLFS = $FFBA
SETNAM = $FFBD
CHKIN  = $FFC6
CHKOUT = $FFC9
CLRCHN = $FFCC

passes = $C7E0
drive  = $C7E1
done   = $C7F0
cnt    = $C7F1              ; 2 bytes
bad    = $C7F3              ; 2 bytes
bad_a  = $C7F5              ; 2 bytes
bad_e  = $C7F7
bad_g  = $C7F8
buf    = $C800              ; 1024 bytes, the pattern

pat    = $FB
chunk  = $FC
pg     = $FD
j      = $FE
got    = $F9
ptr    = $F7                ; 2 bytes
dlo    = $FA                ; the drive address of the byte being compared, low and high
dhi    = $F6

        .segment "CODE"
start:  lda #0
        sta done
        sta cnt
        sta cnt+1
        sta bad
        sta bad+1
        sta bad_a
        sta bad_a+1
        sta bad_e
        sta bad_g
        lda #15
        ldx drive
        ldy #15
        jsr SETLFS
        lda #0
        jsr SETNAM
        jsr OPEN
@pass:  lda #0
        sta pat
@pat:   jsr fill
        jsr write
        jsr readback
        inc pat
        lda pat
        cmp #8
        bcc @pat
        inc cnt
        bne @n
        inc cnt+1
@n:     lda cnt+1
        bne @pass           ; 256 or more passes: just keep going
        lda cnt
        cmp passes
        bne @pass
        lda #1
        sta done
        rts

; fill: buf = the current pattern, 1024 bytes
fill:   lda #<buf
        sta ptr
        lda #>buf
        sta ptr+1
        lda #4
        sta pg
@pg:    ldy #0
@by:    ldx pat
        cpx #6
        bcc @c
        beq @i
        tya                 ; pattern 7: the complement of the index
        eor #$ff
        jmp @st
@i:     tya                 ; pattern 6: the low byte of the index
        jmp @st
@c:     lda pconst,x
@st:    sta (ptr),y
        iny
        bne @by
        inc ptr+1
        dec pg
        bne @pg
        rts

; write: 32 commands "M-W lo hi 32 <32 bytes>" covering $0300-$06FF
write:  lda #0
        sta chunk
@ch:    ldx #15
        jsr CHKOUT
        lda #'M'
        jsr CHROUT
        lda #'-'
        jsr CHROUT
        lda #'W'
        jsr CHROUT
        lda chunk           ; drive address = $0300 + chunk * 32
        and #7
        asl a
        asl a
        asl a
        asl a
        asl a
        sta ptr             ; the same offset into buf (buf is page aligned)
        jsr CHROUT
        lda chunk
        lsr a
        lsr a
        lsr a
        pha
        clc
        adc #>buf
        sta ptr+1
        pla
        clc
        adc #3
        jsr CHROUT
        lda #32
        jsr CHROUT
        lda #0
        sta j
@d:     ldy j
        lda (ptr),y
        jsr CHROUT
        inc j
        lda j
        cmp #32
        bne @d
        jsr CLRCHN
        inc chunk
        lda chunk
        cmp #32
        bcc @ch
        rts

; readback: 8 commands "M-R lo hi 128", compare with buf
readback: lda #0
        sta chunk
@ch:    ldx #15
        jsr CHKOUT
        lda #'M'
        jsr CHROUT
        lda #'-'
        jsr CHROUT
        lda #'R'
        jsr CHROUT
        lda chunk           ; drive address = $0300 + chunk * 128
        and #1
        lsr a
        ror a               ; 0 or $80
        sta dlo
        sta ptr
        jsr CHROUT
        lda chunk
        lsr a
        pha
        clc
        adc #>buf
        sta ptr+1
        pla
        clc
        adc #3
        sta dhi
        jsr CHROUT
        lda #128
        jsr CHROUT
        jsr CLRCHN
        ldx #15
        jsr CHKIN
        lda #0
        sta j
@r:     jsr CHRIN
        sta got
        ldy j
        lda (ptr),y
        cmp got
        beq @ok
        inc bad
        bne @b
        inc bad+1
@b:     lda bad_a           ; remember the first mismatch only
        ora bad_a+1
        bne @ok
        lda dlo
        clc
        adc j
        sta bad_a
        lda dhi
        adc #0
        sta bad_a+1
        lda (ptr),y
        sta bad_e
        lda got
        sta bad_g
@ok:    inc j
        lda j
        cmp #128
        beq :+
        jmp @r
:
        jsr CLRCHN
        inc chunk
        lda chunk
        cmp #8
        bcs :+
        jmp @ch
:       rts

pconst: .byte $00, $FF, $55, $AA, $0F, $F0
