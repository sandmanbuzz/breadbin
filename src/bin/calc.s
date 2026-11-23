; calc [expression...]: a mini bc. Integers, 16-bit signed (-32768..32767).
;   calc 2+3*4              the arguments, joined by spaces, are one expression
;   echo '7*(2-5)' | calc   with no arguments: one expression per line of stdin
; Operators: + - * / % and unary -, parentheses. / truncates toward zero; % takes the sign of the
; dividend. Literals are 0..32767, so -32768 is an overflow (its negation is not representable).
; Parentheses and unary minus nest at most MAXDEPTH (6) deep.
; Errors go to stderr, one line each; the exit status is 1 if any line failed.
.include "../../include/breadbin.inc"
.import argn, getc, set_input, print_dec, newline, putc, eprint, eputc
ptr = $23               ; parser position in line (zero page)
cp  = $25               ; argument being copied (zero page)
LMAX = 79               ; longest expression line
; The kernel saves at most 128 bytes of stack per process at a switch (STKSAVE) and kills a process
; that has more; a parenthesis level costs about 10 bytes of it. Six levels leave room for the
; interrupt frames: deeper nesting is an error, not a kill.
MAXDEPTH = 6            ; parentheses and unary minus nested deeper than this are an error

; BINOP rhs, fn: the operator is consumed; the left operand (v) is pushed on the CPU stack, the
; right operand is parsed by rhs, the left is pulled back, and fn leaves the result in v. The push
; and pull must sit in the caller's frame: a subroutine's rts would pop the pushed bytes.
.macro BINOP rhs, fn
        jsr advance
        lda vhi
        pha
        lda vlo
        pha
        jsr rhs
        lda vlo
        sta rlo
        lda vhi
        sta rhi
        pla
        sta vlo
        pla
        sta vhi
        jsr fn
.endmacro

.segment "CODE"
        lda #0
        sta linelen
        sta longf
        sta status
        lda argc
        cmp #2
        bcs @args
        ; no arguments: one expression per line of stdin
        lda #0
        jsr set_input
@c:     jsr getc
        bcs @eof
        cmp #10
        beq @line
        jsr storech
        jmp @c
@line:  jsr doline
        jmp @c
@eof:   jsr doline              ; a last line without its newline
        jmp @done
        ; arguments: joined by single spaces into one line
@args:  lda #1
        sta ai
@a:     lda ai
        jsr argn                ; A/X = argv[ai]; carry set past the last one
        bcs @run
        sta cp
        stx cp+1
        lda ai
        cmp #2
        bcc @w
        lda #' '
        jsr storech
@w:     ldy #0
@ch:    lda (cp),y
        beq @nx
        jsr storech
        iny
        bne @ch
@nx:    inc ai
        jmp @a
@run:   jsr doline
@done:  lda status
        jmp SYS_EXIT

; storech: append A to line; a line past LMAX is flagged (longf) and the rest is dropped
storech:
        ldx linelen
        cpx #LMAX
        bcs @full
        sta line,x
        inc linelen
        rts
@full:  lda #1
        sta longf
        rts

; doline: evaluate the line collected so far and reset it
doline: lda longf
        beq @ok
        lda #<e_long
        ldx #>e_long
        jsr report
        jmp @end
@ok:    ldx linelen
        lda #0
        sta line,x
        jsr evalline
@end:   lda #0
        sta linelen
        sta longf
        rts

; evalline: parse and print one expression. Errors unwind to here (fail) and return.
evalline:
        tsx
        stx spsave
        lda #0
        sta depth
        lda #<line
        sta ptr
        lda #>line
        sta ptr+1
        jsr peekc
        bne @go
        rts                     ; blank line
@go:    jsr expr
        jsr peekc
        beq @show
        lda #<e_syn             ; trailing junk after the expression
        ldx #>e_syn
        jmp fail
@show:  lda vhi
        bpl @p
        lda #'-'
        jsr putc
        sec
        lda #0
        sbc vlo
        sta vlo
        lda #0
        sbc vhi
        sta vhi
@p:     lda vlo
        ldx vhi
        jsr print_dec
        jmp newline

; fail: A/X = message. Restores the stack to evalline's frame, so its rts returns to doline.
fail:   sta rp
        stx rp+1
        ldx spsave
        txs
        lda rp
        ldx rp+1
        jmp report

; report: A/X = message: "calc: message" on stderr, and the status becomes 1
report: sta rp
        stx rp+1
        lda #1
        sta status
        lda #<s_pre
        ldx #>s_pre
        jsr eprint
        lda rp
        ldx rp+1
        jsr eprint
        lda #10
        jmp eputc

; Grammar (recursive descent; each level leaves its result in v):
;   expr    := term { ('+' | '-') term }
;   term    := unary { ('*' | '/' | '%') unary }
;   unary   := '-' unary | primary
;   primary := number | '(' expr ')'

expr:   jsr term
@l:     jsr peekc
        cmp #'+'
        beq @add
        cmp #'-'
        beq @sub
        rts
@add:   BINOP term, addv
        jmp @l
@sub:   BINOP term, subv
        jmp @l

term:   jsr unary
@l:     jsr peekc
        cmp #'*'
        beq @mul
        cmp #'/'
        beq @div
        cmp #'%'
        beq @mod
        rts
@mul:   BINOP unary, mulv
        jmp @l
@div:   BINOP unary, divv
        jmp @l
@mod:   BINOP unary, modv
        jmp @l

unary:  jsr peekc
        cmp #'-'
        bne primary
        jsr advance
        jsr enter
        jsr unary
        jsr leave
        sec
        lda #0
        sbc vlo
        sta vlo
        lda #0
        sbc vhi
        sta vhi
        lda vhi                 ; only -(-32768) lands on -32768 again
        cmp #$80
        bne @r
        lda vlo
        bne :+
        jmp ovf
:
@r:     rts

primary:
        jsr peekc
        cmp #'('
        bne @num
        jsr advance
        jsr enter
        jsr expr
        jsr leave
        jsr peekc
        cmp #')'
        beq :+
        jmp syntax
:
        jmp advance
@num:   cmp #'0'
        bcs :+
        jmp syntax
:
        cmp #'9'+1
        bcc :+
        jmp syntax
:
        jmp number

; enter/leave count parenthesis and unary-minus nesting: each level uses CPU stack
enter:  inc depth
        lda depth
        cmp #MAXDEPTH+1
        bcs @deep
        rts
@deep:  lda #<e_deep
        ldx #>e_deep
        jmp fail
leave:  dec depth
        rts

syntax: lda #<e_syn
        ldx #>e_syn
        jmp fail
ovf:    lda #<e_ovf
        ldx #>e_ovf
        jmp fail
divz:   lda #<e_div
        ldx #>e_div
        jmp fail

; peekc: A = next non-space character of the line, not consumed (flags set from A)
peekc:  ldy #0
@s:     lda (ptr),y
        cmp #' '
        bne @r
        inc ptr
        bne @s
        inc ptr+1
        jmp @s
@r:     lda (ptr),y
        rts

; advance: consume the character peekc just found
advance:
        inc ptr
        bne @r
        inc ptr+1
@r:     rts

; v = v + R, signed; overflow when both operands share a sign the result lacks
addv:   lda vhi
        sta ahi                 ; a (the left operand), high byte
        clc
        lda vlo
        adc rlo
        sta vlo
        lda vhi
        adc rhi
        sta vhi
        lda ahi
        eor vhi                 ; a ^ r
        sta tlo
        lda rhi
        eor vhi                 ; b ^ r
        and tlo
        bpl :+
        jmp ovf
:
        rts

; v = v - R, signed; overflow when the operands differ in sign and the result differs from v
subv:   lda vhi
        sta ahi
        sec
        lda vlo
        sbc rlo
        sta vlo
        lda vhi
        sbc rhi
        sta vhi
        lda ahi
        eor rhi                 ; a ^ b
        sta tlo
        lda ahi
        eor vhi                 ; a ^ r
        and tlo
        bpl :+
        jmp ovf
:
        rts

; number: v = the decimal digits at ptr; overflow if above 32767
number: lda #0
        sta vlo
        sta vhi
        ldy #0
@d:     lda (ptr),y
        cmp #'0'
        bcc @done
        cmp #'9'+1
        bcs @done
        sec
        sbc #'0'
        sta dig
        ; v = v*10 + dig, unsigned: t = 2v; v = 8v; v += t; v += dig
        lda vlo
        asl a
        sta tlo
        lda vhi
        rol a
        sta thi
        asl vlo
        rol vhi
        bcc :+
        jmp ovf
:
        asl vlo
        rol vhi
        bcc :+
        jmp ovf
:
        asl vlo
        rol vhi
        bcc :+
        jmp ovf
:
        clc
        lda vlo
        adc tlo
        sta vlo
        lda vhi
        adc thi
        sta vhi
        bcc :+
        jmp ovf
:
        clc
        lda vlo
        adc dig
        sta vlo
        lda vhi
        adc #0
        sta vhi
        bcc :+
        jmp ovf
:
        bpl :+
        jmp ovf
:
        inc ptr
        bne @d
        inc ptr+1
        jmp @d
@done:  rts

; prepmag: A = |v|, B = |R|, negf = $80 when the signs differ
prepmag:
        lda vhi
        eor rhi
        and #$80
        sta negf
        lda vlo
        sta alo
        lda vhi
        sta ahi
        bpl @b
        sec
        lda #0
        sbc alo
        sta alo
        lda #0
        sbc ahi
        sta ahi
@b:     lda rlo
        sta blo
        lda rhi
        sta bhi
        bpl @r
        sec
        lda #0
        sbc blo
        sta blo
        lda #0
        sbc bhi
        sta bhi
@r:     rts

; mulv: v = v * R. The 16x16 product is built in X:B (shift and add); X must end zero.
mulv:   jsr prepmag
        lda #0
        sta xlo
        sta xhi
        ldx #16
@it:    lda blo
        lsr a                   ; C = the multiplier's low bit
        bcc @no
        clc
        lda xlo
        adc alo
        sta xlo
        lda xhi
        adc ahi
        sta xhi
@no:    ror xhi
        ror xlo
        ror bhi
        ror blo
        dex
        bne @it
        lda xlo
        ora xhi
        beq :+
        jmp ovf
:
        lda blo
        sta alo
        lda bhi
        sta ahi
        jmp finish

; divv / modv: A = |v| is the dividend, B = |R| the divisor. Restoring division:
; the quotient builds in A, the remainder in X.
divv:   jsr prepmag
        lda blo
        ora bhi
        bne :+
        jmp divz
:
        jsr divcore
        jmp finish

modv:   jsr prepmag
        lda blo
        ora bhi
        bne :+
        jmp divz
:
        jsr divcore
        lda xlo
        sta alo
        lda xhi
        sta ahi
        lda vhi                 ; the remainder takes the dividend's sign
        and #$80
        sta negf
        jmp finish

divcore:
        lda #0
        sta xlo
        sta xhi
        ldx #16
@it:    asl alo
        rol ahi
        rol xlo
        rol xhi
        sec
        lda xlo
        sbc blo
        sta tlo
        lda xhi
        sbc bhi
        bcc @skip               ; remainder < divisor: quotient bit stays 0
        sta xhi
        lda tlo
        sta xlo
        inc alo
@skip:  dex
        bne @it
        rts

; finish: magnitude in A, negf = $80 for a negative result; sets v or overflows
finish: lda negf
        bmi @neg
        lda ahi
        bpl :+
        jmp ovf
:                 ; above 32767
        lda alo
        sta vlo
        lda ahi
        sta vhi
        rts
@neg:   lda ahi
        cmp #$80
        bcc @ok
        beq :+
        jmp ovf
:                 ; above 32768
        lda alo
        beq :+
        jmp ovf
:
@ok:    sec
        lda #0
        sbc alo
        sta vlo
        lda #0
        sbc ahi
        sta vhi
        rts

.segment "RODATA"
s_pre:  .byte "calc: ", 0
e_syn:  .byte "syntax error", 0
e_ovf:  .byte "overflow", 0
e_div:  .byte "divide by zero", 0
e_deep: .byte "nested too deeply", 0
e_long: .byte "line too long", 0

.segment "BSS"
line:    .res LMAX+1
linelen: .res 1
longf:   .res 1
status:  .res 1
ai:      .res 1
depth:   .res 1
spsave:  .res 1
rp:      .res 2
vlo:     .res 1
vhi:     .res 1
rlo:     .res 1
rhi:     .res 1
alo:     .res 1
ahi:     .res 1
blo:     .res 1
bhi:     .res 1
xlo:     .res 1
xhi:     .res 1
negf:    .res 1
tlo:     .res 1
thi:     .res 1
dig:     .res 1
