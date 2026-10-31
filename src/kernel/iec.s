; Breadbin IEC channels: talk to a drive's channels over the serial bus
;
; Replaces the KERNAL's file layer (SETLFS, SETNAM, OPEN, CLOSE, CHKIN, CHKOUT,
; CHRIN, CHROUT, CLRCHN) and its table of open files. A channel is a drive
; number and a secondary address; nothing is remembered between calls, so any
; process-visible state lives in the callers. The bus itself (LISTEN, TALK,
; SECOND, TKSA, CIOUT, ACPTR, UNLSN, UNTLK) is still the KERNAL's in this step.
;
; The stock status byte ST ($90) is kept: bit 7 device not present, bit 6 EOI,
; bit 1 read timeout, bit 0 write timeout.
.include "k.inc"

; the KERNAL's bus routines
LISTEN = $ffb1
TALK   = $ffb4
SECOND = $ff93
TKSA   = $ff96
CIOUT  = $ffa8
ACPTR  = $ffa5
UNLSN  = $ffae
UNTLK  = $ffab

.export iec_ch_open, iec_ch_close, iec_out_begin, iec_out_byte, iec_out_end
.export iec_in_begin, iec_in_byte, iec_in_end

.segment "BSS"
ie_b:   .res 1
ie_dev: .res 1
ie_sa:  .res 1
ie_len: .res 1

.segment "CODE"
; iec_ch_open: A = drive, X = secondary address, (p4) = name, Y = its length.
; Carry set (A = ENODEV) if the drive does not answer.
iec_ch_open:
        sty ie_len
        stx ie_sa
        jsr out_sa_open
        bcs @r
        ldy #0
@n:     cpy ie_len
        beq @d
        lda (p4),y
        jsr CIOUT
        iny
        bne @n
@d:     jsr UNLSN
        clc
@r:     rts

; iec_ch_close: A = drive, X = secondary address
iec_ch_close:
        stx ie_sa
        sta ie_dev
        lda #0
        sta ST
        lda ie_dev
        jsr LISTEN
        lda ie_sa
        ora #$e0
        jsr SECOND
        jmp UNLSN

; iec_out_begin: A = drive, X = secondary address. Then iec_out_byte per byte
; and iec_out_end. Carry set (A = ENODEV) if the drive does not answer.
iec_out_begin:
        stx ie_sa
        jsr out_sa_data
        rts

; out_sa_open / out_sa_data: LISTEN the drive and send secondary $F0 | sa
; (open) or $60 | sa (data). A = drive.
out_sa_open:
        sta ie_dev
        lda #0
        sta ST
        lda ie_dev
        jsr LISTEN
        lda ie_sa
        ora #$f0
        jmp out_sa_second
out_sa_data:
        sta ie_dev
        lda #0
        sta ST
        lda ie_dev
        jsr LISTEN
        lda ie_sa
        ora #$60
out_sa_second:
        jsr SECOND
        lda ST
        bpl @ok
        jsr UNLSN
        lda #ENODEV
        sec
        rts
@ok:    clc
        rts

; iec_out_byte: A = byte. X and Y are preserved.
iec_out_byte:
        sta ie_b
        txa
        pha
        tya
        pha
        lda ie_b
        jsr CIOUT
        pla
        tay
        pla
        tax
        rts

iec_out_end  = UNLSN

; iec_in_begin: A = drive, X = secondary address. Then iec_in_byte per byte and
; iec_in_end. Carry set (A = ENODEV) if the drive does not answer.
iec_in_begin:
        sta ie_dev
        stx ie_sa
        lda #0
        sta ST
        lda ie_dev
        jsr TALK
        lda ie_sa
        ora #$60
        jsr TKSA
        lda ST
        bpl @ok
        jsr UNTLK
        lda #ENODEV
        sec
        rts
@ok:    clc
        rts

; iec_in_byte: returns A, updates ST. X and Y are preserved.
iec_in_byte:
        txa
        pha
        tya
        pha
        jsr ACPTR
        sta ie_b
        pla
        tay
        pla
        tax
        lda ie_b
        rts

iec_in_end  = UNTLK
