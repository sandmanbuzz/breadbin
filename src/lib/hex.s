; Breadbin user library: hex output
.include "../../include/breadbin.inc"
.include "lib.inc"
.import putc
.export print_hex

.segment "CODE"
; print_hex: A as two hex digits
print_hex:
        pha
        lsr a
        lsr a
        lsr a
        lsr a
        jsr @nib
        pla
        and #$0f
@nib:   cmp #10
        bcc @d
        adc #'a'-'0'-11
@d:     adc #'0'
        jmp putc
