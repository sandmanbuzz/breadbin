; Breadbin user library: print a character
.include "../../include/breadbin.inc"
.include "lib.inc"
.export fputc, putc, eputc, newline

.segment "BSS"
lchar:  .res 1

.segment "CODE"
; fputc: A = char, Y = fd
fputc:  sta lchar
        sty lt0
        lda #<lchar
        sta r0
        lda #>lchar
        sta r0+1
        lda #1
        sta r1
        lda #0
        sta r1+1
        lda lt0
        jmp SYS_WRITE
putc:   ldy #1
        jmp fputc
eputc:  ldy #2
        jmp fputc
newline:
        lda #10
        jmp putc
