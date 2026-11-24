; brun-rt.s - the runner's natives: rt.s alone, with an xtab whose compiler slots are no-ops (a
; compiled file calls only the number and control routines).
.include "rt.s"

.export xtab

xtab:   .word x_ldv, x_stv, x_ldk, x_ln                 ; C8 CA CC CE
        .word n_add, n_sub, n_mul, n_div                 ; D0 D2 D4 D6
        .word n_neg, n_cmp, n_int, n_abs                 ; D8 DA DC DE
        .word n_sgn, n_fromi, n_toi, n_tst               ; E0 E2 E4 E6
        .word x_nop, x_nop, x_nop, x_nop                 ; E8-FE: the compiler's, never emitted in a file
        .word x_nop, x_nop, x_nop, x_nop
        .word x_nop, x_nop, x_nop, x_nop
