; exec PATH [ARGS...]: replace this process with PATH (same pid, same descriptors and
; directory). Returns only on failure, with the error printed.
.include "../../include/breadbin.inc"
.import argn, eprint, perr
.segment "CODE"
        lda argc
        cmp #2
        bcc @usage
        lda #1
        jsr argn
        sta r0
        stx r0+1
        lda argv            ; the new argv is ours, minus the first entry
        clc
        adc #2
        sta r1
        lda argv+1
        adc #0
        sta r1+1
        ldy #SP_EXEC
        jsr SYS_SPAWN
        pha                 ; it came back: that is the error
        lda #1
        jsr argn
        pha
        txa
        tay
        pla
        tax
        pla
        jsr perr
        lda #1
        jmp SYS_EXIT
@usage: lda #<usage
        ldx #>usage
        jsr eprint
        lda #1
        jmp SYS_EXIT
.segment "RODATA"
usage:  .byte "usage: exec PATH [ARGS...]", 10, 0
