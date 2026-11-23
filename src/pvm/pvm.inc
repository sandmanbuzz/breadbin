; pvm.inc - p-code for the Breadbin VM (src/pvm/pvm.s) as ca65 macros. The opcode numbers are
; PLASMA's (docs/design/pvm.md). A bytecode function starts with P_FUNC; addresses are emitted as
; .word so the CX relocation sees them; branch offsets are relative to the offset word.
.import pvm_init, pvm_interp
.importzp pvm_errno

; The eval stack, for native code called with CALL: X is the index of TOS (the entry under it is
; at X+1); a native callee pops and pushes by moving X and returns with RTS. Y is free. These are
; pvm.s's ESTKL and ESTKH (tools/test_cc_pcode.py checks that they agree).
P_ESTKH = $0A
P_ESTKL = $15
; The frame pointer (the frame stack grows down from it), for natives that unwind it (pvm.s's IFP).
; A native reached by CALL or ICAL finds, after TSX, its return address at $0101,x-$0102,x and
; the IP the VM resumes at when it returns at $0103,x (low) and $0104,x (high): rewriting those
; two bytes makes the VM go on elsewhere (docs/design/pvm.md section 4).
P_IFP   = $2D
; For an XOP routine (pvm.s's XOP): the base of the bytecode being run, and the offset of its
; last byte (an operand-reading routine advances P_IPY past what it consumes).
P_IP    = $26
P_IPY   = $2F

.macro P_FUNC
        jsr pvm_interp
.endmacro
.macro P_CN n                   ; 0-15
        .byte (n) * 2
.endmacro
.macro P_OP op
        .byte op
.endmacro
.macro P_B op, n                ; op with a byte operand
        .byte op, n
.endmacro
.macro P_W op, w                ; op with a word operand
        .byte op
        .word .loword(w)
.endmacro
.macro P_BR op, target          ; branch: offset from the offset word
        .byte op
        .word .loword((target) - *)
.endmacro
.macro P_ENTER framesize, params
        .byte $58, framesize, params
.endmacro
.macro P_CS str                 ; string constant: pushes its address (length byte first)
        .byte $2E, .strlen(str), str
.endmacro
.macro P_SYS n                  ; syscall n: TOS -> A/X
        .byte $C6, n
.endmacro
.macro P_SYSY n                 ; syscall n: TOS -> A/X, then TOS-1 -> Y
        .byte $C6, (n) | $80
.endmacro

; Upstream's numbers. The ones no compiler here emits are not in the VM (their table slots trap, docs/design/pvm.md
; section 4): DROP2 DUP DIVMOD ANDI ORI SEL CFFB LLB LAB SLB SAB DLB DLW DAB DAW INCR DECR BRGT BRLT
; INCBRLE ADDBRLE DECBRGE SUBBRGE ADDLB ADDAB IDXLB IDXAB IDXAW NATV JUMPZ.
PO_MINUS1 = $20
PO_BREQ   = $22
PO_BRNE   = $24
PO_LA     = $26
PO_LLA    = $28
PO_CB     = $2A
PO_CW     = $2C
PO_CS     = $2E
PO_DROP   = $30
PO_ADDI   = $38
PO_SUBI   = $3A
PO_ISEQ   = $40
PO_ISNE   = $42
PO_ISGT   = $44
PO_ISLT   = $46
PO_BRFLS  = $4C
PO_BRTRU  = $4E
PO_BRNCH  = $50
PO_CALL   = $54
PO_ICAL   = $56
PO_ENTER  = $58
PO_LEAVE  = $5A
PO_RET    = $5C
PO_LB     = $60
PO_LW     = $62
PO_LLW    = $66
PO_LAW    = $6A
PO_SB     = $70
PO_SW     = $72
PO_SLW    = $76
PO_SAW    = $7A
PO_ADD    = $82
PO_SUB    = $84
PO_MUL    = $86
PO_DIV    = $88
PO_MOD    = $8A
PO_NEG    = $90
PO_COMP   = $92
PO_BAND   = $94
PO_IOR    = $96
PO_XOR    = $98
PO_SHL    = $9A
PO_SHR    = $9C
PO_IDXW   = $9E
PO_ADDLW  = $B2
PO_JUMP   = $C4
PO_SYS    = $C6
PO_XOP    = $C8          ; $C8-$FE: the program's native operations
