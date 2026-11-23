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
; The c_ routines are the same for the mini C (`extern int c_add();`): those bas.c declares
; /* void */ push nothing (they are the n_ routines themselves), the others one result.
;
; Control (pvm.md section 4 item 2, "native callees"): a native routine reached by CALL or ICAL
; finds, above its own return address, the IP the VM resumes at when it returns: low byte at
; $0103 + S, high at $0104 + S. rt_go and rt_throw jump by rewriting it.
;
; Golfed (size over clarity, by the owner's leave): routines fall into each other, share tails,
; skip instructions with BIT ($2C skips 2 bytes, $24 one; a BIT read never hits an I/O register
; that a read changes), and pass flags and registers in conventions of their own, said where.
.include "pvm.inc"
.include "breadbin.inc"

.export n_ldv, n_stv, n_add, n_sub, n_mul, n_div, n_neg, n_abs, n_int, n_sgn
.export n_fromi, n_toi, n_cmp, n_tst
.export rt_mark, rt_go, rt_ln, xtab
.export c_ldv, c_stv, c_add, c_sub, c_mul, c_div, c_int, c_fromi, c_toi, c_cmp, c_const, c_fmt
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
rem:    .res 4                  ; udiv's remainder, right after acc (one shift runs through both);
                                ; umul's bit count
opb:    .res 4                  ; the other operand, the multiplier or divisor
tq:     .res 4
dvs:    .res 4                  ; n_div's divisor while the dividend is scaled
sgn:    .res 1                  ; bit 7: the result is negative
msv:    .res 4                  ; rt_mark: the return address and the resume IP ($0101-$0104 + S),
ms:     .res 1                  ; S, X and IFP
mx:     .res 1
mifp:   .res 2
estk:   .res ESTKSZ
err:    .res 1
curip:  .res 2
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
        lda P_IFP
        sta mifp
        lda P_IFP+1
        sta mifp+1
        ldx #ESTKSZ - 1         ; the whole eval stack (the 0 too): a function called after this
:       lda P_ESTKH,x           ; may spill the entries under X into its frame and reuse them
        sta estk,x
        dex
        bpl :-
        tsx
        stx ms
        ldy #0
:       lda $0101,x
        sta msv,y
        inx
        iny
        cpy #4
        bne :-
        ldx mx
        rts

; rt_go: pop an address; if it is not 0, continue there (absolute, as JUMP).
rt_go:  inx
        lda P_ESTKH-1,x
        tay
        ora P_ESTKL-1,x
        beq @r
        lda P_ESTKL-1,x
        stx sx
        tsx
        sta $0103,x
        tya
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

; pop2: sx = X, then pop b to opb and a to acc. pop1: sx = X, pop to acc. popa, popb: no sx.
; popa also zeroes acc[4-7], and leaves N set (X = $FF). All lose X and keep C.
pop2:   stx sx
        jsr popb
        .byte $2C               ; skip pop1's STX (X is not the caller's now)
pop1:   stx sx
popa:   ldx #3
        .byte $2C               ; skip popb's LDX
popb:   ldx #opb - acc + 3
        ldy nsp
:       dey
        lda nstk,y
        sta acc,x
        dex
        tya
        and #3
        bne :-
        sty nsp
        txa
        bpl rts1                ; popb: X = 7
clrhi:  lda #0
        ldx #3
:       sta acc+4,x
        dex
        bpl :-
rts1:   rts

; ---- arithmetic on acc and opb ----

; abs2: acc and opb to their magnitudes, sgn the sign of their product. abs0: sgn = 0, acc to
; its magnitude. absx: acc[X..X+3] to its magnitude, sgn ^= $80 if it was negative.
; nega: acc = -acc. negx: acc[X..X+3] = -itself. Y is lost; X too.
abs2:   jsr abs0
        ldx #opb - acc
        bne absx
abs0:   lda #0
        sta sgn
        tax
absx:   lda acc+3,x
        bpl rts2
        lda sgn
        eor #$80
        sta sgn
        .byte $2C               ; skip nega's LDX
nega:   ldx #0
negx:   ldy #4
        sec
:       lda #0
        sbc acc,x
        sta acc,x
        inx
        dey
        bne :-
rts2:   rts

; ab: pop b and a (sx = X), b = -b if C is set, then acc += opb: A the top byte, V overflow.
; add4: acc[0-3] += opb. addx: acc[X..X+3] += opb (C out; Y lost).
ab:     jsr pop2
        bcc add4
        ldx #opb - acc
        jsr negx
add4:   ldx #0
addx:   ldy #$FC
        clc
:       lda acc,x
        adc opb - $FC,y
        sta acc,x
        inx
        iny
        bne :-
        rts

; addb: acc (64 bits) += opb (32 bits). ripple: acc[X..7] += C.
addb:   jsr add4
ripple: bcc @r
:       inc acc,x
        bne @r
        inx
        cpx #8
        bne :-
@r:     rts

; setb8: opb = A. tenk: opb = 10,000. tena: acc[0-3] = 10,000. setx: acc[X..X+3] = A | Y << 8.
tena:   ldx #0
        .byte $2C               ; skip tenk's LDX
tenk:   ldx #opb - acc
        lda #<10000
        ldy #>10000
        bne setx
setb8:  ldy #0
        ldx #opb - acc
setx:   sta acc,x
        tya
        sta acc+1,x
        lda #0
        sta acc+2,x
        sta acc+3,x
        rts

; umul: acc[0-3] * opb -> acc (64 bits), unsigned. m10k: acc[0-3] * 10,000.
m10k:   jsr tenk
umul:   jsr clrhi
        lda #32
        sta rem
@l:     lda acc
        lsr a
        bcc @n
        ldx #4
        jsr addx                ; acc[4-7] += opb; the carry out goes in at the top
@n:     ldx #8
:       ror acc-1,x
        dex
        bne :-
        dec rem
        bne @l
        rts

; udiv: acc (64 bits) / opb -> quotient in acc, remainder in rem, unsigned; opb 1 to 2^31
; (so rem, under opb, fits 4 bytes even shifted). ustep: Y more steps.
udiv:   ldx #3
        lda #0
:       sta rem,x
        dex
        bpl :-
        ldy #64
@z:     lda acc+7               ; a 0 top byte while rem is 0: 8 steps that only shift, at once
        bne ustep
        ldx #7
:       lda acc-1,x
        sta acc,x
        dex
        bne :-
        stx acc
        tya
        sec
        sbc #8
        tay
        bne @z
        rts
ustep:  ldx #<-12               ; acc and rem, one bit left
        clc
:       rol acc + 12 - $100,x
        inx
        bne :-
        ldx #$FC                ; tq = rem - opb
        sec
:       lda rem - $FC,x
        sbc opb - $FC,x
        sta tq - $FC,x
        inx
        bne :-
        bcc @n                  ; under opb
        ldx #3
:       lda tq,x
        sta rem,x
        dex
        bpl :-
        inc acc                 ; the quotient bit (bit 0 is 0 after the shift)
@n:     dey
        bne ustep
        rts

; big: Z clear (A not 0) if acc (64 bits) is past 2^31 - 1. X is lost.
big:    lda acc+3
        and #$80
        ldx #3
:       ora acc+4,x
        dex
        bpl :-
        tay
        rts

; the errors: each entry's LDA, then BITs over the LDAs after it, into throw with A intact
ovf:    lda #E_OVF
        .byte $2C
c_throw: lda P_ESTKL,x          ; error n: never returns
        .byte $2C
ilq:    lda #E_ILQ
        .byte $2C
div0:   lda #E_DIV0
        .byte $2C
oom:    lda #E_OOM

; throw: error A. Back to rt_mark's caller, which sees 1; the frame stack, the 6502 stack and
; the eval stack as they were there.
throw:  sta err
        ldx ms
        txs
        ldy #0
:       lda msv,y
        sta $0101,x
        inx
        iny
        cpy #4
        bne :-
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
        inc P_ESTKL,x           ; rt_mark's 0, now 1
        rts

; pusha: acc[0-3] onto the number stack, or OUT OF MEMORY. X is lost.
pusha:  ldy nsp
        cpy #NDEPTH * 4
        bcs oom
        ldx #$FC
:       lda acc - $FC,x
        sta nstk,y
        iny
        inx
        bne :-
        sty nsp
        rts

n_sub:  sec
        .byte $24               ; skip the CLC
n_add:  clc
        jsr ab
        bvs ovf
        lda acc+3               ; a signed 32-bit result: -2^31 is an overflow
        eor #$80
        ora acc+2
        ora acc+1
        ora acc
        beq ovf
        bne push

; fin: acc is a magnitude (64 bits) and sgn its sign: push it, or OVERFLOW past 2^31 - 1.
fin:    jsr big
        bne ovf
        bit sgn
        bpl push
negp:   jsr nega
push:   jsr pusha
        ldx sx
        rts

; ---- the n_ routines ----

; popptr: ptr = the eval stack's top, popped
popptr: lda P_ESTKL,x
        sta ptr
        lda P_ESTKH,x
        sta ptr+1
        inx
        rts

n_ldv:  jsr popptr              ; push the number at an address
ldv3:   stx sx
        ldy #3
:       lda (ptr),y
        sta acc,y
        dey
        bpl :-
        bmi push

n_stv:  jsr popptr              ; pop the number to an address
stv2:   jsr pop1
        ldy #3
:       lda acc,y
        sta (ptr),y
        dey
        bpl :-
        ldx sx
        rts

n_abs:  jsr pop1
        lda acc+3
        bpl push
        bmi negp
n_neg:  jsr pop1
        bmi negp                ; (popa leaves N set)

n_sgn:  jsr pop1                ; -1, 0 or 1
        lda acc+3
        sta sgn                 ; bit 7: the sign, for fin
        ora acc+2
        ora acc+1
        ora acc
        beq push                ; 0
        jsr tena
        jmp fin                 ; (popa zeroed acc[4-7])

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
        jsr abs0
        jmp mul10k

; whole: acc = the integer part of the popped number's magnitude, sgn its sign, rem the
; fraction (sx = X)
whole:  jsr pop1
        jsr abs0
        jsr tenk
        jmp udiv

n_toi:  jsr whole               ; pop a number, push it as an int (toward zero); past
        bit sgn                 ; -32768 to 32767, ILLEGAL QUANTITY
        bpl :+
        jsr nega
:       lda acc+1               ; it fits if acc[2-3] are bit 15 copied: acc[2] + C and
        asl a                   ; acc[3] + C (C on from the one before) are both 0
        lda acc+2
        adc #0
        bne @ilq
        lda acc+3
        adc #0
        bne @ilq
        lda acc
        ldy acc+1
        jmp pushs
@ilq:   jmp ilq

n_int:  jsr whole               ; the largest whole number not above it
        bit sgn
        bpl mul10k
        lda rem                 ; negative with a fraction: one further from 0
        ora rem+1
        cmp #1                  ; C: there is one
        ldx #0
        jsr ripple
mul10k: jsr m10k
        jmp fin

n_mul:  jsr pop2
        jsr abs2
        jsr umul
        jsr tenk
; rdiv: acc / opb rounded half away from zero, then fin
rdiv:   jsr udiv
        ldy #1
        jsr ustep               ; one more quotient bit: acc = 2q + (2 rem >= opb)
        ldx #8
        clc
:       ror acc-1,x
        dex
        bne :-                  ; q, C that bit
        jsr ripple              ; (X = 0)
        jmp fin

n_div:  jsr pop2
        lda opb
        ora opb+1
        ora opb+2
        ora opb+3
        bne :+
        jmp div0
:       jsr abs2
        ldx #3
:       lda opb,x
        sta dvs,x
        dex
        bpl :-
        jsr m10k                ; the dividend times 10,000 (under 2^45)
        ldx #3
:       lda dvs,x
        sta opb,x
        dex
        bpl :-
        bmi rdiv

n_cmp:  sec                     ; pop b, then a: push the int -1, 0 or 1 (a against b)
        jsr ab
        bvs @v
        tay
        ora acc
        ora acc+1
        ora acc+2
        beq @eq                 ; A = 0
        tya
        .byte $2C               ; skip the EOR
@v:     eor #$80                ; overflowed: the true sign is the other one (and it is not 0)
        asl a                   ; C: the sign
        lda #$FF
        adc #0
        eor #$FF                ; $FF if negative, else 0
        tay
        ora #1                  ; $FF or 1
        .byte $24               ; skip the TAY
@eq:    tay
pushs:  ldx sx                  ; push A | Y << 8 at sx
pushay: dex
stay:   sta P_ESTKL,x
        tya
        sta P_ESTKH,x
        rts

n_tst:  jsr pop1                ; pop a number: push the int -1 if it is not 0, else 0
        lda acc
        ora acc+1
        ora acc+2
        ora acc+3
        beq :+
        lda #$FF
:       tay
        jmp pushs

; ---- the c_ routines, for the mini C ----

c_ldv   = n_ldv                 ; void, as c_fail
c_stv   = n_stv
c_add   = n_add                 ; void too: the number stack only
c_sub   = n_sub
c_mul   = n_mul
c_div   = n_div
c_int   = n_int
c_fromi = n_fromi
c_toi   = n_toi
c_cmp   = n_cmp

c_err:  lda err
        ldy #0
        beq pushay
c_curip: lda curip
        ldy curip+1
        jmp pushay

; c_const(buf): read a number at si: digits, a point, digits (spaces among them stepped over, as MS);
; its 4 bytes (units of 1/10000, rounded past 4 decimals) go to buf. Returns the value when it is a whole
; number under 32768, else -2. FAIL 1 for no digits, 4 for a number past 2^31 - 1.
; State, all in the lexer's bytes: li digits seen, lo the decimals seen (-1 in the whole part), lc
; nonzero decimals, lj 1 to round up, lq overflow, tq the whole part (tq+2: past 32767). buf stays
; on the eval stack at sx throughout.
c_const: stx sx
        lda #0
        ldy #7
:       sta acc,y
        dey
        bpl :-
        sty lo                  ; -1
        sta li
        sta lc
        sta lq
        sta lj
        sta nsp                 ; and the number stack is empty (a run that failed can leave it full)
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
        bcc @dec
        bne @next               ; past the 5th decimal: dropped
        inc lo                  ; the 5th rounds the 4th up, and counts as nonzero
        cmp #5
        bcc @next
        inc lj
        inc lc
        bcs @next
@dec:   ora lc
        sta lc
        inc lo
@mac:   jsr mac
@next:  jsr incsi
        jsr c_sp
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
@pad:   lda #0                  ; four decimals
        sta t0
        ldy lo
        cpy #4
        bcs @end
        jsr mac
        inc lo
        bne @pad
@end:   lda lj
        jsr maca
        jsr pusha
        ldx sx
        jsr n_stv               ; to buf; X = sx + 1 after
        dex
        lda #1
        ldy li
        beq :+
        lda lq
        beq @ok
        lda #E_OVF
:       jsr seterr
@ok:    lda lc
        ora tq+2
        ora lq
        ldy li
        beq @big
        tay
        bne @big
        lda tq
        ldy tq+1
        jmp stay
@big:   lda #$FE
        ldy #$FF
        jmp stay

; mac: acc = acc * 10 + t0 (maca: + A); lq nonzero past 2^31 - 1. X = sx after.
mac:    lda #10
        jsr setb8
        jsr umul
        lda t0
maca:   jsr setb8
        jsr addb
        jsr big
        beq :+
        sta lq
:       ldx sx
        rts

incsi:  inc g_si                ; si + 1; Z clear after (si is never 0 then)
        bne :+
        inc g_si+1
:       rts

; c_fmt(buf): pop a number and write its text as PRINT shows it to buf (12 bytes at most),
; giving the length: a space or -, then the digits (none before the point when the whole part is 0
; and there is a fraction), the point and the fraction's digits without trailing zeros.
; Built backward from the last digit: the first 4 that div10 gives are the fraction's.
c_fmt:  jsr popptr
        jsr pop1
        jsr abs0
        lda #fend - fbuf
        sta t0                  ; t0: where the text starts
        lda #4
        sta lc                  ; lc: fraction digits to come (then negative)
@l:     lda #10
        jsr setb8
        jsr udiv                ; rem: the next digit
        dec lc
        bmi @w
        lda rem
        bne @k
        ldy t0
        cpy #fend - fbuf
        beq @f                  ; a trailing zero: dropped
@k:     jsr putd
@f:     lda lc
        bne @l
        ldy t0
        cpy #fend - fbuf
        beq @l                  ; no fraction: the whole part, 0 at least
        lda #'.'
        jsr putc
        bne @t                  ; (putc ends with Z clear)
@w:     lda rem
        jsr putd
@t:     lda acc                 ; the whole part is under 2^18
        ora acc+1
        ora acc+2
        bne @l                  ; " .5": no 0 before the point
        lda #' '
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
        jmp pushs

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
