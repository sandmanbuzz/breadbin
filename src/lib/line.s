; Breadbin user library: readline, one line of the current input (set_input) into a buffer
.include "../../include/breadbin.inc"
.include "lib.inc"
.import getc, eprint, argn
.export readline

.segment "BSS"
ln_len: .res 1

.segment "CODE"
; readline: A/X = a 256-byte buffer -> A = length of the line, carry clear. The newline is not
; stored. Carry set at the end of the input. A line of more than 255 bytes is an error:
; "NAME: line too long" on stderr and exit 1.
readline:
        sta lp1
        stx lp1+1
        lda #0
        sta ln_len
@c:     jsr getc
        bcs @eof
        cmp #10
        beq @end
        ldy ln_len
        cpy #255
        beq @long
        sta (lp1),y
        inc ln_len
        jmp @c
@end:   lda ln_len
        clc
        rts
@eof:   lda ln_len
        bne @end            ; the last line had no newline
        sec
        rts
@long:  lda #0
        jsr argn
        jsr eprint
        lda #<s_long
        ldx #>s_long
        jsr eprint
        lda #1
        jmp SYS_EXIT

s_long: .byte ": line too long", 10, 0
