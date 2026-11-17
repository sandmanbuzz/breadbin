; Breadbin IEC: the serial bus and the drive's channels
;
; Two layers. The bus (bus_listen, bus_talk, bus_second, bus_tksa, bus_ciout,
; bus_acptr, bus_unlsn, bus_untlk) bit-bangs the standard Commodore serial
; protocol on CIA2 port A. The channels (iec_ch_open ... iec_in_end) are a drive
; number and a secondary address on top of it. One thing is remembered between
; calls: io_dirty, per drive, says a send to it failed part way, so the drive may
; hold half a command; io_flush clears that before the next LISTEN to it.
; Standard protocol only: no fast-loader or JiffyDOS handshakes.
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
.export io_dirty           ; blk_init marks every drive at boot (a C64-only restart)

.segment "BSS"
io_out:  .res 1     ; the lines we assert now
io_base: .res 1     ; port bits 0-2, kept
io_b:    .res 1     ; byte on the wire
io_n:    .res 1     ; bit count
.if IOSTAT
iec_io_n = io_n         ; for blk.s's IOSTAT record
.export iec_io_n
.endif
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
io_dirty: .res 4    ; per drive (number & 3): a send to it failed part way, or none yet this boot (io_flush).
                    ; Every caller talks to dev_drive's 8-11 only; device 4-7 or 12-15 would share
                    ; a mark with 8-11 (a send to a printer is not supported here)

.segment "IECBUS"
; This module has a segment of its own, the first in KRAM ($A700, kernel.cfg): its place in
; the page then depends on this file alone, not on the size of every module linked before it.
; The bit loops below are timed by the cycle, and a taken branch that crosses a page costs one
; more. The channel level (nothing timed) comes first and puts io_set at IO_AT in its page, so
; that every timed branch crosses a page, or does not, exactly as in the layout that was
; validated in VICE (stock and JiffyDOS ROMs) and on the real 1541 and Ultimate (main before
; bus_tksa was bounded). tb and tx below make the link fail if that ever changes.
IO_AT = $a5        ; main has io_set at $a7; $a5-$a7 give the same crossings (lower fails the link)
iec_seg:
.assert <iec_seg = 0, error, "iec.s: IECBUS must start a page (first in KRAM)"

; tb: a timed branch that must not cross a page; tx: one that crossed a page in the validated
; layout and must keep doing so (one cycle more when taken).
.macro tb op, dest
        op dest
        .assert >* = >(dest), error, "iec.s: a timed branch now crosses a page (see IO_AT)"
.endmacro
.macro tx op, dest
        op dest
        .assert >* <> >(dest), error, "iec.s: a timed branch no longer crosses a page (see IO_AT)"
.endmacro

; ---------------------------------------------------------------------
; channel level

; iec_ch_open: A = drive, X = secondary address, (p4) = name, Y = its length.
; Carry set if the drive does not answer (A = ENODEV) or the name did not get
; through (A = EIO).
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
@d:     jmp iec_out_end
@r:     rts

; iec_out_begin: A = drive, X = secondary address. Then iec_out_byte per byte
; and iec_out_end. Carry set if the drive does not answer (A = ENODEV), or an
; earlier send to it that failed could not be flushed (io_flush).
iec_out_begin:
        stx ie_sa
        jmp out_sa_data

; out_sa_open / out_sa_data: LISTEN the drive and send secondary $F0 | sa
; (open) or $60 | sa (data). A = drive. A LISTEN or secondary not taken (ST bit 7)
; is tried three times before it is ENODEV: a present drive that missed one frame
; ack is not "no drive" (at boot that would adopt the REU root). The flush's own
; LISTEN counts the same way (io_flush: ENODEV, the mark kept).
out_sa_open:
        ldy #$f0
        bne out_sa
out_sa_data:
        ldy #$60
out_sa: sty ie_len2
        sta ie_dev
        lda #3              ; tries, on the stack
        pha
@try:   jsr io_flush
        bcc @l
        cmp #ENODEV
        beq @n
        tay                 ; EIO: the flush failed part way, final
        pla
        tya
        sec
        rts
@l:     lda #0
        sta ST
        lda ie_dev
        jsr bus_listen
        lda ie_sa
        ora ie_len2
        jsr bus_second
        lda ST
        bpl @ok
@n:     pla
        sec
        sbc #1
        beq io_nodev
        pha
        bne @try
@ok:    pla
        clc
        rts
io_nodev:
        lda #ENODEV
        sec
        rts

; iec_in_begin: A = drive, X = secondary address. Then iec_in_byte per byte and
; iec_in_end. Carry set if the drive does not answer (A = ENODEV) or the bus
; did not turn around (A = EIO; the drive has been sent UNTALK).
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
        bmi @bad
        and #$02            ; the turnaround timed out: the drive is there,
        beq @ok             ; so free it (UNTALK) and say so
        jsr bus_untlk
        lda #EIO
        sec
        rts
@bad:   lda #ENODEV
        sec
        rts
@ok:    clc
        rts

; iec_in_byte: returns A, updates ST. X and Y are preserved.
iec_in_byte = bus_acptr

iec_in_end  = bus_untlk

        .res IO_AT - (* - iec_seg)      ; a few bytes: io_set at IO_AT
.assert * - iec_seg = IO_AT, error, "iec.s: the channel level outgrew IO_AT"

; ---------------------------------------------------------------------
; bus level

; io_set: A = lines to assert
io_set: sta io_out
        ora io_base
        sta PORT
        rts

; dly: X = count
dly:    dex
        tb bne, dly
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
        tb bpl, @ok         ; DATA low: something is listening
        dey
        tb bne, @w
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
        tx bmi, @rdy        ; DATA released
        dey
        tb bne, @rfd
        dex
        tb bne, @rfd
        dec io_to
        tx bne, @rfd
        lda io_inf          ; a device that answered ATN is there, only busy
        tb beq, @fail
        inc io_to
        tx bne, @rfd
@fail:  sec
        rts
@rdy:   lda io_eoi
        tb beq, @go
        ldy #200            ; say nothing: after > 200 us the listener pulls DATA
@ea:    bit PORT
        tb bpl, @ea1        ; it pulled DATA
        dey
        tb bne, @ea
        sec
        rts
@ea1:   ldy #96
@eb:    bit PORT
        tb bmi, @go         ; and released it again
        dey
        tb bne, @eb
        sec
        rts
@go:    lda io_out
        ora #A_CLK
        jsr io_set
        lda #8
        sta io_n
@bit:   lsr io_b
        lda io_out
        tb bcs, @one
        ora #A_DAT          ; a 0 is DATA low
        tb bne, @put
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
        tb bne, @bit
        lda io_out
        and #<~A_DAT        ; let the listener acknowledge the frame
        jsr io_set
        ldy #200
@ack:   bit PORT
        tb bpl, @acked      ; DATA pulled: accepted
        dey
        tb bne, @ack
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
        ; (bounded, about 2 s: a drive that stalls mid-byte holds CLK low until
        ; ATN, and no wait here may be forever)
        cli
        lda #3
        sta io_n
        ldy #0
        ldx #0
@rdy:   bit PORT
        tb bvs, @go         ; CLK released: the talker is ready
        dex
        tb bne, @rdy
        dey
        tb bne, @rdy
        dec io_n
        tb bne, @rdy
        sei
        jmp @tmo
@go:    sei
        lda io_out
        and #<~A_DAT        ; ready for data
        jsr io_set
        ldy #90             ; the talker answers within 200 us unless this is EOI; wait ~1 ms to be sure
@a:     bit PORT
        tb bvc, @st         ; CLK low again: no EOI
        dey
        tb bne, @a
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
        tb bvc, @st
        dey
        tb bne, @b
        dex
        tb bne, @b
        beq @tmo
@st:    lda #8
        sta io_n
@bit:   ldy #0
@c:     bit PORT            ; wait for CLK released: the bit is valid
        tb bvs, @v
        dey
        tb bne, @c
        beq @tmo
@v:     tb bpl, @zero       ; DATA low is a 0
        sec
        tb bcs, @in
@zero:  clc
@in:    ror io_b
        ldy #0
@d:     bit PORT            ; wait for CLK low again
        tb bvc, @nx
        dey
        tb bne, @d
        beq @tmo
@nx:    dec io_n
        tb bne, @bit
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

; bus_tksa: A = secondary address. Then the bus is turned around: the device
; talks and we listen. The result is in ST only (bit 7 no device, bit 1 the
; turnaround timed out).
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
        jsr dly             ; (leaves X = 0)
        lda #3              ; the wait's counters are set before the release:
        sta io_n            ; nothing may come between it and the first poll
        ldy #0
        lda #A_DAT          ; ATN off, CLK released, DATA low, all in one write: we
        jsr io_set          ; are the listener from this instant. Any pause here
                            ; hides the device's short clock pulse behind our own
@w:     bit PORT            ; the device takes over the clock: CLK goes low. It
        tb bvc, @ok         ; may be finishing a command first; it has answered
        dex                 ; both bytes, so wait long (about 2 s, interrupts
        tb bne, @w          ; stay off: a pause here can hide the device's short
        dey                 ; clock pulse, and the wait is bounded now). If the
        tb bne, @w          ; pulse was missed the device is already waiting
        dec io_n            ; to send: ST bit 1, and the caller UNTALKs and asks
        tb bne, @w          ; again
        lda ST
        ora #$02
        sta ST
@ok:
@r:     plp                 ; the caller reads ST (plp would undo any carry)
        rts

; ---------------------------------------------------------------------
; channel level, continued (after the timed code, so it does not move it)

; iec_out_byte: A = byte. X and Y are preserved.
iec_out_byte:
        stx io_sx
        sty io_sy
        jsr bus_ciout
        ldx io_sx
        ldy io_sy
        rts

; iec_out_end: the last byte goes with EOI, then UNLISTEN. Carry set (A = EIO)
; if a byte was not accepted. The drive keeps what did arrive: on channel 15 a
; half command, which the 1541 would prefix to the next one ("U2" and then
; "U1:2 0 t s" is a U2 to t/s). So the drive is marked, and the next LISTEN to
; it flushes first (io_flush). An UNLISTEN nobody answered (ST bit 7; the
; LISTEN was answered, or the caller would not be here) is not a failure on a
; data channel: every byte arrived, and a caller that retried would send them
; twice (cbm_write). On channel 15 it is: the drive runs a command at UNLISTEN,
; so it may not have run it, and the status read would answer for the one before.
iec_out_end:
        jsr bus_unlsn
        lda ie_sa
        cmp #15             ; carry set: the command channel
        lda ST
        and #$83
        bcs @t
        and #$03
@t:     beq @ok
        jsr io_drv
        lda #1
        sta io_dirty,x
        lda #EIO
        sec
        rts
@ok:    clc
        rts

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

; io_flush: if a send to ie_dev failed part way, send its command channel 42
; spaces with EOI. The 1541 holds 42 bytes and drops the rest (CFDF); at the
; EOI it finds a command of 42 and answers 32, SYNTAX ERROR, without parsing
; it (C2CE), and empties the buffer (E645). A lone CR would run the half
; command instead. Carry set if this fails: A = EIO if a space was not taken,
; ENODEV if the LISTEN or secondary was not (ST bit 7: the drive is gone, or
; it missed one frame ack, so out_sa tries again). The mark stays either way, so
; nothing else is sent to channel 15 until a flush gets through (a command
; appended to a half one could be "S:*" + "i0").
io_flush:
        jsr io_drv
        lda io_dirty,x
        beq @ok
        lda #0
        sta ST
        lda ie_dev
        jsr bus_listen
        lda #$6f            ; data, channel 15
        jsr bus_second
        lda ST
        bmi @nd             ; not taken: the mark stays
        ldy #42
@l:     lda #' '
        jsr iec_out_byte
        dey
        bne @l
        jsr iec_out_end     ; failed: EIO, and the mark stays
        bcs @r
        jsr io_drv
        lda #0
        sta io_dirty,x
@ok:    clc
@r:     rts
@nd:    jmp io_nodev

io_drv: lda ie_dev
        and #3
        tax
        rts


