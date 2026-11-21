; cut -c LIST | -f LIST [-d C] [file]: print selected characters (-c) or fields (-f) of each line.
; LIST: N, N-M, N- or -M, comma separated, 1-based, 1..255. -d C: the field delimiter (default TAB).
; A field-mode line with no delimiter is printed whole. Lines are up to 255 bytes.
.include "../../include/breadbin.inc"
.import argn, open_or_die, set_input, eprint, putc, readline
.importzp lp1, lp2
.segment "CODE"
        lda #9
        sta delim
        lda #0
        sta mode
        sta fname
        sta fname+1
        lda #1
        sta idx
@args:  lda idx
        cmp argc
        bcc @more
        jmp @run
@more:  jsr argn
        sta lp1
        stx lp1+1
        ldy #0
        lda (lp1),y
        cmp #'-'
        beq @isopt
        jmp @file
@isopt: ldy #1
        lda (lp1),y
        bne @nostd
        jmp @next               ; "-" is stdin
@nostd: sta optc
        ldy #2
        lda (lp1),y
        beq @sepv
        jsr plus2               ; the value is attached: -cLIST
        jmp @opt
@sepv:  inc idx                 ; the value is the next argument: -c LIST
        lda idx
        cmp argc
        bcc @hasv
        jmp usage
@hasv:  jsr argn
@opt:   sta val
        stx val+1
        lda optc
        cmp #'c'
        bne @nc
        lda #1
        sta mode
        jmp @keep
@nc:    cmp #'f'
        bne @nf
        lda #2
        sta mode
        jmp @keep
@nf:    cmp #'d'
        beq @isd
        jmp usage
@isd:   lda val
        sta lp1
        lda val+1
        sta lp1+1
        ldy #0
        lda (lp1),y
        bne @dok
        jmp usage
@dok:   sta delim
        ldy #1
        lda (lp1),y
        beq @next               ; one character only
        jmp usage
@keep:  lda val
        sta lst
        lda val+1
        sta lst+1
@next:  inc idx
        jmp @args
@file:  lda fname+1
        beq @setf
        jmp usage               ; one file at most
@setf:  lda lp1
        sta fname
        lda lp1+1
        sta fname+1
        jmp @next
@run:   lda mode
        bne @havemode
        jmp usage
@havemode:
        lda lst
        sta lp1
        lda lst+1
        sta lp1+1
        jsr parse_list
        lda fname+1
        bne @open
        lda #0
        jsr set_input
        jmp @lines
@open:  lda fname
        ldx fname+1
        ldy #O_RDONLY
        jsr open_or_die
        jsr set_input
@lines: lda #<buf
        ldx #>buf
        jsr readline
        bcs @done
        sta n
        lda mode
        cmp #1
        bne @f
        jsr do_chars
        jmp @lines
@f:     jsr do_fields
        jmp @lines
@done:  lda #0
        jmp SYS_EXIT

usage:  lda #<s_usage
        ldx #>s_usage
        jmp fail
badlist: lda #<s_list
        ldx #>s_list
        jmp fail
; fail: A/X = the message; "NAME: message" on stderr, exit 1
fail:   sta lp2
        stx lp2+1
        lda #0
        jsr argn
        jsr eprint
        lda #<s_sep
        ldx #>s_sep
        jsr eprint
        lda lp2
        ldx lp2+1
        jsr eprint
        lda #1
        jmp SYS_EXIT

; plus2: A/X = lp1 + 2
plus2:  lda lp1
        clc
        adc #2
        ldx lp1+1
        bcc @r
        inx
@r:     rts

; nextp: lp1++
nextp:  inc lp1
        bne @r
        inc lp1+1
@r:     rts

; parse_list: lp1 = LIST -> the bits of the selected positions. Bad lists exit 1.
parse_list:
        ldx #31
        lda #0
@z:     sta bits,x
        dex
        bpl @z
@item:  lda #0
        sta nolo
        jsr getnum
        bcs @nolo
        lda nv
        sta lo
        sta hi
        jmp @more
@nolo:  lda #1
        sta nolo
        sta lo
        lda #255
        sta hi
        ldy #0
        lda (lp1),y
        cmp #'-'
        beq @more               ; an item needs a number or a dash
        jmp @bad
@more:  ldy #0
        lda (lp1),y
        cmp #'-'
        bne @check              ; a lone number: lo = hi
        jsr nextp
        jsr getnum
        bcs @open
        lda nv
        sta hi
        jmp @check
@open:  lda nolo
        beq @opened
        jmp @bad                ; a lone dash selects nothing
@opened: lda #255
        sta hi
@check: lda lo
        bne @lo1
        jmp @bad                ; positions start at 1
@lo1:   lda hi
        cmp lo
        bcs @range
        jmp @bad                ; reversed range
@range: lda lo
        sta k
@s:     lda k
        jsr setbit
        lda k
        cmp hi
        beq @sep
        inc k
        jmp @s
@sep:   ldy #0
        lda (lp1),y
        bne @notnul
        rts
@notnul: cmp #','
        beq @comma
        jmp @bad
@comma: jsr nextp
        jmp @item
@bad:   jmp badlist

; getnum: digits at lp1 -> nv, lp1 past them. Carry clear if there were digits, set if none.
; A value over 255 is a bad list.
getnum: lda #0
        sta nv
        sta ndig
@d:     ldy #0
        lda (lp1),y
        sec
        sbc #'0'
        cmp #10
        bcc @digit
        jmp @e
@digit: sta dg
        lda nv
        cmp #26
        bcc @small
        jmp @gbad
@small: asl a                   ; 2n
        sta tmp
        asl a
        asl a                   ; 8n (at most 200: no carry)
        adc tmp                 ; 10n (at most 250)
        adc dg
        bcc @fits
        jmp @gbad
@fits:  sta nv
        inc ndig
        jsr nextp
        jmp @d
@e:     lda ndig
        beq @none
        clc
        rts
@none:  sec
        rts
@gbad:  jmp badlist

; setbit: A = position (1..255) -> its bit in bits
setbit: pha
        lsr a
        lsr a
        lsr a
        tax
        pla
        and #7
        tay
        lda bitmask,y
        ora bits,x
        sta bits,x
        rts

; insel: A = position -> carry set if selected
insel:  pha
        lsr a
        lsr a
        lsr a
        tax
        pla
        and #7
        tay
        lda bitmask,y
        and bits,x
        beq @no
        sec
        rts
@no:    clc
        rts

; do_chars: buf[0..n-1] -> the selected characters, then a newline
do_chars:
        lda #0
        sta pos
@c:     lda pos
        cmp n
        beq @nl
        clc
        adc #1
        jsr insel
        bcc @skip
        ldx pos
        lda buf,x
        jsr putc
@skip:  inc pos
        jmp @c
@nl:    lda #10
        jmp putc

; do_fields: buf[0..n-1] -> the selected fields, joined with the delimiter, then a newline.
; A selected field after another one gets a delimiter before it, so a skipped field
; keeps its delimiter: "a,b,c" with -f 1,3 is "a,c".
do_fields:
        ldx #0
@scan:  cpx n
        beq @whole
        lda buf,x
        cmp delim
        beq @split
        inx
        jmp @scan
@whole: lda #0
        sta start
        lda n
        sta end
        jsr emit
        lda #10
        jmp putc
@split: lda #0
        sta start
        sta started
        sta fldhi
        lda #1
        sta fldlo
@f:     ldx start
@fe:    cpx n
        beq @fend
        lda buf,x
        cmp delim
        beq @fend
        inx
        jmp @fe
@fend:  stx end
        jsr fsel
        bcc @next
        lda started
        beq @first
        lda delim
        jsr putc
@first: lda #1
        sta started
        jsr emit
@next:  lda end
        cmp n
        beq @eol
        clc
        adc #1
        sta start
        inc fldlo
        bne @f
        inc fldhi
        jmp @f
@eol:   lda #10
        jmp putc

; fsel: fldhi/fldlo = field number -> carry set if selected (fields past 255 never are)
fsel:   lda fldhi
        bne @no
        lda fldlo
        jmp insel
@no:    clc
        rts

; emit: buf[start..end-1] to stdout
emit:   lda start
        sta pos
@e:     lda pos
        cmp end
        beq @d
        tax
        lda buf,x
        jsr putc
        inc pos
        jmp @e
@d:     rts

.segment "RODATA"
bitmask: .byte 1, 2, 4, 8, 16, 32, 64, 128
s_usage: .byte "usage: cut -c LIST | -f LIST [-d C] [file]", 10, 0
s_list:  .byte "bad list", 10, 0
s_sep:   .byte ": ", 0

.segment "BSS"
delim:   .res 1
mode:    .res 1                 ; 1 = -c, 2 = -f
optc:    .res 1
idx:     .res 1
fname:   .res 2                 ; 0 = stdin
val:     .res 2                 ; the value of the option being read
lst:     .res 2                 ; the LIST argument
bits:    .res 32                ; bit k set = position k is selected (k = 1..255)
nolo:    .res 1
lo:      .res 1
hi:      .res 1
k:       .res 1
nv:      .res 1
ndig:    .res 1
dg:      .res 1
tmp:     .res 1
buf:     .res 256               ; the line
n:       .res 1                 ; its length
pos:     .res 1
start:   .res 1
end:     .res 1
started: .res 1
fldlo:   .res 1                 ; field number, 16 bits
fldhi:   .res 1
