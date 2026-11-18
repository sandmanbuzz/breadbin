; drvdump: snapshot the drive's whole RAM ($0000-$07FF) with M-R, from the C64, stock KERNAL.
; Read-only on the drive. Two snapshots: idle (only the command channel open), then after
; OPEN 2,dev,2,"#" (what Breadbin's block layer does), then a third after "U1:2 0 18 0" has
; filled that channel's buffer (shows which drive page it is), then the drive ROM $C000-$FFFF.
; Results by DMA: $4000-$47FF idle, $4800-$4FFF with #, $5000-$57FF after U1, $5800-$97FF ROM;
; done flag $C7F0 (1 = finished), drive number in $C7E1.
; Assemble: ca65 drvdump.s -o drvdump.o && ld65 -t none -S 0xC000 -o drvdump.bin drvdump.o
CHROUT = $FFD2
CHRIN  = $FFCF
OPEN   = $FFC0
SETLFS = $FFBA
SETNAM = $FFBD
CHKIN  = $FFC6
CHKOUT = $FFC9
CLRCHN = $FFCC
drive  = $C7E1
done   = $C7F0
ptr    = $F7
chunk  = $FC
dstart = $FB
nch    = $FA
        .segment "CODE"
        lda #0
        sta done
        lda #15
        ldx drive
        ldy #15
        jsr SETLFS
        lda #0
        jsr SETNAM
        jsr OPEN
        lda #$40
        jsr dump
        lda #2
        ldx drive
        ldy #2
        jsr SETLFS
        lda #1
        ldx #<hash
        ldy #>hash
        jsr SETNAM
        jsr OPEN
        lda #$48
        jsr dump
        ldx #15
        jsr CHKOUT
        ldy #0
@u:     lda u1,y
        jsr CHROUT
        iny
        cpy #u1len
        bne @u
        jsr CLRCHN
        ldx #15
        jsr CHKIN
@s:     jsr CHRIN               ; the status line, up to CR: the command has finished
        cmp #13
        bne @s
        jsr CLRCHN
        lda #$50
        jsr dump
        lda #$58
        sta ptr+1
        lda #0
        sta ptr
        lda #$C0
        sta dstart
        lda #128
        sta nch
        jsr dumpn
        lda #1
        sta done
        rts
hash:   .byte "#"
u1:     .byte "U1:2 0 18 0"
u1len = * - u1
; dump: A = high byte of the destination; 16 commands M-R lo hi 128
dump:   sta ptr+1
        lda #0
        sta ptr
        sta dstart
        lda #16
        sta nch
dumpn:  lda #0
        sta chunk
@ch:    ldx #15
        jsr CHKOUT
        lda #'M'
        jsr CHROUT
        lda #'-'
        jsr CHROUT
        lda #'R'
        jsr CHROUT
        lda chunk
        lsr a
        lda #0
        ror a
        jsr CHROUT
        lda chunk
        lsr a
        clc
        adc dstart
        jsr CHROUT
        lda #128
        jsr CHROUT
        jsr CLRCHN
        ldx #15
        jsr CHKIN
        ldy #0
@r:     jsr CHRIN
        sta (ptr),y
        iny
        cpy #128
        bne @r
        jsr CLRCHN
        lda ptr
        clc
        adc #128
        sta ptr
        bcc @n
        inc ptr+1
@n:     inc chunk
        lda chunk
        cmp nch
        bcc @ch
        rts
