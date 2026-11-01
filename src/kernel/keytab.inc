; Breadbin keyboard decode tables
;
; The standard C64 keyboard layout: for each of the 64 matrix positions
; (index = line*8 + bit, line = the CIA1 port A line driven low, bit = the
; port B bit read back), the PETSCII code produced with no modifier, with
; SHIFT, with the Commodore key, and with CTRL. $FF = produces nothing.
; The modifier keys and RUN/STOP are $FF in every table: they are handled
; by kbd.s itself. tools/check_keytab.py compares these with a KERNAL ROM.
.segment "RODATA"
keytab:
; ---- unshifted
        .byte $14,$0d,$1d,$88,$85,$86,$87,$11   ; line 0: DEL RETURN CRSR-R F7 F1 F3 F5 CRSR-D
        .byte $33,$57,$41,$34,$5a,$53,$45,$ff   ; line 1: 3 W A 4 Z S E LSHIFT
        .byte $35,$52,$44,$36,$43,$46,$54,$58   ; line 2: 5 R D 6 C F T X
        .byte $37,$59,$47,$38,$42,$48,$55,$56   ; line 3: 7 Y G 8 B H U V
        .byte $39,$49,$4a,$30,$4d,$4b,$4f,$4e   ; line 4: 9 I J 0 M K O N
        .byte $2b,$50,$4c,$2d,$2e,$3a,$40,$2c   ; line 5: + P L - . : @ ,
        .byte $5c,$2a,$3b,$13,$ff,$3d,$5e,$2f   ; line 6: POUND * ; HOME RSHIFT = UP-ARROW /
        .byte $31,$5f,$ff,$32,$20,$ff,$51,$ff   ; line 7: 1 LEFT-ARROW CTRL 2 SPACE C= Q STOP
; ---- shift
        .byte $94,$8d,$9d,$8c,$89,$8a,$8b,$91   ; line 0: DEL RETURN CRSR-R F7 F1 F3 F5 CRSR-D
        .byte $23,$d7,$c1,$24,$da,$d3,$c5,$ff   ; line 1: 3 W A 4 Z S E LSHIFT
        .byte $25,$d2,$c4,$26,$c3,$c6,$d4,$d8   ; line 2: 5 R D 6 C F T X
        .byte $27,$d9,$c7,$28,$c2,$c8,$d5,$d6   ; line 3: 7 Y G 8 B H U V
        .byte $29,$c9,$ca,$30,$cd,$cb,$cf,$ce   ; line 4: 9 I J 0 M K O N
        .byte $db,$d0,$cc,$dd,$3e,$5b,$ba,$3c   ; line 5: + P L - . : @ ,
        .byte $a9,$c0,$5d,$93,$ff,$3d,$de,$3f   ; line 6: POUND * ; HOME RSHIFT = UP-ARROW /
        .byte $21,$5f,$ff,$22,$a0,$ff,$d1,$ff   ; line 7: 1 LEFT-ARROW CTRL 2 SPACE C= Q STOP
; ---- commodore
        .byte $94,$8d,$9d,$8c,$89,$8a,$8b,$91   ; line 0: DEL RETURN CRSR-R F7 F1 F3 F5 CRSR-D
        .byte $96,$b3,$b0,$97,$ad,$ae,$b1,$ff   ; line 1: 3 W A 4 Z S E LSHIFT
        .byte $98,$b2,$ac,$99,$bc,$bb,$a3,$bd   ; line 2: 5 R D 6 C F T X
        .byte $9a,$b7,$a5,$9b,$bf,$b4,$b8,$be   ; line 3: 7 Y G 8 B H U V
        .byte $29,$a2,$b5,$30,$a7,$a1,$b9,$aa   ; line 4: 9 I J 0 M K O N
        .byte $a6,$af,$b6,$dc,$3e,$5b,$a4,$3c   ; line 5: + P L - . : @ ,
        .byte $a8,$df,$5d,$93,$ff,$3d,$de,$3f   ; line 6: POUND * ; HOME RSHIFT = UP-ARROW /
        .byte $81,$5f,$ff,$95,$a0,$ff,$ab,$ff   ; line 7: 1 LEFT-ARROW CTRL 2 SPACE C= Q STOP
; ---- control
        .byte $ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff   ; line 0: DEL RETURN CRSR-R F7 F1 F3 F5 CRSR-D
        .byte $1c,$17,$01,$9f,$1a,$13,$05,$ff   ; line 1: 3 W A 4 Z S E LSHIFT
        .byte $9c,$12,$04,$1e,$03,$06,$14,$18   ; line 2: 5 R D 6 C F T X
        .byte $1f,$19,$07,$9e,$02,$08,$15,$16   ; line 3: 7 Y G 8 B H U V
        .byte $12,$09,$0a,$92,$0d,$0b,$0f,$0e   ; line 4: 9 I J 0 M K O N
        .byte $ff,$10,$0c,$ff,$ff,$1b,$00,$ff   ; line 5: + P L - . : @ ,
        .byte $1c,$ff,$1d,$ff,$ff,$1f,$1e,$ff   ; line 6: POUND * ; HOME RSHIFT = UP-ARROW /
        .byte $90,$06,$ff,$05,$ff,$ff,$11,$ff   ; line 7: 1 LEFT-ARROW CTRL 2 SPACE C= Q STOP
