; cksum FILE: the POSIX cksum of FILE ("CRC LENGTH FILE", CRC-32 polynomial $04C11DB7,
; MSB first, initial 0, the length appended least significant byte first, complemented).
; Breadbin has no cksum command; session 5 arm R uses this one, built on the host with the
; release tree's library and run from a separate tools disk (experiments/iec-stall/session5.py).
.include "breadbin.inc"   ; ca65 -I TREE/include (the release tree's)
.import argn, open_or_die, print, putc, newline

crc   = $23     ; 4, most significant byte first
len   = $27     ; 3, least significant byte first
fd    = $2a
p     = $2b     ; 2
cnt   = $2d     ; 2

.segment "CODE"
        lda argc
        cmp #2
        beq @go
        lda #<usage
        ldx #>usage
        jsr print
        lda #2
        jmp SYS_EXIT
@go:    lda #0
        ldx #6
@z:     sta crc,x
        dex
        bpl @z
        lda #1
        jsr argn
        ldy #O_RDONLY
        jsr open_or_die
        sta fd
@rd:    lda #<buf
        sta r0
        lda #>buf
        sta r0+1
        lda #0
        sta r1
        lda #1
        sta r1+1
        lda fd
        jsr SYS_READ
        bcc @ok
        lda #<s_ioerr
        ldx #>s_ioerr
        jsr print
        lda #1
        jmp SYS_EXIT
@ok:    lda r1
        sta cnt
        lda r1+1
        sta cnt+1
        ora cnt
        beq @eof
        lda #<buf
        sta p
        lda #>buf
        sta p+1
@b:     ldy #0
        lda (p),y
        jsr crcb
        inc p
        bne :+
        inc p+1
:       inc len
        bne :+
        inc len+1
        bne :+
        inc len+2
:       lda cnt
        bne :+
        dec cnt+1
:       dec cnt
        lda cnt
        ora cnt+1
        bne @b
        jmp @rd
@eof:   lda fd
        jsr SYS_CLOSE
        ; the length, least significant byte first, while non-zero
        ldx #0
@l:     lda len,x
        sta tmp,x
        inx
        cpx #3
        bne @l
@lb:    lda tmp
        ora tmp+1
        ora tmp+2
        beq @fin
        lda tmp
        jsr crcb
        lda tmp+1
        sta tmp
        lda tmp+2
        sta tmp+1
        lda #0
        sta tmp+2
        jmp @lb
@fin:   ldx #3
@inv:   lda crc,x
        eor #$ff
        sta num,x           ; num: most significant byte first
        dex
        bpl @inv
        jsr pnum
        lda #' '
        jsr putc
        lda #0
        sta num
        lda len+2
        sta num+1
        lda len+1
        sta num+2
        lda len
        sta num+3
        jsr pnum
        lda #' '
        jsr putc
        lda #1
        jsr argn
        jsr print
        jsr newline
        lda #0
        jmp SYS_EXIT

; one byte (A) into the CRC
crcb:   eor crc
        sta crc
        ldx #8
@bit:   asl crc+3
        rol crc+2
        rol crc+1
        rol crc
        bcc @n
        lda crc
        eor #$04
        sta crc
        lda crc+1
        eor #$c1
        sta crc+1
        lda crc+2
        eor #$1d
        sta crc+2
        lda crc+3
        eor #$b7
        sta crc+3
@n:     dex
        bne @bit
        rts

; print num (4 bytes, most significant first) in decimal; destroys num
pnum:   ldy #0              ; digits pushed into dig, least significant first
@d:     lda #0              ; remainder
        ldx #32
@s:     asl num+3
        rol num+2
        rol num+1
        rol num
        rol a
        cmp #10
        bcc @k
        sbc #10
        inc num+3           ; the quotient bit (bit 0 is 0 after the shift)
@k:     dex
        bne @s
        sta dig,y
        iny
        lda num
        ora num+1
        ora num+2
        ora num+3
        bne @d
@o:     dey
        lda dig,y
        ora #'0'
        sty tmp
        jsr putc
        ldy tmp
        cpy #0
        bne @o
        rts

.segment "RODATA"
usage:  .byte "usage: cksum FILE", 10, 0
s_ioerr: .byte "cksum: read error", 10, 0

.segment "BSS"
tmp:    .res 3
num:    .res 4
dig:    .res 10
buf:    .res 256
