; rt.s - the native runtime shared by bas (bas-rt.s) and the runner (brun-rt.s), both of which
; .include it first, so that its labels sit at the same offsets from rt_mark in each: a compiled
; file names the runtime by those offsets (docs/design/basic.md 6.1). Native helpers for bas (src/pc/bas.c, docs/design/basic.md): the fixed-point number
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
.export rt_mark, rt_go, rt_ln, rt_end
.export c_ldv, c_stv, c_add, c_sub, c_mul, c_div, c_int, c_fromi, c_toi, c_cmp, c_fmt
.export c_grow, c_throw, c_err, c_curip

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
lj:     .res 1                  ; the lexer's bytes (bas-rt.s has the rest); c_fmt uses these
lc:     .res 1

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


.import g_mem

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
rt_end:                         ; the end of these natives: only its address is used (rtid in inc/rt.c)
