; Breadbin IEC: the serial bus and the drive's channels
;
; Two layers. The bus (bus_listen, bus_talk, bus_second, bus_tksa, bus_ciout,
; bus_acptr, bus_unlsn, bus_untlk) bit-bangs the standard Commodore serial
; protocol on CIA2 port A. The channels (iec_ch_open ... iec_in_end) are a drive
; number and a secondary address on top of it; nothing is remembered between
; calls. Standard protocol only: no fast-loader or JiffyDOS handshakes.
;
; Written from the published protocol and timing table (the CBM IEC bus
; description in MAME's cbmiec.cpp), not from the KERNAL.
;
; Port bits ($DD00): 3 ATN out, 4 CLK out, 5 DATA out, 6 CLK in, 7 DATA in. On
; the output side a 1 pulls the line low (asserts it); the input bits are the
; true line level, so a 0 means some device is pulling the line low. Bits 0-2
; belong to the VIC bank and RS-232 and are kept.
;
; The stock status byte ST ($90) is kept: bit 7 device not present, bit 6 EOI,
; bit 1 read timeout, bit 0 write timeout.
;
; Interrupts are held off while we are the talker: once a listener is ready for
; data we must start within 200 us or it takes the byte for the last one (EOI),
; so an interrupt in that window would corrupt the transfer. A busy drive can
; therefore stop the clock and keyboard (a format does). When we are the
; listener the talker may be kept waiting, so that wait runs with interrupts on.
; Needs a 1 MHz CPU: turn turbo off around bus use.
.include "k.inc"

PORT   = $dd00
A_ATN  = $08
A_CLK  = $10
A_DAT  = $20

; delay counts for dly: 5 cycles each plus about 14 for the call
D_TS   = 8          ; bit set-up (>= 20 us)
D_TV   = 10         ; bit valid (>= 20 us, 60 for a talker)
D_TBB  = 20         ; between bytes (>= 100 us)
D_TR   = 4          ; frame to release of ATN (>= 20 us)
D_EOIH = 14         ; hold DATA to acknowledge EOI (>= 60 us)

.export iec_ch_open, iec_ch_close, iec_out_begin, iec_out_byte, iec_out_end
.export iec_in_begin, iec_in_byte, iec_in_end

.segment "BSS"
io_out:  .res 1     ; the lines we assert now
io_base: .res 1     ; port bits 0-2, kept
io_b:    .res 1     ; byte on the wire
io_n:    .res 1     ; bit count
io_to:   .res 1     ; outer timeout count
io_pend: .res 1     ; a byte is held back so the last one can carry EOI
io_held: .res 1
io_eoi:  .res 1     ; send this byte with EOI
io_inf:  .res 1     ; wait for a busy device without a limit (set under ATN)
io_sx:   .res 1     ; callers' X and Y
io_sy:   .res 1
ie_dev:  .res 1
ie_sa:   .res 1
ie_len:  .res 1
ie_len2: .res 1

.segment "CODE"
; ---------------------------------------------------------------------
; bus level

; io_set: A = lines to assert
io_set: sta io_out
        ora io_base
        sta PORT
        rts

; dly: X = count
dly:    dex
        bne dly
        rts

; io_idle: release every line
io_idle:
        lda #0
        beq io_set

; io_atn_begin: assert ATN and CLK and see that some device pulls DATA (within
; 1 ms). Carry set if none does. Interrupts must be off.
io_atn_begin:
        lda PORT
        and #$07
        sta io_base
        lda #0
        sta io_pend
        ldx #D_TBB
        jsr dly
        lda #A_ATN | A_CLK
        jsr io_set
        ldy #96
@w:     bit PORT
        bpl @ok             ; DATA low: something is listening
        dey
        bne @w
        sec
        rts
@ok:    clc
        rts

; io_tx: A = byte. Send it as talker, CLK held low on entry; io_eoi != 0 sends
; it with EOI. Carry set if the listener never answered. Interrupts must be off.
io_tx:  sta io_b
        lda io_out
        and #<~A_CLK        ; ready to send
        jsr io_set
        lda #4              ; wait for every listener to be ready for data
        sta io_to
        ldy #0
        ldx #0
@rfd:   bit PORT
        bmi @rdy            ; DATA released
        dey
        bne @rfd
        dex
        bne @rfd
        dec io_to
        bne @rfd
        lda io_inf          ; a device that answered ATN is there, only busy
        beq @fail
        inc io_to
        bne @rfd
@fail:  sec
        rts
@rdy:   lda io_eoi
        beq @go
        ldy #200            ; say nothing: after > 200 us the listener pulls DATA
@ea:    bit PORT
        bpl @ea1            ; it pulled DATA
        dey
        bne @ea
        sec
        rts
@ea1:   ldy #96
@eb:    bit PORT
        bmi @go             ; and released it again
        dey
        bne @eb
        sec
        rts
@go:    lda io_out
        ora #A_CLK
        jsr io_set
        lda #8
        sta io_n
@bit:   lsr io_b
        lda io_out
        bcs @one
        ora #A_DAT          ; a 0 is DATA low
        bne @put
@one:   and #<~A_DAT
@put:   jsr io_set
        ldx #D_TS
        jsr dly
        lda io_out
        and #<~A_CLK        ; the bit is valid
        jsr io_set
        ldx #D_TV
        jsr dly
        lda io_out
        ora #A_CLK
        jsr io_set
        dec io_n
        bne @bit
        lda io_out
        and #<~A_DAT        ; let the listener acknowledge the frame
        jsr io_set
        ldy #200
@ack:   bit PORT
        bpl @acked          ; DATA pulled: accepted
        dey
        bne @ack
        sec
        rts
@acked: ldx #D_TBB
        jsr dly
        clc
        rts

; io_cmd: A = byte, sent under ATN to the device. Sets ST bit 7 and leaves the
; bus idle if it fails. Interrupts must be off. Carry set on failure.
io_cmd: ldx #0
        stx io_eoi
        inx
        stx io_inf
        jsr io_tx
        bcs io_fail
        rts
io_fail:
        lda ST
        ora #$80
        sta ST
        jsr io_idle
        sec
        rts

; io_first: A = TALK or LISTEN byte: start the attention sequence and send it
io_first:
        pha
        jsr io_atn_begin
        bcc @ok
        pla
        jmp io_fail
@ok:    pla
        jmp io_cmd

; io_atn_off: after the last byte under ATN
io_atn_off:
        ldx #D_TR
        jsr dly
        lda io_out
        and #<~A_ATN
        jmp io_set

; bus_listen: A = device
bus_listen:
        ora #$20
        bne bus_first
; bus_talk: A = device
bus_talk:
        ora #$40
bus_first:
        php
        sei
        jsr io_first
        plp
        rts

; bus_second: A = secondary address (with its command bits)
bus_second:
        php
        sei
        tax                 ; the byte survives the status check
        lda ST
        bmi @r              ; LISTEN already failed
        txa
        jsr io_cmd
        bcs @r
        jsr io_atn_off
        clc
@r:     plp
        rts

; bus_tksa: A = secondary address. Then the bus is turned around: the device
; talks and we listen.
bus_tksa:
        php
        sei
        tax
        lda ST
        bmi @r              ; TALK already failed
        txa
        jsr io_cmd
        bcs @r
        ldx #D_TR
        jsr dly
        lda #A_DAT          ; ATN off, CLK released, DATA low, all in one write: we
        jsr io_set          ; are the listener from this instant. Any pause here
                            ; hides the device's short clock pulse behind our own
@w:     bit PORT            ; the device takes over the clock: CLK goes low. It
        bvs @w              ; may be finishing a command first; it has answered
        clc                 ; both bytes, so wait as long as it takes
@r:     plp
        rts

; bus_ciout: A = byte for the listener. One byte is held back so that the last
; one can carry EOI.
bus_ciout:
        pha
        php
        sei
        lda io_pend
        beq @hold
        lda ST
        and #$83
        bne @hold           ; the bus has failed: send nothing more
        lda io_held
        ldx #0
        stx io_eoi
        stx io_inf
        jsr io_tx
        bcc @hold
        lda ST
        ora #$01
        sta ST
@hold:  plp
        pla
        sta io_held
        lda #1
        sta io_pend
        rts

; bus_unlsn: send the held byte with EOI, then UNLISTEN
bus_unlsn:
        php
        sei
        lda io_pend
        beq @u
        lda #0
        sta io_pend
        lda ST
        and #$83
        bne @u
        lda #1
        sta io_eoi
        lda #0
        sta io_inf
        lda io_held
        jsr io_tx
        bcc @u
        lda ST
        ora #$01
        sta ST
@u:     lda #$3f
        jsr io_last
        plp
        rts

; bus_untlk: UNTALK
bus_untlk:
        php
        sei
        lda #$5f
        jsr io_last
        plp
        rts

; io_last: A = UNLISTEN or UNTALK: send it under ATN and leave the bus idle
io_last:
        jsr io_first
        bcs @r
        ldx #D_TR
        jsr dly
        jsr io_idle
@r:     rts

; bus_acptr: receive a byte from the talker into A. EOI sets ST bit 6; a wait
; that runs out sets ST bit 1.
bus_acptr:
        php
        txa
        pha
        tya
        pha
        ; the talker is ready when it lets go of CLK; a busy drive can take as
        ; long as it likes, so wait with interrupts enabled
        cli
@rdy:   bit PORT
        bvc @rdy            ; CLK still low: the talker is not ready
        sei
        lda io_out
        and #<~A_DAT        ; ready for data
        jsr io_set
        ldy #90             ; the talker answers within 200 us unless this is EOI; wait ~1 ms to be sure
@a:     bit PORT
        bvc @st             ; CLK low again: no EOI
        dey
        bne @a
        lda io_out          ; EOI: acknowledge it
        ora #A_DAT
        jsr io_set
        ldx #D_EOIH
        jsr dly
        lda io_out
        and #<~A_DAT
        jsr io_set
        lda ST
        ora #$40
        sta ST
        ldx #0
        ldy #0
@b:     bit PORT
        bvc @st
        dey
        bne @b
        dex
        bne @b
        beq @tmo
@st:    lda #8
        sta io_n
@bit:   ldy #0
@c:     bit PORT            ; wait for CLK released: the bit is valid
        bvs @v
        dey
        bne @c
        beq @tmo
@v:     bpl @zero           ; DATA low is a 0
        sec
        bcs @in
@zero:  clc
@in:    ror io_b
        ldy #0
@d:     bit PORT            ; wait for CLK low again
        bvc @nx
        dey
        bne @d
        beq @tmo
@nx:    dec io_n
        bne @bit
        lda io_out
        ora #A_DAT          ; byte accepted
        jsr io_set
        lda io_b
        jmp @out
@tmo:   lda ST
        ora #$02
        sta ST
        lda #0
@out:   sta io_b
        pla
        tay
        pla
        tax
        plp
        lda io_b
        rts

; ---------------------------------------------------------------------
; channel level

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
        jsr iec_out_byte
        iny
        bne @n
@d:     jsr bus_unlsn
        clc
@r:     rts

; iec_ch_close: A = drive, X = secondary address
iec_ch_close:
        stx ie_sa
        sta ie_dev
        lda #0
        sta ST
        lda ie_dev
        jsr bus_listen
        lda ie_sa
        ora #$e0
        jsr bus_second
        jmp bus_unlsn

; iec_out_begin: A = drive, X = secondary address. Then iec_out_byte per byte
; and iec_out_end. Carry set (A = ENODEV) if the drive does not answer.
iec_out_begin:
        stx ie_sa
        jmp out_sa_data

; out_sa_open / out_sa_data: LISTEN the drive and send secondary $F0 | sa
; (open) or $60 | sa (data). A = drive.
out_sa_open:
        ldy #$f0
        bne out_sa
out_sa_data:
        ldy #$60
out_sa: sty ie_len2
        sta ie_dev
        lda #0
        sta ST
        lda ie_dev
        jsr bus_listen
        lda ie_sa
        ora ie_len2
        jsr bus_second
        lda ST
        bpl @ok
        lda #ENODEV
        sec
        rts
@ok:    clc
        rts

; iec_out_byte: A = byte. X and Y are preserved.
iec_out_byte:
        stx io_sx
        sty io_sy
        jsr bus_ciout
        ldx io_sx
        ldy io_sy
        rts

iec_out_end  = bus_unlsn

; iec_in_begin: A = drive, X = secondary address. Then iec_in_byte per byte and
; iec_in_end. Carry set (A = ENODEV) if the drive does not answer.
iec_in_begin:
        sta ie_dev
        stx ie_sa
        lda #0
        sta ST
        lda ie_dev
        jsr bus_talk
        lda ST
        bmi @bad
        lda ie_sa
        ora #$60
        jsr bus_tksa
        lda ST
        bpl @ok
@bad:   lda #ENODEV
        sec
        rts
@ok:    clc
        rts

; iec_in_byte: returns A, updates ST. X and Y are preserved.
iec_in_byte = bus_acptr

iec_in_end  = bus_untlk
