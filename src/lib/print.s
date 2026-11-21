; Breadbin user library: print a string
.include "../../include/breadbin.inc"
.include "lib.inc"
.import strlen
.export fprint, print, eprint

.segment "CODE"
; fprint: A/X = string, Y = fd
fprint:
        sty lt0
        sta r0
        stx r0+1
        jsr strlen
        sta r1
        lda #0
        sta r1+1
        lda lt0
        jmp SYS_WRITE
print:  ldy #1
        jmp fprint
eprint: ldy #2
        jmp fprint
