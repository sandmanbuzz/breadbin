; cache [stat|off|on|flush]: the REU block cache of the boot drive
;   stat   state, hits, reads that went to the bus, bus errors (the default)
;   off    reads go to the bus (writes still keep the cache in step); on: use it again
;   flush  forget every cached block
.include "../../include/breadbin.inc"
.import argn, eprint, print, print_dec_w, newline, perr
ptr = $23
.segment "CODE"
        lda #0
        sta op
        lda argc
        cmp #2
        bcc @run
        bne @usage
        lda #1
        jsr argn
        sta ptr
        stx ptr+1
        ldx #0
@try:   lda words,x         ; the table ends with an empty word
        beq @usage
        ldy #0
@c:     lda words,x
        cmp (ptr),y
        bne @skip
        cmp #0
        beq @run            ; matched, and op is its index
        inx
        iny
        bne @c
@skip:  lda words,x         ; on to the next word
        beq @past
        inx
        bne @skip
@past:  inx
        inc op
        bne @try
@usage: lda #<usage
        ldx #>usage
        jsr eprint
        lda #1
        jmp SYS_EXIT
@run:   lda #<buf
        sta r0
        lda #>buf
        sta r0+1
        lda op
        jsr SYS_CACHE
        bcc @ok
        ldx #0
        ldy #0
        jsr perr
        lda #1
        jmp SYS_EXIT
@ok:    lda op
        bne @ret
        ldx buf
        beq @none
        dex
        beq @off
        lda #<s_on
        ldx #>s_on
        bne @pr
@off:   lda #<s_off
        ldx #>s_off
        bne @pr
@none:  lda #<s_none
        ldx #>s_none
@pr:    jsr print
        lda buf
        beq @nl
        lda #<s_hits
        ldx #>s_hits
        jsr print
        lda buf+1
        ldx buf+2
        ldy #1
        jsr print_dec_w
        lda #<s_miss
        ldx #>s_miss
        jsr print
        lda buf+3
        ldx buf+4
        ldy #1
        jsr print_dec_w
        lda #<s_err
        ldx #>s_err
        jsr print
        lda buf+5
        ldx buf+6
        ldy #1
        jsr print_dec_w
@nl:    jmp newline
@ret:   rts
.segment "RODATA"
words:  .byte "stat", 0, "off", 0, "on", 0, "flush", 0, 0
usage:  .byte "usage: cache [stat|off|on|flush]", 10, 0
s_none: .byte "reu cache: none", 0
s_off:  .byte "reu cache: off", 0
s_on:   .byte "reu cache: on", 0
s_hits: .byte 10, "  hits ", 0
s_miss: .byte 10, "  bus reads ", 0
s_err:  .byte 10, "  bus errors ", 0
.segment "BSS"
buf: .res 8
op:  .res 1
