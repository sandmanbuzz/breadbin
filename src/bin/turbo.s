; turbo [n | off | max]: show or set the Ultimate's CPU speed (docs/roadmap.md "Turbo")
; $D031 bits 0-3 are the speed index (0 = 1 MHz); other bits are left alone. Without the Ultimate's
; "U64 Turbo Registers" (or "Turbo Enable Bit") mode, $D031 reads $FF like any unused VIC register:
; then there is nothing to show or set, and a write is harmless.
.include "../../include/breadbin.inc"
.import print, eprint, argn, parse_dec, print_dec, newline
.importzp lp1
TURBO = $D031
n = $23
.segment "CODE"
        lda TURBO
        cmp #$ff
        beq @none
        lda #1
        jsr argn
        bcs @show
        sta lp1
        stx lp1+1
        ldy #0
        lda (lp1),y
        cmp #'o'                ; off = index 0
        beq @off
        cmp #'m'                ; max = index 15
        beq @max
        lda lp1
        ldx lp1+1
        jsr parse_dec
        bcs @usage
        cpx #0
        bne @usage
        cmp #16
        bcs @usage
        bcc @set
@off:   lda #0
        beq @set
@max:   lda #15
@set:   sta n
        lda TURBO
        and #$f0
        ora n
        sta TURBO
@show:  lda #<s_speed
        ldx #>s_speed
        jsr print
        lda TURBO
        and #$0f
        ldx #0
        jsr print_dec
        jmp newline
@none:  lda #<s_none
        ldx #>s_none
        jsr eprint
        lda #1
        jmp SYS_EXIT
@usage: lda #<s_usage
        ldx #>s_usage
        jsr eprint
        lda #1
        jmp SYS_EXIT
.segment "RODATA"
s_speed: .byte "speed index ", 0
s_none:  .byte "turbo: no turbo registers (set Turbo Mode to U64 Turbo Registers in the Ultimate menu)", 10, 0
s_usage: .byte "usage: turbo [0-15 | off | max]", 10, 0
