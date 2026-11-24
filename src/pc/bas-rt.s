; bas-rt.s - the compiler's native helpers for bas (src/pc/bas.c, docs/design/basic.md): the lexer,
; the line store and the scanner and code emitter. The number core and the control transfers
; the compiled code calls are in rt.s, included first (the runner has them too). Linked beside
; bas's p-code by mk/pvm.mk (src/pc/NAME-rt.s goes with src/pc/NAME.c).
.include "inc/rt.s"

.export c_crunch, c_find
.export c_sp, c_digit, c_letter, c_tok, c_ult, c_fail, c_emit, c_room, c_op1, c_opw, c_ncall, c_xop, c_xopw
.export xtab

; ---- the lexer and the line store (basic.md section 7: the compiler's hot helpers, native) ----

T_PRINT = 144                   ; bas.c's kwt: 128 + the place of PRINT and REM there
T_REM   = 145

; c_crunch(buf, kwt): normalise the line at buf (NUL-ended, under 256 bytes) in place, as
; bas.c's comment on it says. kwt is the keyword table: "NAME|NAME|...|", token 128 + place.
; Returns the new length, or -1 for a byte above 127 outside quotes.
c_crunch:
        lda P_ESTKL,x
        sta kbase
        lda P_ESTKH,x
        sta kbase+1
        lda P_ESTKL+1,x
        sta ptr
        lda P_ESTKH+1,x
        sta ptr+1
        inx
        stx sx
        lda #0
        sta li
        sta lo
        sta lq
@next:  ldy li
        lda (ptr),y
        beq @done
        iny
        sty li
        ldy lq
        bne @inq
        cmp #' '
        beq @sp
        cmp #9
        beq @sp
        cmp #128
        bcc :+
        jmp @bad
:       cmp #'?'
        bne :+
        lda #T_PRINT
        bne @put
:       jsr upper
        cmp #'A'
        bcc @plain
        cmp #'Z'+1
        bcs @plain
        jsr match
        bcc @plain0
        cmp #T_REM
        bne @put
        ldy #2
        sty lq
        bne @put
@plain0: ldy li                 ; no keyword: the letter itself
        dey
        lda (ptr),y
        jsr upper
@plain: cmp #'"'
        bne @put
        ldy #1
        sty lq
        bne @put
@inq:   cpy #1                  ; in a string, a quote ends it; in a REM nothing does
        bne @put
        cmp #'"'
        bne @put
        ldy #0
        sty lq
        beq @put
@sp:    ldy lo
        beq @next               ; none leading
        dey
        lda (ptr),y
        cmp #' '
        beq @next               ; one of a run
        lda #' '
@put:   ldy lo
        sta (ptr),y
        inc lo
        jmp @next
@done:  ldy lo
        lda lq
        bne @end                ; an unclosed string or a REM keeps its trailing spaces
@trim:  cpy #0
        beq @end
        dey
        lda (ptr),y
        cmp #' '
        beq @trim
        iny
@end:   lda #0
        sta (ptr),y
        tya
        ldx sx
        sta P_ESTKL,x
        lda #0
        sta P_ESTKH,x
        rts
@bad:   ldx sx
        lda #$FF
        sta P_ESTKL,x
        sta P_ESTKH,x
        rts

upper:  cmp #'a'
        bcc :+
        cmp #'z'+1
        bcs :+
        and #$DF
:       rts

; match: the first keyword in kbase's table that the text at li - 1 starts with (either case).
; Found: carry set, A the token, li past it. Else carry clear.
match:  lda kbase
        sta t0
        lda kbase+1
        sta t0+1
        lda #128
        sta ltok
@entry: ldy #0
        lda (t0),y
        beq @none               ; the table's end
        dec li                  ; li: the keyword's first byte, while comparing
@cmp:   lda (t0),y
        cmp #'|'
        beq @hit
        sta lc
        sty lj
        tya
        clc
        adc li
        tay
        lda (ptr),y
        jsr upper
        ldy lj
        iny
        cmp lc
        beq @cmp
        inc li
:       lda (t0),y              ; to the next entry
        iny
        cmp #'|'
        bne :-
        tya
        clc
        adc t0
        sta t0
        bcc :+
        inc t0+1
:       inc ltok
        bne @entry
@none:  clc
        rts
@hit:   tya
        clc
        adc li
        sta li
        lda ltok
        sec
        rts

; c_find(mem, top, n): the offset in mem of the first line numbered n or above (unsigned), or
; top. A line is its number (2 bytes), its length L, 2 bytes, the text and a 0: 6 + L bytes.
c_find: lda P_ESTKL,x
        sta lc
        lda P_ESTKH,x
        sta lj
        lda P_ESTKL+1,x
        sta kbase               ; top
        lda P_ESTKH+1,x
        sta kbase+1
        lda P_ESTKL+2,x
        sta ptr
        sta t0                  ; t0: mem, to make the offset
        lda P_ESTKH+2,x
        sta ptr+1
        sta t0+1
        inx
        inx
        stx sx
@line:  lda ptr                 ; at the top?
        sec
        sbc t0
        sta li
        lda ptr+1
        sbc t0+1
        cmp kbase+1
        bne :+
        lda li
        cmp kbase
:       bcs @at                 ; offset >= top
        ldy #1
        lda (ptr),y
        cmp lj
        bne :+
        dey
        lda (ptr),y
        cmp lc
:       bcs @at                 ; its number >= n
        ldy #2
        lda (ptr),y
        clc
        adc #6
        adc ptr
        sta ptr
        bcc @line
        inc ptr+1
        bne @line
@at:    lda ptr
        sec
        sbc t0
        ldx sx
        sta P_ESTKL,x
        lda ptr+1
        sbc t0+1
        sta P_ESTKH,x
        rts

; ---- the compiler's scanner and code emitter, on bas.c's globals (cc_pcode exports them) ----
; src[si] is the parse position (lines are under 256 bytes); mem[cend] the next code byte, below
; vbot; straight counts the bytes since Y was last reset (bas.c's room() comment).

.import g_src, g_si, g_mem, g_cend, g_vbot, g_straight, g_err

srcp:   lda g_src               ; ptr = src + si
        clc
        adc g_si
        sta ptr
        lda g_src+1
        adc g_si+1
        sta ptr+1
        ldy #0
        rts

; c_sp(): step over spaces at si; returns the byte there.
c_sp:   jsr srcp
:       lda (ptr),y
        cmp #' '
        bne :+
        iny
        bne :-
:       pha
        tya
        clc
        adc g_si
        sta g_si
        bcc :+
        inc g_si+1
:       pla
        ldy #0
        jmp pushay

; c_digit(), c_letter(): the byte at si is 0-9, A-Z (1 or 0).
c_digit: lda #'0'
        ldy #'9'+1
        bne range
c_letter: lda #'A'
        ldy #'Z'+1
range:  sta lc
        sty lj
        jsr srcp
        lda (ptr),y
        cmp lc
        bcc no
        cmp lj
        bcs no
        lda #1
        jmp pushay
no:     lda #0
        jmp pushay

; c_tok(t): the token t at si: step over it (1), or 0.
c_tok:  jsr srcp
        lda (ptr),y
        cmp P_ESTKL,x
        bne :+
        inc g_si
        bne :++
        inc g_si+1
        bne :++
:       lda #0
        .byte $2C               ; BIT abs: skip the LDA #1
:       lda #1
        sta P_ESTKL,x
        lda #0
        sta P_ESTKH,x
        rts

; c_fail(e): err = e, unless one came first. 0. seterr: the same for A.
c_fail: lda P_ESTKL,x
        inx                     ; void: the routine pops its own argument
        jmp seterr
seterr: sta t0                  ; (Y is the VM's IP offset when c_fail runs as an XOP: keep it)
        lda g_err
        ora g_err+1
        bne @r
        lda t0
        sta g_err
@r:     rts

; c_ult(a, b): a < b, unsigned (1 or 0).
c_ult:  ldy #0
        lda P_ESTKL+1,x
        cmp P_ESTKL,x
        lda P_ESTKH+1,x
        sbc P_ESTKH,x
        bcs :+
        iny
:       inx
        tya
        sta P_ESTKL,x
        lda #0
        sta P_ESTKH,x
        rts

; emitb: mem[cend++] = A, straight + 1; at vbot, err = OUT OF MEMORY (unless one came first)
; and nothing is written. X is kept.
emitb:  pha
        lda g_cend
        cmp g_vbot
        lda g_cend+1
        sbc g_vbot+1
        bcc :+
        pla
        lda g_err
        ora g_err+1
        bne @r
        lda #E_OOM
        sta g_err
@r:     rts
:       lda g_mem               ; mem is a pointer: c_grow sets it
        clc
        adc g_cend
        sta ptr
        lda g_mem+1
        adc g_cend+1
        sta ptr+1
        pla
        ldy #0
        sta (ptr),y
        inc g_cend
        bne :+
        inc g_cend+1
:       inc g_straight
        bne :+
        inc g_straight+1
:       rts

; roomb: before an instruction of A bytes: past 240 since Y was reset, a BRNCH to the next
; instruction (80, then the offset 2, relative to the offset word) resets it.
roomb:  ldy g_straight+1
        bne @br
        clc
        adc g_straight
        bcs @br
        cmp #241
        bcc @r
@br:    lda #80
        jsr emitb
        lda #2
        jsr emitb
        lda #0
        jsr emitb
        lda #0
        sta g_straight
        sta g_straight+1
@r:     rts

; c_emit(b), c_room(n), c_op1(b): as bas.c's comments on emit, room and op1. 0.
c_emit: lda P_ESTKL,x
        inx
        jmp emitb
c_room: lda P_ESTKL,x
        inx
        jmp roomb
c_op1:  lda #1
        jsr roomb
        lda P_ESTKL,x
        inx
        jmp emitb

; c_opw(b, w): an op with a word operand. c_ncall(f): NCAL f (82), after which the return has
; reset Y. 0.
c_opw:  lda #3
        jsr roomb
        lda P_ESTKL+1,x
        jsr emitb
        jsr word
        inx
        inx
        rts
c_ncall: lda #3
        jsr roomb
        lda #82
        jsr emitb
        jsr word
        jmp xstr
; c_xop(b): an XOP with no operand. c_xopw(b, w): one with a word operand. Like CALL, an XOP
; has the VM renormalise IP, so straight-line counting starts over. 0.
c_xop:  lda #1
        jsr roomb
        lda P_ESTKL,x
        jsr emitb
        jmp xstr
c_xopw: lda #3
        jsr roomb
        lda P_ESTKL+1,x
        jsr emitb
        jsr word
        inx
xstr:   inx
        lda #0
        sta g_straight
        sta g_straight+1
        rts
word:   lda P_ESTKL,x
        jsr emitb
        lda P_ESTKH,x
        jmp emitb

xtab:   .word x_ldv, x_stv, x_ldk, x_ln                 ; C8 CA CC CE
        .word n_add, n_sub, n_mul, n_div                 ; D0 D2 D4 D6
        .word n_neg, n_cmp, n_int, n_abs                 ; D8 DA DC DE
        .word n_sgn, n_fromi, n_toi, n_tst               ; E0 E2 E4 E6
        .word c_sp, c_tok, c_emit, c_op1                 ; E8 EA EC EE: the compiler's hot externs,
        .word c_ldv, c_digit, c_ncall, c_stv             ; F0 F2 F4 F6  called as one byte (bas.c's
        .word c_room, c_opw, c_fail, c_xop               ; F8 FA FC FE  /* xop N */ declarations)
