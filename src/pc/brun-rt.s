; brun-rt.s - the runner's natives: rt.s alone, with an xtab whose compiler slots are no-ops (a
; compiled file calls only the number and control routines).
.include "inc/rt.s"

.export xtab, c_arg

xtab:   .word x_ldv, x_stv, x_ldk, x_ln                 ; C8 CA CC CE
        .word n_add, n_sub, n_mul, n_div                 ; D0 D2 D4 D6
        .word n_neg, n_cmp, n_int, n_abs                 ; D8 DA DC DE
        .word n_sgn, n_fromi, n_toi, n_tst               ; E0 E2 E4 E6
        .word x_nop, x_nop, x_nop, x_nop                 ; E8-EE: the compiler's, never emitted in a file
        .word c_ldv, x_nop, x_nop, c_stv                 ; F0 F6: the number routines' bytecode (inc/rt.c) uses
        .word x_nop, x_nop, x_nop, x_nop                 ; F8-FE  these two, as bas's xtab has them

; c_arg(n): argv[n] (breadbin.inc: $20 points to the array of string pointers), 0 past its end.
c_arg:  lda P_ESTKL,x
        asl
        tay
        lda (argv),y
        pha
        iny
        lda (argv),y
        sta P_ESTKH,x
        pla
        sta P_ESTKL,x
        rts
