; hello.km: the smallest kernel module. Proves link against the exported kernel API, the
; relocator, the hash check, top-down loading and unloading (docs/design/next/modules-v1.md).
.include "../../include/breadbin.inc"
.include "kexp.inc"

.segment "HEADER"
        jmp init
        jmp fini
        .word KAPI_HASH
        .byte 0                 ; class 0: generic

.segment "CODE"
init:   lda #<s_hi
        ldx #>s_hi
        jsr con_puts_ax
        clc
        rts

fini:   lda #<s_bye
        ldx #>s_bye
        jsr con_puts_ax
        clc
        rts

.segment "RODATA"
s_hi:   .byte "hello from module", 10, 0
s_bye:  .byte "bye from module", 10, 0
