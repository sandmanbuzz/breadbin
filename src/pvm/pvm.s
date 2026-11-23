; pvm.s - the Breadbin p-code VM: PLASMA's bytecode interpreter, ported to ca65 and to Breadbin.
;
; Derived from the PLASMA C64 VM (src/vmsrc/c64/plvmc64.s, upstream commit f209e30, 2026-11-03),
; https://github.com/dschmenk/PLASMA
;
;   MIT License. Copyright (c) 2010-2022 David Schmenk.
;   Permission is hereby granted, free of charge, to any person obtaining a copy of this software
;   and associated documentation files (the "Software"), to deal in the Software without
;   restriction, including without limitation the rights to use, copy, modify, merge, publish,
;   distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
;   Software is furnished to do so, subject to the following conditions: The above copyright
;   notice and this permission notice shall be included in all copies or substantial portions of
;   the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
;   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
;   PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
;   LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
;   OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
;   DEALINGS IN THE SOFTWARE.
;
; Changes from upstream (docs/design/pvm.md section 4):
; - zero page: the eval stack is 11 deep in $0A-$1F with a 2-byte guard at $08 (kernel syscall
;   scratch, saved per process); the VM state is in $23-$36. Nothing at $40 or above.
; - calls: a CALL/ICAL to a bytecode function (one that starts with JSR pvm_interp) keeps the
;   return IP on the frame stack and uses no 6502 stack; RET pops it, or returns to native code
;   (RTS) at the marker pvm_interp pushes when native code calls in. Native targets as upstream.
;   NATV pushes RET's address so a native tail's RTS returns from the function, as upstream.
; - ENTER spills the caller's pending eval-stack entries to the frame stack when fewer than
;   ESRESERVE would be free, LEAVE restores them under any number of results; an eval stack
;   index out of range at a call or return traps (exit ENOMEM).
; - XOP (opcodes $C8-$FE): the program's own native operations, one byte each (docs/design/pvm.md).
; - SYS n (opcode $C6): a Breadbin syscall, the eval stack saved around it (on the frame stack).
; - no module loader, no cmd, no IINTERP. The VM is a shared library (CX format 3, /lib/pvm): pure
;   code, every byte of state in the process's zero page or frame stack; the image starts with the
;   library id, which tools/cx.py writes and every importing program carries.
; The opcode numbers and their semantics are upstream's, but the ops no Breadbin compiler emits
; were dropped (docs/design/pvm.md, the squish): PLASMA's own output that uses them traps to
; pvm_overflow (exit 12), as do the other limits in section 5 there.

.include "../../include/breadbin.inc"
.export pvm_init, pvm_interp
.exportzp pvm_errno

; ---- zero page ----
ESGUARD = $08           ; 2 bytes the indexed-indirect loads use below TOS
ESTKH   = $0A           ; eval stack high bytes, 11 entries
ESDEPTH = 11
ESRESERVE = 8           ; ENTER keeps at least this many entries free for the callee (spilling)
ESTKL   = ESTKH + ESDEPTH
ESTKSZ  = 2 * ESDEPTH
.assert ESTKL + ESDEPTH = $20, error, "eval stack must end below argv ($20)"
DROP    = $23           ; the fetch routine (10 bytes, copied from zpcode)
NEXTOP  = DROP + 1
FETCHOP = NEXTOP + 1
IP      = FETCHOP + 1   ; the operand of FETCHOP's LDA abs,Y
OPIDX   = FETCHOP + 6   ; the low byte of JMP (OPTBL)
IFP     = DROP + 10     ; frame pointer: the frame stack grows down
IPY     = IFP + 2
ESP     = IPY + 1
JMPTMP  = ESP + 1       ; JMP abs; TMP is its operand
TMP     = JMPTMP + 1
DVSIGN  = TMP + 2
SRC     = DVSIGN + 1
flim    = SRC + 2       ; the bottom of the frame stack (pvm_init)
pvm_errno = flim + 2    ; the last SYS's errno, 0 on success
.assert pvm_errno = $39, error, "VM zero page overlaps the program's ($3A-$3F)"

OP_SYS  = $C6

; The image (src/pvm/pvm.cfg): the library id, handlers up to a page, the opcode table
; page-aligned (JMP (OPTBL) puts the opcode in the low byte), more handlers. No BSS: shared.
.segment "PVM"
        .word 0                 ; the library id: tools/cx.py writes it

; pvm_init: A/Y = top of the frame stack (lo/hi), r0 = its bottom (at least $0100: one allocation
; is at most 255 bytes, so the check in fsalloc cannot wrap). Returns X = eval stack index; native
; code must keep X while it calls bytecode.
pvm_init:
        sta IFP
        sty IFP+1
        lda r0
        sta flim
        lda r0+1
        sta flim+1
        ldy #9
@c:     lda zpcode,y
        sta DROP,y
        dey
        bpl @c
        lda #$4C
        sta JMPTMP
        ldx #ESDEPTH
        rts

zpcode: inx                     ; DROP
        iny                     ; NEXTOP
        .byte $B9, $FF, $FF     ; FETCHOP: lda $FFFF,y (IP)
        .byte $85, OPIDX        ; sta OPIDX
        jmp (OPTBL)

; ---- multiply, divide ----
MUL:    sty IPY
        ldy #$10
        lda ESTKL+1,x
        eor #$FF
        sta TMP
        lda ESTKH+1,x
        eor #$FF
        sta TMP+1
        lda #0
        sta ESTKL+1,x           ; PRODL
@lp:    lsr TMP+1               ; MULTPLRH
        ror TMP                 ; MULTPLRL
        bcs @sh
        sta ESTKH+1,x           ; PRODH
        lda ESTKL,x
        adc ESTKL+1,x
        sta ESTKL+1,x
        lda ESTKH,x
        adc ESTKH+1,x
@sh:    asl ESTKL,x
        rol ESTKH,x
        dey
        bne @lp
        sta ESTKH+1,x
        ldy IPY
        jmp DROP

DIV:    jsr _DIV
        lsr DVSIGN              ; sign(result) = (sign(dividend) + sign(divisor)) & 1
        bcs NEG
        jmp NEXTOP
MOD:    jsr _DIV
        lda TMP                 ; remainder
        sta ESTKL,x
        lda TMP+1
        sta ESTKH,x
        lda DVSIGN              ; remainder takes the dividend's sign
        bmi NEG
        jmp NEXTOP
NEG:    jsr _NEG
        jmp NEXTOP
_NEG:   lda #0
        sec
        sbc ESTKL,x
        sta ESTKL,x
        lda #0
        sbc ESTKH,x
        sta ESTKH,x
        rts
; filler: handlers that fit the rest of the page before the table
COMP:   lda #$FF
        eor ESTKL,x
        sta ESTKL,x
        lda #$FF
        eor ESTKH,x
        sta ESTKH,x
        jmp NEXTOP
BAND:   lda ESTKL+1,x
        and ESTKL,x
        sta ESTKL+1,x
        lda ESTKH+1,x
        and ESTKH,x
        sta ESTKH+1,x
        jmp DROP
IOR:    lda ESTKL+1,x
        ora ESTKL,x
        sta ESTKL+1,x
        lda ESTKH+1,x
        ora ESTKH,x
        sta ESTKH+1,x
        jmp DROP
XOR:    lda ESTKL+1,x
        eor ESTKL,x
        sta ESTKL+1,x
        lda ESTKH+1,x
        eor ESTKH,x
        sta ESTKH+1,x
        jmp DROP
ADD:    lda ESTKL,x
        clc
        adc ESTKL+1,x
        sta ESTKL+1,x
        lda ESTKH,x
        adc ESTKH+1,x
        sta ESTKH+1,x
        jmp DROP
SB:     lda ESTKL,x
        sta ESTKH-1,x
        lda ESTKL+1,x
        sta (ESTKH-1,x)
        inx
        jmp DROP
SUB:    lda ESTKL+1,x
        sec
        sbc ESTKL,x
        sta ESTKL+1,x
        lda ESTKH+1,x
        sbc ESTKH,x
        sta ESTKH+1,x
        jmp DROP
pushov0:  jmp pvm_overflow       ; for the push guards in branch range
BAD     = pvm_overflow          ; the upstream opcodes nothing here emits: they trap (exit ENOMEM)
PRETBL:
; ---- the opcode table ----
        .align 256
.assert OPTBL - PRETBL < 8, error, "padding before the opcode table: move handlers"
OPTBL:  .word CN,CN,CN,CN,CN,CN,CN,CN                           ; 00 02 04 06 08 0A 0C 0E
        .word CN,CN,CN,CN,CN,CN,CN,CN                           ; 10 12 14 16 18 1A 1C 1E
        .word MINUS1,BREQ,BRNE,LA,LLA,CB,CW,CS                  ; 20 22 24 26 28 2A 2C 2E
        .word DROP,BAD,BAD,BAD,ADDI,SUBI,BAD,BAD        ; 30 32 34 36 38 3A 3C 3E
        .word ISEQ,ISNE,ISGT,ISLT,BAD,BAD,BRFLS,BRTRU         ; 40 42 44 46 48 4A 4C 4E
        .word BRNCH,NCAL,CALL,ICAL,ENTER,LEAVE,RET,BAD          ; 50 52 54 56 58 5A 5C 5E
        .word LB,LW,BAD,LLW,BAD,LAW,BAD,BAD                     ; 60 62 64 66 68 6A 6C 6E
        .word SB,SW,BAD,SLW,BAD,SAW,BAD,BAD                     ; 70 72 74 76 78 7A 7C 7E
        .word BAD,ADD,SUB,MUL,DIV,MOD,BAD,BAD                     ; 80 82 84 86 88 8A 8C 8E
        .word NEG,COMP,BAND,IOR,XOR,SHL,SHR,IDXW                ; 90 92 94 96 98 9A 9C 9E
        .word BAD,BAD,BAD,BAD,BAD,BAD,BAD,BAD                      ; A0 A2 A4 A6 A8 AA AC AE
        .word BAD,ADDLW,BAD,BAD,BAD,BAD,BAD,BAD                   ; B0 B2 B4 B6 B8 BA BC BE
        .word BAD,BAD,JUMP,SYS                                       ; C0 C2 C4 C6
.assert * - OPTBL = OP_SYS + 2, error, "SYS is not at its opcode"
        .word XOP,XOP,XOP,XOP,XOP,XOP,XOP,XOP                   ; C8 CA CC CE D0 D2 D4 D6
        .word XOP,XOP,XOP,XOP,XOP,XOP,XOP,XOP                   ; D8 DA DC DE E0 E2 E4 E6
        .word XOP,XOP,XOP,XOP,XOP,XOP,XOP,XOP                   ; E8 EA EC EE F0 F2 F4 F6
        .word XOP,XOP,XOP,XOP                                   ; F8 FA FC FE
.assert * - OPTBL = 256, error, "the opcode table is one page"

; XOP ($C8-$FE, the program's own operations): a native routine behind a one-byte opcode. The
; program keeps a vector table of 28 words in the 56 bytes just below the bottom of its frame
; stack (flim); the vector for opcode op is at flim - 256 + op. The routine is called with JSR as a
; CALL'd native is (X is the eval stack index and may move; A, Y and TMP are free) and RTSes; IP
; and IPY are in zero page, IPY the offset of the last byte the op owns (its own opcode, or its
; operand bytes: a routine that reads operands advances IPY past them). The VM then renormalises
; IP, as a CALL does, so straight-line counts start again. Not for code that redirects control:
; that stays a CALL, which has the return address on the stack.
XOP:    sty IPY
        lda flim
        clc
        adc OPIDX
        sta TMP
        lda flim+1
        adc #$FF
        sta TMP+1
        ldy #0
        lda (TMP),y
        pha
        iny
        lda (TMP),y
        sta TMP+1
        pla
        sta TMP
        jsr JMPTMP
        ldy IPY
        jmp FIXNEXT

_DIV:   sty IPY
        ldy #$11                ; bits + 1
        lda #0
        sta TMP
        sta TMP+1
        sta DVSIGN
        lda ESTKL,x             ; a zero divisor: x / 0 and x % 0 are 0 (the normalising loop would
        ora ESTKH,x             ; give a value that depends on x's bit count)
        bne @dv
        sta ESTKL+1,x           ; the quotient; A is 0, and TMP and DVSIGN are 0 already
        sta ESTKH+1,x
        beq @ex                 ; Z is the ORA's
@dv:    lda ESTKH+1,x
        bpl @pos
        inx
        jsr _NEG
        dex
        lda #$81
        sta DVSIGN
@pos:   ora ESTKL+1,x
        beq @ex
        lda ESTKH,x
        bpl @d1
        jsr _NEG
        inc DVSIGN
@d1:    asl ESTKL+1,x
        rol ESTKH+1,x
        dey
        bcc @d1
@lp:    rol TMP
        rol TMP+1
        lda TMP
        cmp ESTKL,x
        lda TMP+1
        sbc ESTKH,x
        bcc @no
        sta TMP+1
        lda TMP
        sbc ESTKL,x
        sta TMP
        sec
@no:    rol ESTKL+1,x
        rol ESTKH+1,x
        dey
        bne @lp
@ex:    inx
        ldy IPY
        rts


; ---- arithmetic and logic ----
IDXW:   lda ESTKL,x             ; TOS * 2 + TOS-1
        asl
        rol ESTKH,x
        clc
        adc ESTKL+1,x
        sta ESTKL+1,x
        lda ESTKH,x
        adc ESTKH+1,x
        sta ESTKH+1,x
        jmp DROP
SHL:    sty IPY
        ldy ESTKL,x             ; the count, 0 to 255: a loop (fast enough, and 36 bytes smaller)
        beq @sd
@sl:    asl ESTKL+1,x
        rol ESTKH+1,x
        dey
        bne @sl
@sd:    ldy IPY
        jmp DROP
SHR:    sty IPY
        ldy ESTKL,x
        beq @rd
@rl:    lda ESTKH+1,x
        cmp #$80                ; arithmetic: the sign goes back in
        ror ESTKH+1,x
        ror ESTKL+1,x
        dey
        bne @rl
@rd:    ldy IPY
        jmp DROP
ADDI:   iny
        lda (IP),y
        clc
        adc ESTKL,x
        sta ESTKL,x
        bcc :+
        inc ESTKH,x
:       jmp NEXTOP
SUBI:   iny
        lda ESTKL,x
        sec
        sbc (IP),y
        sta ESTKL,x
        bcs :+
        dec ESTKH,x
:       jmp NEXTOP

; ---- constants ----
MINUS1: dex
        bmi pushov1
SETTRUE: lda #$FF
        sta ESTKL,x
        sta ESTKH,x
        jmp NEXTOP
CN:     dex                     ; A = the opcode = constant * 2
        bmi pushov1
        lsr
        sta ESTKL,x
        lda #0
        sta ESTKH,x
        jmp NEXTOP
pushov1:  jmp pvm_overflow       ; for the push guards in branch range
CB:     lda #0
        dex
        bmi pushov1
        sta ESTKH,x
        iny
        lda (IP),y
        sta ESTKL,x
        jmp NEXTOP
LAFIX:  tya                     ; renormalise IP
        clc
        adc IP
        sta IP
        bcc :+
        inc IP+1
:       ldy #$FF
LA:     iny
        bmi LAFIX
        dex
        bmi pushov1
        lda (IP),y
        sta ESTKL,x
        iny
        lda (IP),y
        sta ESTKH,x
        jmp NEXTOP
CW:     dex
        bmi pushov1
        iny
        lda (IP),y
        sta ESTKL,x
        iny
        lda (IP),y
        sta ESTKH,x
        jmp NEXTOP
CS:     dex                     ; push the string's address, skip it
        bmi pushov1
        tya
        sec
        adc IP
        sta IP
        sta ESTKL,x
        lda #0
        tay
        adc IP+1
        sta IP+1
        sta ESTKH,x
        lda (IP),y
        tay
        jmp NEXTOP

; ---- loads ----
LB:     lda ESTKL,x
        sta ESTKH-1,x
        lda (ESTKH-1,x)
        sta ESTKL,x
        lda #0
        sta ESTKH,x
        jmp NEXTOP
LW:     lda ESTKL,x
        sta ESTKH-1,x
        lda (ESTKH-1,x)
        sta ESTKL,x
        inc ESTKH-1,x
        beq @c
        lda (ESTKH-1,x)
        sta ESTKH,x
        jmp NEXTOP
@c:     inc ESTKH,x
        lda (ESTKH-1,x)
        sta ESTKH,x
        jmp NEXTOP
LLAFIX: tya
        clc
        adc IP
        sta IP
        bcc :+
        inc IP+1
:       ldy #$FF
LLA:    iny
        bmi LLAFIX
        lda (IP),y
        dex
        bmi pushov2
        clc
        adc IFP
        sta ESTKL,x
        lda #0
        adc IFP+1
        sta ESTKH,x
        jmp NEXTOP
pushov2:  jmp pvm_overflow       ; for the push guards in branch range
LLW:    iny
        lda (IP),y
        sty IPY
        tay
        dex
        bmi pushov2
        lda (IFP),y
        sta ESTKL,x
        iny
        lda (IFP),y
        sta ESTKH,x
        ldy IPY
        jmp NEXTOP
ADDLW:  iny
        lda (IP),y
        sty IPY
        tay
        lda (IFP),y
        clc
        adc ESTKL,x
        sta ESTKL,x
        iny
        lda (IFP),y
        adc ESTKH,x
        sta ESTKH,x
        ldy IPY
        jmp NEXTOP
pushov3:  jmp pvm_overflow       ; for the push guards in branch range
LAW:    iny
        lda (IP),y
        sta TMP
        iny
        lda (IP),y
        sta TMP+1
        sty IPY
        ldy #0
        lda (TMP),y
        dex
        bmi pushov3
        sta ESTKL,x
        iny
        lda (TMP),y
        sta ESTKH,x
        ldy IPY
        jmp NEXTOP

; ---- stores ----
SW:     lda ESTKL,x
        sta ESTKH-1,x
        lda ESTKL+1,x
        sta (ESTKH-1,x)
        lda ESTKH+1,x
        inc ESTKH-1,x
        beq @c
        sta (ESTKH-1,x)
        inx
        jmp DROP
@c:     inc ESTKH,x
        sta (ESTKH-1,x)
        inx
        jmp DROP
SLW:    iny
        lda (IP),y
        sty IPY
        tay
        lda ESTKL,x
        sta (IFP),y
        iny
        lda ESTKH,x
        sta (IFP),y
        ldy IPY
        bmi FIXDROP
        jmp DROP
FIXDROP: inx                    ; DROP, but Y is past the window: flatten IP first
        jmp FIXNEXT
SAW:    iny
        lda (IP),y
        sta TMP
        iny
        lda (IP),y
        sta TMP+1
        sty IPY
        ldy #0
        lda ESTKL,x
        sta (TMP),y
        iny
        lda ESTKH,x
        sta (TMP),y
        ldy IPY
        bmi FIXDROP
        jmp DROP

; ---- compares ----
ISEQ:   lda ESTKL,x
        cmp ESTKL+1,x
        bne ISFLS
        lda ESTKH,x
        cmp ESTKH+1,x
        bne ISFLS
ISTRU:  lda #$FF
        sta ESTKL+1,x
        sta ESTKH+1,x
        jmp DROP
ISNE:   lda ESTKL,x
        cmp ESTKL+1,x
        bne ISTRU
        lda ESTKH,x
        cmp ESTKH+1,x
        bne ISTRU
ISFLS:  lda #0
        sta ESTKL+1,x
        sta ESTKH+1,x
        jmp DROP
ISGT:   lda ESTKL,x
        cmp ESTKL+1,x
        lda ESTKH,x
        sbc ESTKH+1,x
        bvs ISGTV
        bmi ISTRU
        bpl ISFLS
ISGTV:  bmi ISFLS
        bpl ISTRU
ISLT:   lda ESTKL+1,x
        cmp ESTKL,x
        lda ESTKH+1,x
        sbc ESTKH,x
        bvs ISGTV
        bmi ISTRU
        bpl ISFLS

; ---- branches ----
FIXNEXT: tya
        ldy #0
        sec
        adc IP
        sta IP
        bcc :+
        inc IP+1
:       jmp FETCHOP
BREQ:   inx
        inx
        lda ESTKL-2,x
        cmp ESTKL-1,x
        bne NOBRNCH
        lda ESTKH-2,x
        cmp ESTKH-1,x
        beq BRNCH
        bne NOBRNCH
BRNE:   inx
        inx
        lda ESTKL-2,x
        cmp ESTKL-1,x
        bne BRNCH
        lda ESTKH-2,x
        cmp ESTKH-1,x
        bne BRNCH
        beq NOBRNCH
BRTRU:  inx
        lda ESTKH-1,x
        ora ESTKL-1,x
        bne BRNCH
NOBRNCH: iny
        bmi FIXNEXT
        jmp NEXTOP
BRFLS:  inx
        lda ESTKH-1,x
        ora ESTKL-1,x
        bne NOBRNCH
BRNCH:  tya                     ; flatten IP: TMP = the offset byte
        sec
        adc IP
        sta TMP
        lda #0
        tay
        adc IP+1
        sta TMP+1
        lda (TMP),y             ; a signed byte, from its own address
        bpl :+
        dey
:       clc
        adc TMP
        sta IP
        tya
        adc TMP+1
        sta IP+1
        ldy #0
        jmp FETCHOP

; ---- calls ----
; pvm_interp: the entry of bytecode from native code (JSR pvm_interp, P_FUNC; a bytecode function itself starts at its ENTER):
; push the native-return marker (high byte 0) and run the bytecode after the JSR.
pvm_interp:
        lda #2
        jsr fsalloc
        ldy #1
        lda #0
        sta (IFP),y
        pla
        clc
        adc #1
        sta IP
        pla
        adc #0
        sta IP+1
        ldy #0
        jmp FETCHOP

NCAL:   sec                     ; native code (it can be reached by nothing else: no header)
        .byte $24               ; BIT zp: the clc is skipped
CALL:   clc                     ; a bytecode function: it starts at its ENTER
        iny
        lda (IP),y
        sta TMP
        iny
        lda (IP),y
        sta TMP+1
        jmp CALLTMP
ICAL:   lda ESTKL,x             ; bytecode
        sta TMP
        lda ESTKH,x
        sta TMP+1
        inx
        clc
CALLTMP: php
        cpx #ESDEPTH + 1        ; the eval stack wrapped: trap (see RET)
        bcs pvm_overflow
        tya                     ; IP = the next op
        sec
        adc IP
        sta IP
        bcc :+
        inc IP+1
:       plp
        bcs @native
        lda #2                  ; push the return IP on the frame stack
        jsr fsalloc
        ldy #0
        lda IP
        sta (IFP),y
        iny
        lda IP+1
        sta (IFP),y
        lda TMP                 ; run the function
        sta IP
        lda TMP+1
        sta IP+1
        ldy #0
        jmp FETCHOP
@native: lda IP+1
        pha
        lda IP
        pha
        jsr JMPTMP
        pla
        sta IP
        pla
        sta IP+1
        ldy #0
        jmp FETCHOP
; pvm_overflow: a push found the eval stack full (dex; bmi pushovN after every push that can
; overflow: a 12th entry is never written), or the index was out of range at a call or
; return. The process exits with status ENOMEM (12) instead of running on with wrong values.
pvm_overflow:
        lda #ENOMEM
        jmp SYS_EXIT
; fsalloc: take A bytes (0-255) from the frame stack before anything is written there. Below the
; bottom pvm_init was given, the process exits with ENOMEM. Keeps X and Y.
fsalloc: eor #$FF
        sec
        adc IFP
        sta IFP
        bcs :+
        dec IFP+1
:       cmp flim
        lda IFP+1
        sbc flim+1
        bcc pvm_overflow
        rts
; ENTER framesize, params (always the first op: IP is the function, Y is 0): make the frame and
; move the params into it from the eval stack. If fewer than ESRESERVE entries would be free once
; the params are gone, the caller's pending entries move to the frame stack first and LEAVE moves
; them back, so compiled code like n + f(n - 1) recurses as deep as the frame stack allows, not
; the 11-entry eval stack. The frame stack, low to high: frame, spill count, spilled entries
; (shallowest first), return IP. framesize counts the frame's first byte, which holds framesize
; for LEAVE: locals start at 1.
ENTER:  ldy #2
        txa
        clc
        adc (IP),y              ; X + params: where the caller's pending entries start
        cmp #ESRESERVE
        bcs @nosp
        sta DVSIGN
        lda #ESDEPTH
        sec
        sbc DVSIGN              ; p, the entries to spill
        sta TMP
        asl
        adc #1                  ; 2p + 1 bytes (carry clear: p < 12)
        jsr fsalloc
        stx ESP
        ldx DVSIGN
        ldy #1
@sp:    lda ESTKL,x
        sta (IFP),y
        iny
        lda ESTKH,x
        sta (IFP),y
        iny
        inx
        cpx #ESDEPTH
        bne @sp
        ldx ESP
        lda TMP
        bne @cnt                ; always
@nosp:  lda #0
        sta TMP
        lda #1
        jsr fsalloc
        lda #0
@cnt:   ldy #0
        sta (IFP),y
        iny
        lda (IP),y              ; framesize: the frame's own bytes, the first holding this
        jsr fsalloc
        lda (IP),y
        ldy #0
        sta (IFP),y
        ldy #2
        lda (IP),y
        beq @done
        asl
        tay
@lp:    lda ESTKH,x
        sta (IFP),y
        dey
        lda ESTKL,x
        inx
        sta (IFP),y
        dey
        bne @lp
@done:  txa                     ; spilled: the eval stack is now empty
        clc
        adc TMP
        tax
        ldy #3
        jmp FETCHOP
; LEAVE: drop the frame, put back what ENTER spilled (under the results), return
LEAVE:  ldy #0
        lda (IFP),y
        clc
        adc IFP
        sta IFP
        bcc :+
        inc IFP+1
:       ldy #0
        lda (IFP),y             ; spill count
        beq @none
        sta TMP                 ; p. ENTER left the stack empty, so X..10 are the results
        cpx #ESDEPTH + 1        ; (none for a #0 function, two for #2): move them down p. X past
        bcs @ovf                ; empty (the callee popped more than it pushed): trap here, as
        txa                     ; X - p could land back in range and RET would not see it
        sec
        sbc TMP
        bcs @ok                 ; below 0: more results than fit under the spilled entries, a
@ovf:   jmp pvm_overflow        ; 12th entry: trap before the shift writes it (into page 1)
@ok:    sta ESP                 ; the new X
        tay
@sh:    cpx #ESDEPTH
        bcs @shd
        lda ESTKL,x
        sta ESTKL,y
        lda ESTKH,x
        sta ESTKH,y
        inx
        iny
        bne @sh                 ; always
@shd:   lda #ESDEPTH            ; the spilled entries go back where they were: 11 - p up
        sec
        sbc TMP
        tax
        ldy #1
@rs:    lda (IFP),y
        sta ESTKL,x
        iny
        lda (IFP),y
        sta ESTKH,x
        iny
        inx
        cpx #ESDEPTH
        bne @rs
        ldx ESP
        dey                     ; Y = 2p + 1 - 1: the spill bytes; the count is the inc below
        tya
        clc
        adc IFP
        sta IFP
        bcc @none
        inc IFP+1
@none:  inc IFP                 ; the count byte
        bne RET
        inc IFP+1
; RET: pop the return IP; the marker (high byte 0) means native code called in. An eval stack
; index outside 0-11 means it over- or underflowed: trap rather than run on with wrapped values.
RET:    cpx #ESDEPTH + 1
        bcc :+
        jmp pvm_overflow
:       ldy #0
        lda (IFP),y
        sta TMP
        iny
        lda (IFP),y
        pha
        lda IFP
        clc
        adc #2
        sta IFP
        bcc :+
        inc IFP+1
:       pla
        beq @rts
        sta IP+1
        lda TMP
        sta IP
        ldy #0
        jmp FETCHOP
@rts:   rts
JUMP:   iny
        lda (IP),y
        pha
        iny
        lda (IP),y
        sta IP+1
        pla
        sta IP
        ldy #0
        jmp FETCHOP

; SYS n: syscall n (bits 0-4). Pops TOS into A (low) and X (high); with bit 7 set, then pops
; TOS-1's low byte into Y. r0-r2 are set beforehand with stores to $02-$07. Pushes A | X << 8,
; or -1 with the errno in pvm_errno. The syscall clobbers $08-$1F: the eval stack is saved on
; the frame stack (ESTKSZ bytes, through fsalloc, so a full frame stack exits with ENOMEM).
SYS:    iny
        lda (IP),y
        sty IPY
        pha
        and #$1F
        sta TMP
        asl
        adc TMP                 ; n * 3 (carry clear: n < 32)
        sta TMP
        lda #>SYS_BASE
        sta TMP+1
        lda #ESTKSZ
        jsr fsalloc
        ldy #ESTKSZ-1
@s:     lda ESTKH,y
        sta (IFP),y
        dey
        bpl @s
        stx ESP
        inc ESP
        ldy ESTKL+1,x
        pla
        bpl :+
        inc ESP
:       lda ESTKL,x
        pha
        lda ESTKH,x
        tax
        pla
        jsr JMPTMP
        php
        sta TMP
        stx TMP+1
        ldy #ESTKSZ-1
@r:     lda (IFP),y
        sta ESTKH,y
        dey
        bpl @r
        lda IFP
        clc
        adc #ESTKSZ
        sta IFP
        bcc :+
        inc IFP+1
:       ldx ESP
        dex
        plp
        lda #0                  ; errno 0 on success, so a result of -1 is unambiguous
        bcc @eno
        lda TMP
        ldy #$FF
        sty TMP
        sty TMP+1
@eno:   sta pvm_errno
        lda TMP
        sta ESTKL,x
        lda TMP+1
        sta ESTKH,x
        ldy IPY
        jmp NEXTOP

