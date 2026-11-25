; bench.pla's bytecode (the docs/design/pvm.md benchmark). It began as PLASMA's xplasm -AO output
; (upstream f209e30, MIT) and is now written with the P_ macros of pvm.inc: this VM dropped the
; opcodes the compilers here never emit, so each PLASMA for loop (DLW, INCBRLE) keeps its counter
; in the local instead of on the eval stack (SLW, then LLW; ADDI 1; SLW; LLW; CB limit; ISGT;
; BRFLS: the loop is `while not i > limit`), INCR is ADDI 1 and DUP a second LLW. The module init (_INIT) is left out:
; tools/test_pvm.py calls main (_C003) itself.
_D000:	.res 200

_D001:	.res 20

; sieve: n = 0; for i = 2 to 199: flags[i] = 1; for i = 2 to 199: if flags[i]: n++; j = i + i; ...
_C000:
	P_ENTER 7, 0
	P_CN 0
	P_B PO_SLW, 5
	P_CN 2
	P_B PO_SLW, 1
_B002:	P_CN 1
	P_W PO_LA, _D000
	P_B PO_ADDLW, 1
	P_OP PO_SB
	P_B PO_LLW, 1
	P_B PO_ADDI, 1
	P_B PO_SLW, 1
	P_B PO_LLW, 1
	P_B PO_CB, 199
	P_OP PO_ISGT
	P_BR PO_BRFLS, _B002
	P_CN 2
	P_B PO_SLW, 1
_B005:	P_W PO_LA, _D000
	P_B PO_ADDLW, 1
	P_OP PO_LB
	P_BR PO_BRFLS, _B007
	P_B PO_LLW, 5
	P_B PO_ADDI, 1
	P_B PO_SLW, 5
	P_B PO_LLW, 1
	P_B PO_ADDLW, 1
	P_B PO_SLW, 3
	P_BR PO_BRNCH, _B011
_B009:	P_CN 0
	P_W PO_LA, _D000
	P_B PO_ADDLW, 3
	P_OP PO_SB
	P_B PO_LLW, 3
	P_B PO_ADDLW, 1
	P_B PO_SLW, 3
_B011:	P_B PO_LLW, 3
	P_B PO_CB, 200
	P_OP PO_ISLT
	P_BR PO_BRTRU, _B009
_B007:	P_B PO_LLW, 1
	P_B PO_ADDI, 1
	P_B PO_SLW, 1
	P_B PO_LLW, 1
	P_B PO_CB, 199
	P_OP PO_ISGT
	P_BR PO_BRFLS, _B005
	P_B PO_LLW, 5
	P_OP PO_LEAVE

; gcd(x, y): while x <> y: if x > y: x = x - y else y = y - x
_C001:
	P_ENTER 5, 2
	P_BR PO_BRNCH, _B014
_B012:	P_B PO_LLW, 1
	P_B PO_LLW, 3
	P_OP PO_ISGT
	P_BR PO_BRFLS, _B015
	P_B PO_LLW, 1
	P_B PO_LLW, 3
	P_OP PO_SUB
	P_B PO_SLW, 1
	P_BR PO_BRNCH, _B016
_B015:	P_B PO_LLW, 3
	P_B PO_LLW, 1
	P_OP PO_SUB
	P_B PO_SLW, 3
_B016:
_B014:	P_B PO_LLW, 1
	P_B PO_LLW, 3
	P_BR PO_BRNE, _B012
	P_B PO_LLW, 1
	P_OP PO_LEAVE

; sum: for i = 0 to 9: a[i] = i * 3; s = 0; for i = 0 to 9: s = s + a[i]; return s
_C002:
	P_ENTER 5, 0
	P_CN 0
	P_B PO_SLW, 1
_B018:	P_B PO_LLW, 1
	P_B PO_LLW, 1
	P_OP PO_IDXW
	P_W PO_LA, _D001
	P_B PO_LLW, 1
	P_OP PO_IDXW
	P_OP PO_SW
	P_B PO_LLW, 1
	P_B PO_ADDI, 1
	P_B PO_SLW, 1
	P_B PO_LLW, 1
	P_B PO_CB, 9
	P_OP PO_ISGT
	P_BR PO_BRFLS, _B018
	P_CN 0
	P_B PO_SLW, 3
	P_CN 0
	P_B PO_SLW, 1
_B021:	P_B PO_LLW, 3
	P_W PO_LA, _D001
	P_B PO_LLW, 1
	P_OP PO_IDXW
	P_OP PO_LW
	P_OP PO_ADD
	P_B PO_SLW, 3
	P_B PO_LLW, 1
	P_B PO_ADDI, 1
	P_B PO_SLW, 1
	P_B PO_LLW, 1
	P_B PO_CB, 9
	P_OP PO_ISGT
	P_BR PO_BRFLS, _B021
	P_B PO_LLW, 3
	P_OP PO_LEAVE

; main: t = sieve(); for k = 1 to 20: t = t + gcd(k * 6, 84); return t + sum()
_C003:
	P_ENTER 5, 0
	P_W PO_CALL, _C000
	P_B PO_SLW, 1
	P_CN 1
	P_B PO_SLW, 3
_B024:	P_B PO_LLW, 1
	P_B PO_LLW, 3
	P_CN 6
	P_OP PO_MUL
	P_B PO_CB, 84
	P_W PO_CALL, _C001
	P_OP PO_ADD
	P_B PO_SLW, 1
	P_B PO_LLW, 3
	P_B PO_ADDI, 1
	P_B PO_SLW, 3
	P_B PO_LLW, 3
	P_B PO_CB, 20
	P_OP PO_ISGT
	P_BR PO_BRFLS, _B024
	P_B PO_LLW, 1
	P_W PO_CALL, _C002
	P_OP PO_ADD
	P_OP PO_LEAVE
