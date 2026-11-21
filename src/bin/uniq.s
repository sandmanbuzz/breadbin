; uniq [-c] [-d] [-u] [file]: collapse runs of equal adjacent lines into one.
; -c: prefix each line with its count; -d: print only the lines that repeat (one copy each);
; -u: print only the lines that do not repeat. Lines are up to 255 bytes.
.include "../../include/breadbin.inc"
.import argn, open_or_die, set_input, eprint, readline, print_dec_w, putc
.importzp lp1
.segment "CODE"
        lda #0
        sta cflag
        sta dflag
        sta uflag
        sta fname
        sta fname+1
        lda #1
        sta idx
@args:  lda idx
        cmp argc
        bcs @go
        jsr argn
        sta lp1
        stx lp1+1
        ldy #0
        lda (lp1),y
        cmp #'-'
        bne @file
        ldy #1
        lda (lp1),y
        beq @stdin              ; "-" is stdin
@ol:    lda (lp1),y
        beq @next
        cmp #'c'
        bne @n1
        lda #1
        sta cflag
        bne @oi
@n1:    cmp #'d'
        bne @n2
        lda #1
        sta dflag
        bne @oi
@n2:    cmp #'u'
        beq @isu
        jmp usage
@isu:   lda #1
        sta uflag
@oi:    iny
        bne @ol                 ; an option argument is under 256 bytes
@next:  inc idx
        jmp @args
@stdin: jmp @next
@file:  lda fname+1
        beq @setf
        jmp usage               ; one file at most
@setf:  lda lp1
        sta fname
        lda lp1+1
        sta fname+1
        jmp @next

@go:    lda fname+1
        bne @open
        lda #0
        jsr set_input
        jmp @run
@open:  lda fname
        ldx fname+1
        ldy #O_RDONLY
        jsr open_or_die
        jsr set_input
@run:   lda #0
        sta have
@rd:    lda #<cur
        ldx #>cur
        jsr readline
        bcs @end
        sta clen
        lda have
        beq @start
        lda clen
        cmp prevlen
        bne @diff
        ldx #0
@cmp:   cpx clen
        beq @same
        lda cur,x
        cmp prev,x
        bne @diff
        inx
        jmp @cmp
@same:  inc cnt
        bne @rd
        inc cnt+1
        jmp @rd
@diff:  jsr emit
@start: lda clen                ; this line starts the next run
        sta prevlen
        ldx #0
@cp:    cpx clen
        beq @cpd
        lda cur,x
        sta prev,x
        inx
        jmp @cp
@cpd:   lda #1
        sta have
        sta cnt
        lda #0
        sta cnt+1
        jmp @rd
@end:   lda have
        beq @done
        jsr emit
@done:  lda #0
        jmp SYS_EXIT

usage:  lda #0                  ; argv0: usage
        jsr argn
        jsr eprint
        lda #<s_usage
        ldx #>s_usage
        jsr eprint
        lda #1
        jmp SYS_EXIT

; emit: the run in prev (prevlen bytes, cnt copies) to stdout, if the flags let it through
emit:   lda cnt+1
        bne @multi
        lda cnt
        cmp #1
        bne @multi
        lda dflag               ; a line that does not repeat: -d drops it
        bne @skip
        jmp @out
@multi: lda uflag               ; a line that repeats: -u drops it
        bne @skip
@out:   lda cflag
        beq @line
        lda cnt
        ldx cnt+1
        ldy #7
        jsr print_dec_w
        lda #' '
        jsr putc
@line:  ldx prevlen
        lda #10
        sta prev,x              ; the newline goes after the line: 255 bytes plus it fit 256
        lda #<prev
        sta r0
        lda #>prev
        sta r0+1
        lda prevlen
        clc
        adc #1
        sta r1
        lda #0
        adc #0
        sta r1+1
        lda #1
        jsr SYS_WRITE
@skip:  rts

.segment "RODATA"
s_usage: .byte ": usage: uniq [-c] [-d] [-u] [file]", 10, 0

.segment "BSS"
cflag:   .res 1
dflag:   .res 1
uflag:   .res 1
idx:     .res 1
fname:   .res 2                 ; 0 = stdin
have:    .res 1                 ; prev holds a run
prevlen: .res 1
clen:    .res 1
cnt:     .res 2                 ; the run's length, 16 bits
cur:     .res 256               ; the line just read
prev:    .res 256               ; the run's line
