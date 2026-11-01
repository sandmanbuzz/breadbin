; hello: the smallest kernel module, a proof of the loader (mod_load/mod_unload).
; Image: offset 0 jmp init, 3 jmp fini, 6 kernel hash, 8 class. Linked against build/kexp.s.
.import con_puts_ax, KHASH
.segment "CODE"
        jmp init
        jmp fini
        .word KHASH
        .byte 1                 ; class 1: test
init:   lda #<msg
        ldx #>msg
        jsr con_puts_ax
        clc
        rts
fini:   clc
        rts
msg:    .byte "hello from a module", 10, 0
