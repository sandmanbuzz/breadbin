; Breadbin user library, core: output, strings, arguments
.include "../../include/breadbin.inc"
.include "lib.inc"
.exportzp lp1, lp2, lp3, lval
.export exit, basename, strlen, fprint, print, eprint, write_buf, fputc, putc, eputc, newline, strcmp, argn

.segment "BSS"
lchar:  .res 1

.segment "CODE"
exit:   jmp SYS_EXIT

; basename: A/X = path -> A/X = part after the last '/'
basename:
        sta lp1
        stx lp1+1
        ldy #0
        sty lt0
@l:     lda (lp1),y
        beq @d
        iny
        cmp #'/'
        bne @l
        sty lt0
        jmp @l
@d:     lda lp1
        clc
        adc lt0
        ldx lp1+1
        bcc @r
        inx
@r:     rts

; strlen: A/X = string -> Y = A = length (max 255)
strlen:
        sta lp1
        stx lp1+1
        ldy #0
@l:     lda (lp1),y
        beq @d
        iny
        bne @l
        dey
@d:     tya
        rts

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

; write_buf: A = fd, r0/r1 set
write_buf:
        jmp SYS_WRITE

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

; strcmp: (lp1) vs (lp2) -> Z set if equal
strcmp:
        ldy #0
@l:     lda (lp1),y
        cmp (lp2),y
        bne @r
        cmp #0
        beq @r
        iny
        bne @l
@r:     rts

; argn: A = index -> A/X = argv[index]; carry set if index >= argc
argn:
        cmp argc
        bcs @r
        asl a
        tay
        lda (argv),y
        pha
        iny
        lda (argv),y
        tax
        pla
        clc
@r:     rts
