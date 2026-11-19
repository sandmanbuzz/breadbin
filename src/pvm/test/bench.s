; bench.pla compiled by PLASMA's xplasm -AO (upstream f209e30, MIT) and converted from ACME to
; ca65 syntax mechanically (directives only; the bytes are the compiler's). The module init
; (_INIT) is left out: tools/test_pvm.py calls main (_C003) itself.
_D000:	.res 200

_D001:	.res 20

_C000:
	jsr pvm_interp

	.byte	$58,$06,$00

	.byte	$00
	.byte	$76,$04
	.byte	$2A,$C7
	.byte	$04
_B002:
	.byte	$6E,$00

	.byte	$02
	.byte	$26
_F000:	.word .loword(_D000+0)
	.byte	$B2,$00
	.byte	$70
_B003:
	.byte	$A4
	.word .loword(_B002-*)
_B001:
	.byte	$76,$00
	.byte	$30

	.byte	$2A,$C7
	.byte	$04
_B005:
	.byte	$6E,$00

	.byte	$26
_F001:	.word .loword(_D000+0)
	.byte	$B2,$00
	.byte	$60
	.byte	$4C
	.word .loword(_B007-*)
	.byte	$66,$04
	.byte	$8C
	.byte	$76,$04
	.byte	$66,$00
	.byte	$B2,$00
	.byte	$76,$02
	.byte	$50
	.word .loword(_B011-*)
_B009:

	.byte	$00
	.byte	$26
_F002:	.word .loword(_D000+0)
	.byte	$B2,$02
	.byte	$70
	.byte	$66,$02
	.byte	$B2,$00
	.byte	$76,$02
_B011:
	.byte	$66,$02
	.byte	$2A,$C8
	.byte	$46
	.byte	$4E
	.word .loword(_B009-*)
_B010:

_B007:
_B008:

_B006:
	.byte	$A4
	.word .loword(_B005-*)
_B004:
	.byte	$76,$00
	.byte	$30

	.byte	$66,$04
	.byte	$5A,$06

_C001:
	jsr pvm_interp

	.byte	$58,$04,$02
	.byte	$50
	.word .loword(_B014-*)
_B012:

	.byte	$66,$00
	.byte	$66,$02
	.byte	$44
	.byte	$4C
	.word .loword(_B015-*)
	.byte	$66,$00
	.byte	$66,$02
	.byte	$84
	.byte	$76,$00
	.byte	$50
	.word .loword(_B016-*)
_B015:

	.byte	$66,$02
	.byte	$66,$00
	.byte	$84
	.byte	$76,$02
_B016:

_B014:
	.byte	$66,$00
	.byte	$66,$02
	.byte	$24
	.word .loword(_B012-*)
_B013:

	.byte	$66,$00
	.byte	$5A,$04

_C002:
	jsr pvm_interp

	.byte	$58,$04,$00
	.byte	$12
	.byte	$00
_B018:
	.byte	$6E,$00

	.byte	$66,$00
	.byte	$34
	.byte	$9E
	.byte	$26
_F003:	.word .loword(_D001+0)
	.byte	$BA,$00
	.byte	$72
_B019:
	.byte	$A4
	.word .loword(_B018-*)
_B017:
	.byte	$76,$00
	.byte	$30

	.byte	$00
	.byte	$76,$02
	.byte	$12
	.byte	$00
_B021:
	.byte	$6E,$00

	.byte	$66,$02
	.byte	$26
_F004:	.word .loword(_D001+0)
	.byte	$BA,$00
	.byte	$62
	.byte	$82
	.byte	$76,$02
_B022:
	.byte	$A4
	.word .loword(_B021-*)
_B020:
	.byte	$76,$00
	.byte	$30

	.byte	$66,$02
	.byte	$5A,$04

_C003:
	jsr pvm_interp

	.byte	$58,$04,$00

	.byte	$54
_F005:	.word .loword(_C000)
	.byte	$76,$00
	.byte	$2A,$14
	.byte	$02
_B024:
	.byte	$6E,$02

	.byte	$66,$00
	.byte	$66,$02
	.byte	$0C
	.byte	$86
	.byte	$2A,$54
	.byte	$54
_F006:	.word .loword(_C001)
	.byte	$82
	.byte	$76,$00
_B025:
	.byte	$A4
	.word .loword(_B024-*)
_B023:
	.byte	$76,$02
	.byte	$30

	.byte	$66,$00
	.byte	$54
_F007:	.word .loword(_C002)
	.byte	$82
	.byte	$5A,$04
