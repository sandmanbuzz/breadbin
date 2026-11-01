; Do the stable undocumented 6510 opcodes behave as on an NMOS 6510? A standalone C64
; program: each test sets A, X, carry and a memory byte, runs one opcode, captures A, X,
; the byte and the N V Z C flags, and compares them with values worked out by hand
; (checked against VICE first). Prints "ILLEGAL OPS: PASS", or "FAIL" and the ids of the
; failing tests. Results: $C000 = number of failures, $C001.. = their ids.
.setcpu "6502X"
CHROUT = $ffd2
m = $fb                 ; the test byte, in zero page

.segment "LOADADDR"
        .word $0801
.segment "STUB"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

.segment "BSS"
nfail:  .res 1
fails:  .res 31
ra:     .res 1
rx:     .res 1
rp:     .res 1
e:      .res 4

.macro SETUP mem, av, xv, cv
        clv                     ; V is only compared where the opcode defines it
        lda #mem
        sta m
        .if cv = 1
        sec
        .else
        clc
        .endif
        lda #av
        ldx #xv
        .if cv = 1
        sec
        .else
        clc
        .endif
.endmacro
.macro CAPT
        php
        sta ra
        stx rx
        pla
        and #$c3                ; N V Z C
        sta rp
.endmacro
.macro CHK id, ea, ex, em, ep
        lda #ea
        sta e
        lda #ex
        sta e+1
        lda #em
        sta e+2
        lda #ep
        sta e+3
        lda #id
        jsr check
.endmacro

.segment "CODE"
start:  cld
        lda #0
        sta nfail
        ; LAX zp
        SETUP $80, $55, $aa, 0
        lax m
        CAPT
        CHK 1, $80, $80, $80, $80
        SETUP $00, $55, $aa, 0
        lax m
        CAPT
        CHK 2, $00, $00, $00, $02
        ; SAX zp: M = A and X, flags untouched
        SETUP $ff, $f0, $3c, 1
        sax m
        CAPT
        CHK 3, $f0, $3c, $30, $01
        ; DCP zp
        SETUP $10, $0f, $00, 0
        dcp m
        CAPT
        CHK 4, $0f, $00, $0f, $03
        SETUP $00, $05, $00, 0
        dcp m
        CAPT
        CHK 5, $05, $00, $ff, $00
        ; ISC zp
        SETUP $0f, $20, $00, 1
        isc m
        CAPT
        CHK 6, $10, $00, $10, $01
        SETUP $0f, $20, $00, 0
        isc m
        CAPT
        CHK 7, $0f, $00, $10, $01
        ; SLO zp
        SETUP $81, $01, $00, 0
        slo m
        CAPT
        CHK 8, $03, $00, $02, $01
        ; RLA zp
        SETUP $81, $ff, $00, 1
        rla m
        CAPT
        CHK 9, $03, $00, $03, $01
        ; SRE zp
        SETUP $03, $ff, $00, 0
        sre m
        CAPT
        CHK 10, $fe, $00, $01, $81
        ; RRA zp
        SETUP $03, $10, $00, 1
        rra m
        CAPT
        CHK 11, $92, $00, $81, $80
        ; ANC #imm
        SETUP $00, $ff, $00, 0
        anc #$80
        CAPT
        CHK 12, $80, $00, $00, $81
        SETUP $00, $f0, $00, 1
        anc #$0f
        CAPT
        CHK 13, $00, $00, $00, $02
        ; ALR #imm
        SETUP $00, $ff, $00, 1
        alr #$fe
        CAPT
        CHK 14, $7f, $00, $00, $00
        SETUP $00, $07, $00, 0
        alr #$03
        CAPT
        CHK 15, $01, $00, $00, $01
        ; ARR #imm (binary mode)
        SETUP $00, $ff, $00, 1
        arr #$ff
        CAPT
        CHK 16, $ff, $00, $00, $81
        SETUP $00, $80, $00, 0
        arr #$ff
        CAPT
        CHK 17, $40, $00, $00, $41
        ; SBX #imm (X = (A and X) - imm)
        SETUP $00, $f0, $3c, 0
        axs #$01
        CAPT
        CHK 18, $f0, $2f, $00, $01
        SETUP $00, $f0, $0f, 1
        axs #$01
        CAPT
        CHK 19, $f0, $ff, $00, $80
        ; $EB: SBC #imm
        SETUP $00, $20, $00, 1
        .byte $eb, $10
        CAPT
        CHK 20, $10, $00, $00, $01
        ; NOPs change nothing (implied, immediate, zero page, absolute)
        SETUP $5a, $12, $34, 1
        .byte $1a
        .byte $80, $99
        .byte $04, m
        .byte $0c
        .word m
        CAPT
        CHK 21, $12, $34, $5a, $01
        ; report
        lda nfail
        bne @fail
        ldx #0
@p:     lda ok,x
        beq @done
        jsr CHROUT
        inx
        bne @p
@fail:  ldx #0
@f:     lda bad,x
        beq @ids
        jsr CHROUT
        inx
        bne @f
@ids:   ldx #0
@i:     cpx nfail
        beq @done
        lda #' '
        jsr CHROUT
        lda fails,x
        jsr pdec
        inx
        bne @i
@done:  lda #13
        jsr CHROUT
        rts

; check: A = id; compare ra rx m rp with e
check:  tay
        lda ra
        cmp e
        bne @bad
        lda rx
        cmp e+1
        bne @bad
        lda m
        cmp e+2
        bne @bad
        lda rp
        cmp e+3
        bne @bad
        rts
@bad:   ldx nfail
        tya
        sta fails,x
        inc nfail
        rts

pdec:   ldy #'0'-1              ; A (0-99) in decimal
@t:     iny
        sec
        sbc #10
        bcs @t
        adc #10+'0'
        pha
        tya
        cmp #'0'
        beq @one
        jsr CHROUT
@one:   pla
        jmp CHROUT

.segment "RODATA"
ok:     .byte "ILLEGAL OPS: PASS", 0
bad:    .byte "ILLEGAL OPS: FAIL", 0
