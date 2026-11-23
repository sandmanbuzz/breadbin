; bas-rt.s - native helpers for bas (src/pc/bas.c, docs/design/basic.md): the fixed-point number
; core and the control transfers the VM has no opcode for. Linked beside bas's p-code by
; mk/pvm.mk (src/pc/NAME-rt.s goes with src/pc/NAME.c).
;
; Numbers (basic.md section 3): a 32-bit signed binary integer scaled by 10,000, little endian,
; -2147483647 to 2147483647 (so -214748.3647 to 214748.3647; -2^31 is an overflow, so negation
; never overflows). They live on a number stack of their own (nstk, NDEPTH entries); the
; compiler bounds an expression's depth, and a push past the end throws OUT OF MEMORY. Products
; and quotients are rounded half away from zero to 4 places.
;
; Two calling conventions. The n_ routines are CALLed by compiled BASIC: they pop their
; arguments from the eval stack and push a result only where noted (the compiler knows which).
; The c_ routines are the same for the mini C (`extern int c_add();`): each pushes one result,
; as cc.py --pcode's extern contract requires.
;
; Control (pvm.md section 4 item 2, "native callees"): a native routine reached by CALL or ICAL
; finds, above its own return address, the IP the VM resumes at when it returns: low byte at
; $0103 + S, high at $0104 + S. rt_go and rt_throw jump by rewriting it.
.include "pvm.inc"
.include "breadbin.inc"

.export n_ldv, n_ldk, n_stv, n_dup, n_add, n_sub, n_mul, n_div, n_neg, n_abs, n_int, n_sgn
.export n_fromi, n_toi, n_cmp, n_tst
.export rt_mark, rt_go, rt_ln, xtab
.export c_ldv, c_stv, c_dup, c_add, c_sub, c_mul, c_div, c_int, c_fromi, c_toi, c_cmp, c_const, c_fmt
.export c_grow, c_throw, c_err, c_curip, c_crunch, c_find
.export c_sp, c_digit, c_letter, c_tok, c_ult, c_fail, c_emit, c_room, c_op1, c_opw, c_ncall, c_xop, c_xopw

NDEPTH  = 16
ESTKSZ  = P_ESTKL - P_ESTKH + 11 ; both halves, contiguous
E_OOM   = 2                     ; error numbers: bas.c's report() has the messages
E_OVF   = 4
E_DIV0  = 5
E_ILQ   = 6

.segment "ZEROPAGE"
ptr:    .res 2
sx:     .res 1                  ; the eval stack index, kept across the routines
t0:     .res 2

.segment "BSS"
nstk:   .res NDEPTH * 4
nsp:    .res 1                  ; bytes in use
acc:    .res 8                  ; the accumulator: 64 bits for products and dividends
opb:    .res 4                  ; the other operand, the multiplier or divisor
rem:    .res 5                  ; the remainder (one bit more than the divisor)
tq:     .res 4
dvs:    .res 4                  ; n_div's divisor while the dividend is scaled
sgn:    .res 1                  ; bit 7: the result is negative
ms:     .res 1                  ; rt_mark: S, X, IFP, the resume IP and the return address
mx:     .res 1
mifp:   .res 2
mip:    .res 2
mret:   .res 2
estk:   .res ESTKSZ
err:    .res 1
curip:  .res 2
fx:     .res 5                  ; c_fmt: the fraction, then the whole part
fbuf:   .res 12                 ; c_fmt's text: sign, 6 digits, point, 4 digits
fend:
kbase:  .res 2                  ; c_crunch and c_find
li:     .res 1
lo:     .res 1
lq:     .res 1
lj:     .res 1
lc:     .res 1
ltok:   .res 1

.segment "CODE"

; ---- control ----

; rt_mark: the compiled code's first op. Records where rt_throw lands: the op after this CALL,
; with S, X and IFP as now and the number stack empty. Pushes 0; rt_throw makes it push 1.
rt_mark:
        dex
        lda #0
        sta P_ESTKL,x
        sta P_ESTKH,x
        sta nsp
        sta err
        stx mx
        tsx
        stx ms
        lda $0101,x
        sta mret
        lda $0102,x
        sta mret+1
        lda $0103,x
        sta mip
        lda $0104,x
        sta mip+1
        lda P_IFP
        sta mifp
        lda P_IFP+1
        sta mifp+1
        ldx #ESTKSZ - 1         ; the whole eval stack: a function called after this may
:       lda P_ESTKH,x           ; spill the entries under X into its frame and reuse them
        sta estk,x
        dex
        bpl :-
        ldx mx
        rts

; throw: error A. Back to rt_mark's caller, which sees 1; the frame stack, the 6502 stack and
; the eval stack as they were there.
throw:  sta err
        ldx ms
        txs
        lda mret
        sta $0101,x
        lda mret+1
        sta $0102,x
        lda mip
        sta $0103,x
        lda mip+1
        sta $0104,x
        lda mifp
        sta P_IFP
        lda mifp+1
        sta P_IFP+1
        ldx #ESTKSZ - 1
:       lda estk,x
        sta P_ESTKH,x
        dex
        bpl :-
        ldx mx
        lda #1
        sta P_ESTKL,x
        rts

; rt_go: pop an address; if it is not 0, continue there (absolute, as JUMP).
rt_go:  lda P_ESTKL,x
        sta t0
        lda P_ESTKH,x
        sta t0+1
        inx
        ora t0
        beq @r
        stx sx
        tsx
        lda t0
        sta $0103,x
        lda t0+1
        sta $0104,x
        ldx sx
@r:     rts

; rt_ln: at the start of each line: remember where (bas maps it back to a line number).
rt_ln:  stx sx
        tsx
        lda $0103,x
        sta curip
        lda $0104,x
        sta curip+1
        ldx sx
        rts

; ---- the number stack ----

pusha:  ldy nsp
        cpy #NDEPTH * 4
        bcc :+
        lda #E_OOM
        jmp throw
:       lda acc
        sta nstk,y
        lda acc+1
        sta nstk+1,y
        lda acc+2
        sta nstk+2,y
        lda acc+3
        sta nstk+3,y
        tya
        clc
        adc #4
        sta nsp
        rts

popa:   jsr popy
        lda nstk,y
        sta acc
        lda nstk+1,y
        sta acc+1
        lda nstk+2,y
        sta acc+2
        lda nstk+3,y
        sta acc+3
clrhi:  lda #0
        sta acc+4
        sta acc+5
        sta acc+6
        sta acc+7
        rts

popb:   jsr popy
        lda nstk,y
        sta opb
        lda nstk+1,y
        sta opb+1
        lda nstk+2,y
        sta opb+2
        lda nstk+3,y
        sta opb+3
        rts

popy:   lda nsp
        sec
        sbc #4
        sta nsp
        tay
        rts

; ---- arithmetic on acc and opb ----

nega:   ldy #$FC                ; acc = -acc (32 bits)
        sec
:       lda #0
        sbc acc - $FC,y
        sta acc - $FC,y
        iny
        bne :-
        rts

absa:   lda acc+3               ; acc = |acc|, sgn ^= its sign
        bpl :+
        lda sgn
        eor #$80
        sta sgn
        jmp nega
:       rts

absb:   lda opb+3               ; opb = |opb|, sgn ^= its sign
        bpl :++
        lda sgn
        eor #$80
        sta sgn
        ldy #$FC
        sec
:       lda #0
        sbc opb - $FC,y
        sta opb - $FC,y
        iny
        bne :-
:       rts

; umul: acc[0-3] * opb -> acc (64 bits), unsigned
umul:   jsr clrhi
        ldx #32
@l:     lda acc
        lsr a
        bcc @n
        ldy #$FC                ; acc[4-7] += opb; the carry out goes in at the top
        clc
:       lda acc + 4 - $FC,y
        adc opb - $FC,y
        sta acc + 4 - $FC,y
        iny
        bne :-
@n:     ror acc+7
        ror acc+6
        ror acc+5
        ror acc+4
        ror acc+3
        ror acc+2
        ror acc+1
        ror acc
        dex
        bne @l
        rts

; udiv: acc / opb -> quotient in acc, remainder in rem, unsigned. udiv32 takes a 32-bit
; dividend (acc[0-3]) and udiv48 a 48-bit one (acc[0-5]): they move it to the top of acc and
; run 32 or 48 steps instead of 64.
udiv32: ldy #3
:       lda acc,y
        sta acc+4,y
        lda #0
        sta acc,y
        dey
        bpl :-
        ldx #32
        bne udiv
udiv48: ldy #5
:       lda acc,y
        sta acc+2,y
        dey
        bpl :-
        lda #0
        sta acc
        sta acc+1
        ldx #48
udiv:   lda #0
        ldy #4
:       sta rem,y
        dey
        bpl :-
@l:     asl acc
        rol acc+1
        rol acc+2
        rol acc+3
        rol acc+4
        rol acc+5
        rol acc+6
        rol acc+7
        rol rem
        rol rem+1
        rol rem+2
        rol rem+3
        rol rem+4
        ldy #$FC                ; tq = rem - opb, the borrow into rem[4]
        sec
:       lda rem - $FC,y
        sbc opb - $FC,y
        sta tq - $FC,y
        iny
        bne :-
        lda rem+4
        sbc #0
        bcc @n
        sta rem+4
        ldy #3
:       lda tq,y
        sta rem,y
        dey
        bpl :-
        inc acc                 ; the quotient bit (bit 0 is 0 after the shift)
@n:     dex
        bne @l
        rts

setb:   sta opb                 ; opb = A | Y << 8
        sty opb+1
        lda #0
        sta opb+2
        sta opb+3
        rts

tenk:   lda #<10000
        ldy #>10000
        bne setb

; fin: acc is a magnitude (64 bits) and sgn its sign: push it, or OVERFLOW past 2^31 - 1.
fin:    lda acc+4
        ora acc+5
        ora acc+6
        ora acc+7
        bne ovf
        lda acc+3
        bmi ovf
        bit sgn
        bpl :+
        jsr nega
:       jsr pusha
        ldx sx
        rts
ovf:    lda #E_OVF
        jmp throw

; scale48: acc (a 64-bit magnitude) must fit 48 bits for udiv48; past them the quotient by
; 10,000 or more would overflow anyway
scale48: lda acc+6
        ora acc+7
        bne ovf
        rts

; addb: acc (64 bits) += opb (32 bits)
addb:   ldy #$FC
        clc
:       lda acc - $FC,y
        adc opb - $FC,y
        sta acc - $FC,y
        iny
        bne :-
        bcc @r
        ldy #4
:       lda acc,y
        adc #0                  ; carry is set: adds 1
        sta acc,y
        bcc @r
        iny
        cpy #8                  ; cpy clobbers carry: set it again for the next byte
        bcs @r
        sec
        bcs :-
@r:     rts

; ---- the n_ routines ----

n_ldk:  lda P_ESTKL,x           ; a CS constant: its 4 bytes follow the length byte
        clc
        adc #1
        sta ptr
        lda P_ESTKH,x
        adc #0
        sta ptr+1
        jmp ldv2
n_ldv:  lda P_ESTKL,x           ; push the number at an address
        sta ptr
        lda P_ESTKH,x
        sta ptr+1
ldv2:   inx
ldv3:   stx sx
        ldy #3
:       lda (ptr),y
        sta acc,y
        dey
        bpl :-
push:   jsr pusha
        ldx sx
        rts

n_stv:  lda P_ESTKL,x           ; pop the number to an address
        sta ptr
        lda P_ESTKH,x
        sta ptr+1
        inx
        stx sx
stv2:   jsr popa
        ldy #3
:       lda acc,y
        sta (ptr),y
        dey
        bpl :-
        ldx sx
        rts

n_dup:  stx sx
        jsr popa
        jsr pusha
        jmp push

n_add:  stx sx
        jsr popb
        jsr popa
        ldy #$FC
        clc
:       lda acc - $FC,y
        adc opb - $FC,y
        sta acc - $FC,y
        iny
        bne :-
        bvc :+
        jmp ovf
:
        jmp signed
n_sub:  stx sx
        jsr popb
        jsr popa
        ldy #$FC
        sec
:       lda acc - $FC,y
        sbc opb - $FC,y
        sta acc - $FC,y
        iny
        bne :-
        bvc :+
        jmp ovf
:
signed: lda acc+3               ; a signed 32-bit result: -2^31 is an overflow
        cmp #$80
        bne push
        lda acc
        ora acc+1
        ora acc+2
        bne :+
        jmp ovf
:
        bne push

n_neg:  stx sx
        jsr popa
        jsr nega
        jmp push

n_abs:  stx sx
        jsr popa
        lda acc+3
        bmi :+
        jmp push
:
        jsr nega
        jmp push

n_sgn:  stx sx                  ; -1, 0 or 1
        jsr popa
        lda acc+3
        bmi @neg
        ora acc+2
        ora acc+1
        ora acc
        bne :+
        jmp push
:
        lda #0
        sta sgn
        beq one
@neg:   lda #$80
        sta sgn
one:    lda #<10000
        sta acc
        lda #>10000
        sta acc+1
        lda #0
        sta acc+2
        sta acc+3
        jmp fin

n_fromi: lda P_ESTKL,x          ; pop an int, push it as a number
        sta acc
        lda P_ESTKH,x
        sta acc+1
        inx
        stx sx
        ldy #0
        asl a                   ; sign-extend
        bcc :+
        dey
:       sty acc+2
        sty acc+3
        lda #0
        sta sgn
        jsr absa
        jsr tenk
        jsr umul
        jmp fin

; whole: acc = the integer part of the popped number's magnitude, sgn its sign, rem the fraction
whole:  jsr popa
        lda #0
        sta sgn
        jsr absa
        jsr tenk
        jmp udiv32

n_toi:  stx sx                  ; pop a number, push it as an int (toward zero); past
        jsr whole               ; -32768 to 32767, ILLEGAL QUANTITY
        lda acc+2
        ora acc+3
        bne ilq
        bit sgn
        bmi @neg
        lda acc+1
        bmi ilq
        bpl pushi
@neg:   lda acc+1               ; up to 32768
        cmp #$80
        bcc :+
        bne ilq
        lda acc
        bne ilq
:       jsr nega
pushi:  ldx sx
        dex
        lda acc
        sta P_ESTKL,x
        lda acc+1
        sta P_ESTKH,x
        rts
ilq:    lda #E_ILQ
        jmp throw

n_int:  stx sx                  ; the largest whole number not above it
        jsr whole
        bit sgn
        bpl :+
        lda rem                 ; negative with a fraction: one further from 0
        ora rem+1
        beq :+
        inc acc
        bne :+
        inc acc+1
        bne :+
        inc acc+2
:       jsr tenk
        jsr umul
        jmp fin

n_mul:  stx sx
        jsr popb
        jsr popa
        lda #0
        sta sgn
        jsr absa
        jsr absb
        jsr umul
        lda #<5000              ; round half away from zero
        ldy #>5000
        jsr setb
        jsr addb
        jsr scale48
        jsr tenk
        jsr udiv48
        jmp fin

n_div:  stx sx
        jsr popb
        jsr popa
        lda opb
        ora opb+1
        ora opb+2
        ora opb+3
        bne :+
        lda #E_DIV0
        jmp throw
:       lda #0
        sta sgn
        jsr absa
        jsr absb
        ldy #3
:       lda opb,y
        sta dvs,y
        dey
        bpl :-
        jsr tenk                ; the dividend times 10,000 (under 2^45)
        jsr umul
        lda dvs+3               ; plus half the divisor, to round
        lsr a
        sta opb+3
        lda dvs+2
        ror a
        sta opb+2
        lda dvs+1
        ror a
        sta opb+1
        lda dvs
        ror a
        sta opb
        jsr addb
        ldy #3
:       lda dvs,y
        sta opb,y
        dey
        bpl :-
        jsr udiv48
        jmp fin

n_cmp:  stx sx                  ; pop b, then a: push the int -1, 0 or 1 (a against b)
        jsr popb
        jsr popa
        ldy #$FC
        sec
:       lda acc - $FC,y
        sbc opb - $FC,y
        sta acc - $FC,y
        iny
        bne :-
        bvc @nv
        eor #$80                ; the sign of the true difference (which is not 0)
        bmi @lt
        bpl @gt
@nv:    ora #0
        bmi @lt
        ora acc
        ora acc+1
        ora acc+2
        beq @eq
@gt:    lda #1
        ldy #0
        beq @r
@lt:    lda #$FF
        tay
        bne @r
@eq:    lda #0
        tay
@r:     ldx sx
        jmp pushay

n_tst:  stx sx                  ; pop a number: push the int -1 if it is not 0, else 0
        jsr popa
        lda acc
        ora acc+1
        ora acc+2
        ora acc+3
        beq :+
        lda #$FF
:       ldx sx
        dex
        sta P_ESTKL,x
        sta P_ESTKH,x
        rts

; ---- the c_ routines, for the mini C: one result each ----

push0:  dex
        lda #0
        sta P_ESTKL,x
        sta P_ESTKH,x
        rts
c_ldv:  jsr n_ldv
        jmp push0
c_stv:  jsr n_stv
        jmp push0
c_dup:  jsr n_dup
        jmp push0
c_add:  jsr n_add
        jmp push0
c_sub:  jsr n_sub
        jmp push0
c_mul:  jsr n_mul
        jmp push0
c_div:  jsr n_div
        jmp push0
c_int:  jsr n_int
        jmp push0
c_fromi: jsr n_fromi
        jmp push0
c_toi   = n_toi
c_cmp   = n_cmp

c_throw: lda P_ESTKL,x          ; error n: never returns
        jmp throw

c_err:  lda err
        ldy #0
        beq pushay
c_curip: lda curip
        ldy curip+1
pushay: dex
        sta P_ESTKL,x
        tya
        sta P_ESTKH,x
        rts

; c_const(buf): read a number at si: digits, a point, digits (spaces among them stepped over, as MS);
; its 4 bytes (units of 1/10000, rounded past 4 decimals) go to buf. Returns the value when it is a whole
; number under 32768, else -2. FAIL 1 for no digits, 4 for a number past 2^31 - 1.
; State, all in the lexer's bytes: li digits seen, lo the decimals seen (-1 in the whole part), lc
; nonzero decimals, lj the 4th decimal + the rounding, lq overflow, tq the whole part (tq+2: past 32767).
c_const: lda P_ESTKL,x
        sta dvs
        lda P_ESTKH,x
        sta dvs+1
        stx sx
        lda #0
        ldy #7
:       sta acc,y
        dey
        bpl :-
        sta li
        sta lc
        sta lq
        sta lj
        sta nsp                 ; and the number stack is empty (a run that failed can leave it full)
        lda #$FF
        sta lo
@loop:  jsr srcp
        lda (ptr),y
        sec
        sbc #'0'
        cmp #10
        bcs @nd
        sta t0
        ldy lo
        bmi @mac                ; a whole-part digit
        cpy #4
        bcs @f4
        lda lc
        ora t0
        sta lc
        cpy #3
        bcs @f3
        jsr mac
        jmp @bump
@f3:    lda t0                  ; the 4th decimal
        sta lj
        bcs @bump
@f4:    bne @bump               ; the 5th rounds the 4th up, and counts as nonzero
        lda t0
        cmp #5
        bcc @bump
        inc lj
        inc lc
@bump:  lda lo
        cmp #5
        bcs @next
        inc lo
        bne @next
@mac:   jsr mac
@next:  inc g_si
        bne :+
        inc g_si+1
:       jsr c_sp
        inx
        inc li
        bne @loop
@nd:    ldy lo
        bpl @pad                ; the decimals are over
        inc lo                  ; the whole part is: keep it, and look for the point
        lda acc
        sta tq
        lda acc+1
        sta tq+1
        and #$80
        ora acc+2
        ora acc+3
        sta tq+2
        ldy #0
        lda (ptr),y
        cmp #'.'
        beq @next               ; step over the point (it counts in li, so a bare . is a number: 0, as MS)
@pad:   lda lo                  ; three decimals at least
        cmp #3
        bcs @end
        lda #0
        sta t0
        jsr mac
        inc lo
        bne @pad
@end:   lda lj
        sta t0
        jsr mac
        lda dvs
        sta ptr
        lda dvs+1
        sta ptr+1
        ldy #3
:       lda acc,y
        sta (ptr),y
        dey
        bpl :-
        lda li
        bne :+
        lda #1
        jsr seterr
:       lda lq
        beq :+
        lda #E_OVF
        jsr seterr
:       ldx sx
        lda lc
        ora tq+2
        ora lq
        ldy li
        beq @big
        tay
        bne @big
        lda tq
        ldy tq+1
        bpl @ret
@big:   lda #$FE
        ldy #$FF
@ret:   sta P_ESTKL,x
        tya
        sta P_ESTKH,x
        rts

; mac: acc = acc * 10 + t0; lq = 1 past 2^31 - 1
mac:    jsr clrhi
        jsr mul10
        lda t0
        ldy #0
        jsr setb
        jsr addb
        lda acc+4
        ora acc+5
        ora acc+6
        ora acc+7
        bne :+
        lda acc+3
        bpl @r
:       sta lq
@r:     ldx sx                  ; (mul10 used X)
        rts

; c_fmt(buf): pop a number and write its text as PRINT shows it to buf (12 bytes at most),
; giving the length: a space or -, then the digits (none before the point when the whole part is 0
; and there is a fraction), the point and the fraction's digits without trailing zeros.
c_fmt:  lda P_ESTKL,x
        sta ptr
        lda P_ESTKH,x
        sta ptr+1
        inx
        stx sx
        jsr whole
        lda #fend - fbuf
        sta t0                  ; t0: where the text starts (it is built backward)
        lda rem                 ; the fraction, 0-9999
        sta fx
        lda rem+1
        sta fx+1
        lda acc                 ; the whole part (under 2^18)
        sta fx+2
        lda acc+1
        sta fx+3
        lda acc+2
        sta fx+4
        lda fx
        ora fx+1
        beq @whole
        ldx #4                  ; four fraction digits; trailing zeros are dropped
        lda #1
        sta dvs+1               ; still dropping zeros
@frac:  stx dvs+2
        lda fx
        sta acc
        lda fx+1
        sta acc+1
        lda #0
        sta acc+2
        sta acc+3
        jsr div10
        lda acc
        sta fx
        lda acc+1
        sta fx+1
        lda rem
        ldy dvs+1
        beq @keep
        cmp #0
        beq @next
        ldy #0
        sty dvs+1
@keep:  jsr putd
@next:  ldx dvs+2
        dex
        bne @frac
        lda #'.'
        jsr putc
        lda fx+2
        ora fx+3
        ora fx+4
        beq @sign               ; " .5": no 0 before the point
@whole: lda fx+2
        sta acc
        lda fx+3
        sta acc+1
        lda fx+4
        sta acc+2
        lda #0
        sta acc+3
        jsr div10
        lda acc
        sta fx+2
        lda acc+1
        sta fx+3
        lda acc+2
        sta fx+4
        lda rem
        jsr putd
        lda fx+2
        ora fx+3
        ora fx+4
        bne @whole
@sign:  lda #' '
        bit sgn
        bpl :+
        lda #'-'
:       jsr putc
        ldx t0                  ; copy it out
        ldy #0
:       lda fbuf,x
        sta (ptr),y
        iny
        inx
        cpx #fend - fbuf
        bne :-
        tya
        ldy #0
        ldx sx
        jmp pushay

mul10:  jsr @dbl                ; acc = acc * 10, for acc under 2^32: (2a) * 4 + 2a, in 5 bytes
        ldy #4
:       lda acc,y
        sta rem,y
        dey
        bpl :-
        jsr @dbl
        jsr @dbl
        ldy #0
        ldx #5
        clc
:       lda acc,y
        adc rem,y
        sta acc,y
        iny
        dex
        bne :-
        rts
@dbl:   asl acc
        rol acc+1
        rol acc+2
        rol acc+3
        rol acc+4
        rts

div10:  lda #10
        ldy #0
        jsr setb
        jmp udiv32
putd:   ora #'0'
putc:   dec t0
        ldy t0
        sta fbuf,y
        rts

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

; c_grow(n): ask the kernel for up to n more pages (SYS_BRK; they are the free ones directly after
; the program's own) for the arena: g_mem = the first, the result the number granted.
c_grow: lda P_ESTKL,x
        stx sx
        ldy #0
        sty r0+1                ; BRK is meminfo with no buffer
        jsr SYS_BRK
        sta g_mem+1
        lda #0
        sta g_mem
        txa
        ldx sx
        sta P_ESTKL,x
        lda #0
        sta P_ESTKH,x
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
        jsr seterr
        jmp ret0
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
        jsr emitb
        jmp ret0
c_room: lda P_ESTKL,x
        jsr roomb
        jmp ret0
c_op1:  lda #1
        jsr roomb
        lda P_ESTKL,x
        jsr emitb
ret0:   lda #0
        sta P_ESTKL,x
        sta P_ESTKH,x
        rts

; c_opw(b, w): an op with a word operand. c_ncall(f): NCAL f (82), after which the return has
; reset Y. 0.
c_opw:  lda #3
        jsr roomb
        lda P_ESTKL+1,x
        jsr emitb
        jsr word
        inx
        jmp ret0
c_ncall: lda #3
        jsr roomb
        lda #82
        jsr emitb
        jsr word
        lda #0
        sta g_straight
        sta g_straight+1
        jmp ret0
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
xstr:   lda #0
        sta g_straight
        sta g_straight+1
        jmp ret0
word:   lda P_ESTKL,x
        jsr emitb
        lda P_ESTKH,x
        jmp emitb

; ---- XOPs (pvm.md, "XOP"): bas's own one-byte opcodes, $C8 + 2 * the index in xtab ----
; The VM calls these as it does a native callee (X the eval stack index), but they keep their
; operands in the code: P_IP and P_IPY say where, and an operand routine advances P_IPY past them.
; Those that are plain n_ routines (no operand) are in xtab as themselves.

xw:     ldy P_IPY               ; the word operand to ptr
        iny
        lda (P_IP),y
        sta ptr
        iny
        lda (P_IP),y
        sta ptr+1
        sty P_IPY
        rts
x_ldv:  jsr xw                  ; XLDV a: push the number at a
        jmp ldv3
x_stv:  jsr xw                  ; XSTV a: pop the number to a
        stx sx
        jmp stv2
x_ldk:  lda P_IPY               ; XLDK b0..b3: push the four bytes after the op
        sec                     ; (ptr = IP + IPY + 1)
        adc P_IP
        sta ptr
        lda P_IP+1
        adc #0
        sta ptr+1
        lda P_IPY
        clc
        adc #4
        sta P_IPY
        jmp ldv3
x_ln:   lda P_IPY               ; XLN: rt_ln, with the op after this one as the position
        sec
        adc P_IP
        sta curip
        lda P_IP+1
        adc #0
        sta curip+1
x_nop:  rts

xtab:   .word x_ldv, x_stv, x_ldk, x_ln                 ; C8 CA CC CE
        .word n_add, n_sub, n_mul, n_div                 ; D0 D2 D4 D6
        .word n_neg, n_cmp, n_int, n_abs                 ; D8 DA DC DE
        .word n_sgn, n_fromi, n_toi, n_tst               ; E0 E2 E4 E6
        .word c_sp, c_tok, c_emit, c_op1                 ; E8 EA EC EE: the compiler's hot externs,
        .word c_ldv, c_digit, c_ncall, c_stv             ; F0 F2 F4 F6  called as one byte (bas.c's
        .word c_room, c_opw, c_fail, c_xop               ; F8 FA FC FE  /* xop N */ declarations)
