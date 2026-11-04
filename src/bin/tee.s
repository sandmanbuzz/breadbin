; Ported from upstream Breadbin (https://github.com/kpatr1981/breadbin, MIT; Copyright 2026 Konstantinos Patronas),
; commit 04f3a47 (feat: tee, tail and sort). Adapted: none; the program is taken as upstream wrote it.
; tee [-a] file...: copy stdin to stdout and into the files (-a appends)
; Gaps closed locally (2026-11-03): more than MAXF files is an error (nothing is copied); a write error is reported and exits 1.
.include "../../include/breadbin.inc"
.import argn, open_or_die, eprint
MAXF = 4
idx   = $23
n     = $24
flags = $25
p     = $26             ; 2
xs    = $28
fd    = $29
len   = $2a             ; 2
.segment "CODE"
        lda #(O_WRONLY | O_CREAT | O_TRUNC)
        sta flags
        lda #0
        sta n
        sta wst
        lda #1
        sta idx
        jsr argn
        bcs copy
        sta p
        stx p+1
        ldy #0
        lda (p),y
        cmp #'-'
        bne @chk
        iny
        lda (p),y
        cmp #'a'
        bne @chk
        iny                 ; the option is exactly "-a": "-ab" is a file name's flag, not -a
        lda (p),y
        bne @chk
        lda #(O_WRONLY | O_CREAT | O_APPEND)
        sta flags
        inc idx
@chk:   lda argc            ; more files than MAXF is an error, before anything is opened or truncated
        sec
        sbc idx
        cmp #MAXF+1
        bcs toomany
@files: lda idx
        jsr argn
        bcs copy
        ldy flags
        jsr open_or_die
        ldx n
        sta fds,x
        inc n
        inc idx
        jmp @files

toomany: lda #<msg_many
        ldx #>msg_many
        jsr eprint
        lda #1
        jmp SYS_EXIT

copy:   lda #<buf
        sta r0
        lda #>buf
        sta r0+1
        lda #0
        sta r1
        lda #1
        sta r1+1
        lda #0
        jsr SYS_READ
        bcs done
        lda r1
        sta len
        lda r1+1
        sta len+1
        ora len
        beq done
        lda #1
        jsr out
        bcs werr
        ldx #0
@f:     cpx n
        beq copy
        stx xs
        lda fds,x
        jsr out
        bcs werr
        ldx xs
        inx
        jmp @f
werr:   lda #<msg_write
        ldx #>msg_write
        jsr eprint
        lda #1
        sta wst
        jmp done
done:   ldx #0
@c:     cpx n
        beq @x
        stx xs
        lda fds,x
        jsr SYS_CLOSE
        ldx xs
        inx
        jmp @c
@x:     lda wst             ; 1 after a write error, else 0
        jmp SYS_EXIT

; out: A = fd; write the len bytes in buf
out:    sta fd
        lda #<buf
        sta r0
        lda #>buf
        sta r0+1
        lda len
        sta r1
        lda len+1
        sta r1+1
        lda fd
        jmp SYS_WRITE

.segment "RODATA"
msg_many:  .byte "tee: too many files", 10, 0
msg_write: .byte "tee: write error", 10, 0

.segment "BSS"
fds:    .res MAXF
wst:    .res 1
buf:    .res 256
