; du [path...]: bytes used under each path, one line per argument ("bytes path", as du -s).
; A directory's figure is the sum of every entry below it, its own size included; a file's
; figure is its size. No arguments: the current directory. Each open directory holds one fd, so
; the walk stops at MAXD levels (EMFILE, reported and skipped).
.include "../../include/breadbin.inc"
.import argn, perr, print, putc, newline
.importzp lp1
MAXD  = 8               ; directory levels the walk may open
PBMAX = 160             ; path buffer

.segment "CODE"
        lda #0
        sta npath
        lda #1
        sta idx
@l:     lda idx
        jsr argn
        bcs @end
        jsr one
        inc npath
        inc idx
        jmp @l
@end:   lda npath
        bne @r
        lda #<dot
        ldx #>dot
        jsr one
@r:     rts

; one: A/X = path argument. Copies it to pbuf, prints its figure and name.
one:    sta argp
        stx argp+1
        sta lp1
        stx lp1+1
        lda #0
        sta dep
        ldy #0
@c:     lda (lp1),y
        sta pbuf,y
        beq @cd
        iny
        cpy #PBMAX-15
        bcc @c
        lda #ENAMETOOLONG
        ldx argp
        ldy argp+1
        jmp perr
@cd:    lda #<pbuf
        sta r0
        lda #>pbuf
        sta r0+1
        lda #<st
        sta r1
        lda #>st
        sta r1+1
        jsr SYS_STAT
        bcc @ok
        ldx argp
        ldy argp+1
        jmp perr
@ok:    lda #0
        sta sm0
        sta sm1
        sta sm2
        sta sm3
        ldx #0
        jsr addsz
        lda st
        cmp #T_DIR
        bne @show
        jsr walk
@show:  ldx #0
        jsr prt
        lda #' '
        jsr putc
        lda argp
        ldx argp+1
        jsr print
        jmp newline

; walk: pbuf is a directory path at depth dep (its own size is already in sm[dep]).
; Adds the size of every entry below it into sm[dep]. Nothing here relies on ent or st
; surviving a recursive call: each entry is read, used, and then the next one is read.
walk:   ldy #0
@sl:    lda pbuf,y
        beq @sd
        iny
        bne @sl
@sd:    ldx dep
        tya
        sta plen,x
        lda #<pbuf
        sta r0
        lda #>pbuf
        sta r0+1
        lda #O_RDONLY
        jsr SYS_OPEN
        bcc @op
        ldx #<pbuf
        ldy #>pbuf
        jsr perr
        rts
@op:    ldx dep
        sta fdt,x
@rd:    lda #<ent
        sta r0
        lda #>ent
        sta r0+1
        lda #16
        sta r1
        lda #0
        sta r1+1
        ldx dep
        lda fdt,x
        jsr SYS_READ
        bcc @got
        jmp @close
@got:   lda r1
        cmp #16
        beq @full
        jmp @close
@full:  lda ent
        beq @rd                 ; free slot
        lda ent+1               ; skip "." and ".."
        cmp #'.'
        bne @child
        lda ent+2
        beq @rd
        cmp #'.'
        bne @child
        lda ent+3
        beq @rd
@child: ldx dep
        lda plen,x
        tay                     ; Y = length of the directory's path
        dey
        lda pbuf,y
        iny
        cmp #'/'
        beq @nos
        lda #'/'
        sta pbuf,y
        iny
@nos:   cpy #PBMAX-15
        bcc @cp
        lda #ENAMETOOLONG
        ldx #<(ent+1)
        ldy #>(ent+1)
        jsr perr
        jmp @rd
@cp:    ldx #0
@n:     lda ent+1,x
        sta pbuf,y
        beq @cd2
        iny
        inx
        bne @n
@cd2:   lda #<pbuf
        sta r0
        lda #>pbuf
        sta r0+1
        lda #<st
        sta r1
        lda #>st
        sta r1+1
        jsr SYS_STAT
        bcc @ok2
        ldx #<pbuf
        ldy #>pbuf
        jsr perr
        jmp @rd
@ok2:   ldx dep
        jsr addsz               ; sm[dep] += size of this entry
        lda st
        cmp #T_DIR
        beq @isdir
        jmp @rd
@isdir: ldx dep
        cpx #MAXD-1
        bcc @deep
        lda #EMFILE
        ldx #<pbuf
        ldy #>pbuf
        jsr perr
        jmp @rd
@deep:  inx                     ; the child's sum starts at zero
        lda #0
        sta sm0,x
        sta sm1,x
        sta sm2,x
        sta sm3,x
        inc dep
        jsr walk
        dec dep
        ldx dep                 ; sm[dep] += sm[dep+1]
        ldy dep
        iny
        jsr addsub
        jmp @rd
@close: ldx dep
        lda fdt,x
        jsr SYS_CLOSE
        rts

; addsz: sm[X] += size of the entry in st (3 bytes, st+2..st+4)
addsz:  clc
        lda st+2
        adc sm0,x
        sta sm0,x
        lda st+3
        adc sm1,x
        sta sm1,x
        lda st+4
        adc sm2,x
        sta sm2,x
        lda #0
        adc sm3,x
        sta sm3,x
        rts

; addsub: sm[X] += sm[Y]
addsub: clc
        lda sm0,y
        adc sm0,x
        sta sm0,x
        lda sm1,y
        adc sm1,x
        sta sm1,x
        lda sm2,y
        adc sm2,x
        sta sm2,x
        lda sm3,y
        adc sm3,x
        sta sm3,x
        rts

; prt: print sm[X] as an unsigned 32-bit decimal (no padding)
prt:    lda sm0,x
        sta tv
        lda sm1,x
        sta tv+1
        lda sm2,x
        sta tv+2
        lda sm3,x
        sta tv+3
        lda #0
        sta nd
@dg:    jsr div10
        ldy nd
        sta dig,y
        inc nd
        lda tv
        ora tv+1
        ora tv+2
        ora tv+3
        bne @dg
        ldx nd
@p:     dex
        lda dig,x
        ora #'0'
        stx ci
        jsr putc
        ldx ci
        bne @p
        rts

; div10: tv = tv / 10, A = remainder (0-9)
div10:  lda #0
        ldx #32
@b:     asl tv
        rol tv+1
        rol tv+2
        rol tv+3
        rol a
        cmp #10
        bcc @n
        sbc #10
        inc tv
@n:     dex
        bne @b
        rts

.segment "RODATA"
dot:    .byte ".", 0

.segment "BSS"
idx:    .res 1
npath:  .res 1
argp:   .res 2
dep:    .res 1
st:     .res 8
ent:    .res 16
pbuf:   .res PBMAX
fdt:    .res MAXD
plen:   .res MAXD
sm0:    .res MAXD
sm1:    .res MAXD
sm2:    .res MAXD
sm3:    .res MAXD
tv:     .res 4
nd:     .res 1
ci:     .res 1
dig:    .res 10
