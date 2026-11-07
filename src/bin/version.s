; version: print the Breadbin version
.include "../../include/breadbin.inc"
.import print
.segment "CODE"
        lda #<s
        ldx #>s
        jmp print
.segment "RODATA"
s: .byte "breadbox 0.1", 10
   .byte "based on breadbin by kpatronas@gmail.com", 0
