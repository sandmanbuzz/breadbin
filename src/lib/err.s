; Breadbin user library: error messages
.include "../../include/breadbin.inc"
.include "lib.inc"
.import eprint, eputc, argn
.export perr, errstr, open_or_die

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
@m:     lda lt3
        jsr errstr
        jsr eprint
        lda #10
        jmp eputc

; errstr: A = errno -> A/X = message
errstr:
        ldx #0
@l:     ldy errtab,x
        beq @unk
        cmp errtab,x
        beq @f
        inx
        inx
        inx
        bne @l
@f:     lda errtab+2,x
        pha
        lda errtab+1,x
        tay
        pla
        tax
        tya
        rts
@unk:   lda #<e_unk
        ldx #>e_unk
        rts

.segment "RODATA"
s_colon: .byte ": ", 0
errtab:
        .byte EPERM
        .word e_perm
        .byte ENOENT
        .word e_noent
        .byte ESRCH
        .word e_srch
        .byte EIO
        .word e_io
        .byte E2BIG
        .word e_2big
        .byte ENOEXEC
        .word e_noexec
        .byte EBADF
        .word e_badf
        .byte ECHILD
        .word e_child
        .byte EAGAIN
        .word e_again
        .byte ENOMEM
        .word e_nomem
        .byte EBUSY
        .word e_busy
        .byte EEXIST
        .word e_exist
        .byte ENODEV
        .word e_nodev
        .byte EXDEV
        .word e_xdev
        .byte ENOTDIR
        .word e_notdir
        .byte EISDIR
        .word e_isdir
        .byte EINVAL
        .word e_inval
        .byte EMFILE
        .word e_mfile
        .byte EFBIG
        .word e_fbig
        .byte ENOSPC
        .word e_nospc
        .byte EPIPE
        .word e_pipe
        .byte ENAMETOOLONG
        .word e_long
        .byte ENOTEMPTY
        .word e_notempty
        .byte 0
e_perm:   .byte "operation not permitted", 0
e_noent:  .byte "no such file or directory", 0
e_srch:   .byte "no such process", 0
e_io:     .byte "i/o error", 0
e_2big:   .byte "argument list too long", 0
e_noexec: .byte "exec format error", 0
e_badf:   .byte "bad file descriptor", 0
e_child:  .byte "no child processes", 0
e_again:  .byte "too many processes", 0
e_nomem:  .byte "out of memory", 0
e_exist:  .byte "file exists", 0
e_busy:   .byte "device busy", 0
e_nodev:  .byte "no such device or no disk", 0
e_xdev:   .byte "cross-device link", 0
e_notdir: .byte "not a directory", 0
e_isdir:  .byte "is a directory", 0
e_inval:  .byte "invalid argument", 0
e_mfile:  .byte "too many open files", 0
e_fbig:   .byte "file too large", 0
e_nospc:  .byte "no space left on device", 0
e_pipe:   .byte "broken pipe", 0
e_long:   .byte "file name too long", 0
e_notempty: .byte "directory not empty", 0
e_unk:    .byte "error", 0
