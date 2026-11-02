; Breadbin user library: error messages
.include "../../include/breadbin.inc"
.include "lib.inc"
.import eprint, eputc, argn
.export perr, open_or_die

.segment "CODE"
; open_or_die: A/X = path, Y = flags -> A = fd; on error prints and exits 1
open_or_die:
        sta lp3
        stx lp3+1
        sta r0
        stx r0+1
        tya
        jsr SYS_OPEN
        bcc @r
        ldx lp3
        ldy lp3+1
        jsr perr
        lda #1
        jmp SYS_EXIT
@r:     rts

; perr: A = errno, X/Y = extra string or 0/0.
; prints "argv0: [extra: ]message" to stderr
perr:
        sta lt3
        stx lp3
        sty lp3+1
        lda #0
        jsr argn
        jsr eprint
        lda #<s_colon
        ldx #>s_colon
        jsr eprint
        lda lp3
        ora lp3+1
        beq @m
        lda lp3
        ldx lp3+1
        jsr eprint
        lda #<s_colon
        ldx #>s_colon
        jsr eprint
@m:     jsr errmsg
        lda #10
        jmp eputc

; errmsg: lt3 = errno -> its message on stderr (no newline).
; The commonest three are built in, so they print even when the disk cannot be read (and
; ENOENT costs no block read). The rest are looked up in /etc/errors, lines "NN text", streamed
; a byte at a time: no buffer, and nothing here may call perr. Not found or unreadable: "error N".
errmsg:
        ldx #0
@b:     lda btab,x
        beq @file
        cmp lt3
        beq @bi
        inx
        inx
        inx
        bne @b
@bi:    lda btab+1,x
        pha
        lda btab+2,x
        tax
        pla
        jmp eprint
@file:  lda #<s_file
        sta r0
        lda #>s_file
        sta r0+1
        lda #O_RDONLY
        jsr SYS_OPEN
        bcs @fall
        sta lt2
@line:  lda #0
        sta lt1
@num:   jsr rdb
        bcs @nf
        cmp #' '
        beq @have
        cmp #10
        beq @line               ; an empty line
        sec
        sbc #'0'
        cmp #10
        bcs @skip               ; not a number: ignore the line
        sta lt0
        lda lt1
        asl a
        asl a
        adc lt1                 ; x5 (no carry: lt1 < 26)
        asl a                   ; x10
        adc lt0
        sta lt1
        jmp @num
@have:  lda lt1
        cmp lt3
        beq @show
@skip:  jsr rdb
        bcs @nf
        cmp #10
        bne @skip
        beq @line
@show:  jsr rdb
        bcs @done
        cmp #10
        beq @done
        jsr eputc
        jmp @show
@done:  jsr cls
        rts
@nf:    jsr cls
@fall:  lda #<s_err
        ldx #>s_err
        jsr eprint
        lda lt3                 ; errno as decimal (below 100)
        ldx #'0'
@t:     cmp #10
        bcc @u
        sbc #10
        inx
        bne @t
@u:     pha
        txa
        cmp #'0'
        beq @o
        jsr eputc
@o:     pla
        clc
        adc #'0'
        jmp eputc

; rdb: next byte of the file (lt2) -> A; carry set at the end or on an error
rdb:    lda #<lval
        sta r0
        lda #0
        sta r0+1
        lda #1
        sta r1
        lda #0
        sta r1+1
        lda lt2
        jsr SYS_READ
        bcs @e
        lda r1
        beq @e
        lda lval
        clc
        rts
@e:     sec
        rts

cls:    lda lt2
        jmp SYS_CLOSE

.segment "RODATA"
s_colon: .byte ": ", 0
s_file:  .byte "/etc/errors", 0
s_err:   .byte "error ", 0
btab:   .byte EIO
        .word e_io
        .byte ENOENT
        .word e_noent
        .byte ENODEV
        .word e_nodev
        .byte 0
e_io:    .byte "i/o error", 0
e_noent: .byte "no such file or directory", 0
e_nodev: .byte "no such device or no disk", 0
