; fast.km: fast block transfer with a stock 1541 (no JiffyDOS ROM in the drive needed).
;
; The module uploads a small program into the drive's RAM and from then on moves each
; c64fs block (bread, bwrite) with it: the drive reads or writes the sector with its own
; job queue and the 256 bytes cross the bus two bits at a time, by the clock, using the
; kernel's JiffyDOS byte routines on this side (src/kernel/iec.s: jif_rx, jif_tx). The
; drive's ROM is not involved in the transfer, so its type does not matter, as long as it
; is a 1541. Every block carries a checksum, and anything that goes wrong (a job error, a
; timeout, a bad checksum, a drive that does not answer) falls back to the kernel's own
; path (U1/U2 with its retries) for that block. Needs a kernel built with JIFFY=1.
;
; Source and licence. Our own work. The byte framing follows Michael Steil's public
; description of the JiffyDOS protocol, "Commodore Peripheral Bus, Part 7: JiffyDOS"
; (github.com/mist64/cbmbus_doc), because the kernel's routines speak it; the drive side
; here is written from that description and from public documentation of the 1541 (its
; VIA port at $1800, the job queue at $00-$04 with the headers at $06 and up, the
; M-R/M-W/M-E commands). No JiffyDOS ROM code, no drive ROM code and no other loader was
; read or copied. See docs/design/fast-io.md.
;
; How it hooks in (no resident bytes): init points three call sites in src/kernel/blk.s
; at this module: bread_io (jsr iec_read), bwrite_io (jsr iec_write) and iclose_io (the
; jmp iec_ch_close that closes a drive's command channel, which frees every buffer in the
; drive: our program is gone then). fini puts them back.
;
; Drive memory. The kernel's own "#" channel (secondary 2) owns one drive buffer; install
; checks that it is buffer 2 ($0500: what a stock 1541 gives the first "#"), and the drive
; code uses that buffer and its job slot ($02, header $0A/$0B) for the sector. The code
; lives in buffers 0 and 1 ($0300-$04FF), reserved with "#0" and "#1" on secondaries 4 and
; 5 so the drive's DOS leaves them alone. One buffer stays free. Only drives whose mount is c64fs are touched:
; a CBM DOS disk needs the buffers for its files.
;
; One block: "M-E" lo hi op track sector (the drive runs the code once and returns to its
; DOS, so every other command still works in between), then
;   drive: CLK low ("running")          host: DATA low ("seen")
;   read:  drive runs the job, then sends status (1 = good), 256 bytes, the checksum
;   write: drive DATA low and CLK released; host CLK low; host sends 256 bytes and the
;          checksum; drive runs the job (the write and a verify), CLK low and DATA
;          released ("done"); host DATA low; drive sends status
; ATN at any point makes the drive code leave (that is how the fallback gets through).
;
; Limits, on purpose: a drive that is switched off and on while mounted has lost the
; program (and the kernel's own channel); a block then costs a timeout before the standard
; path fails too. A direct job does not notice a changed disk by itself: the header ID
; no longer matches, the job fails and the fallback (the DOS) sorts it out. The timing
; has been proven in emulation only (docs/design/fast-io.md has the margins).
.include "../kernel/k.inc"
.include "kexp.inc"

PORT    = $dd00
A_CLK   = $10
A_DAT   = $20

DRV     = $0300         ; where the drive code runs (buffers 0 and 1)
DBUF    = $0500         ; buffer 2, the kernel's own "#" buffer: the sector
D2      = $078a         ; the rest of the drive code
RB2     = DBUF + 325    ; the second raw sector of a pass (to $078A: the rest of buffer 3 and 4, and the BAM's)
PB      = $1800         ; the drive's serial port (VIA 1 port B)
OP_RD   = $80           ; the job codes
OP_WR   = $90
OP_VFY  = $a0
CHUNK   = 32            ; drive code bytes per M-W

.segment "HEADER"
        jmp init
        jmp fini
        .word KAPI_HASH
        .byte $30               ; class 0: generic; high nibble = name id for `mod ls` (the table is in src/bin/mod.s)

.segment "BSS"
state:  .res 4          ; per drive (number & 3): 0 not tried, 1-3 active (fails in a row + 1), $80 not usable
ft_i:    .res 1          ; the drive's index into state
sv_p4:  .res 2
sv_jif: .res 1
sv_y:   .res 1
ft_ck:   .res 1          ; checksum
ft_n:    .res 1
wmask:  .res 1
wn:     .res 1
mrb:    .res 2          ; M-R answer
up:     .res 2          ; upload: drive address
up2:    .res 1
rawbuf: .res 325        ; EXPERIMENT: a block as the drive read it off the disk
g_t:    .res 5
g_o:    .res 4
g_c:    .res 1
g_e:    .res 1
g_cs:   .res 1
g_h:    .res 1
g_x:    .res 1
ft_pt:  .res 1          ; the last block's track and sector (for hint)
ft_ps:  .res 1
ft_s1:  .res 1          ; the stride of the last request on this track
ft_nf:  .res 1          ; blocks that fell back to the standard path (tests/test_fast.py reads both)
ft_ng:  .res 2          ; blocks carried

.segment "CODE"
; init is refused unless the kernel is loading the module (as cbm.km), and when the call
; sites are not the kernel's own (a second copy).
init:   lda mod_busy
        beq @no
        lda bread_io+1
        cmp #<iec_read
        bne @no
        lda bread_io+2
        cmp #>iec_read
        bne @no
        php
        sei
        lda #<ft_read
        sta bread_io+1
        lda #>ft_read
        sta bread_io+2
        lda #<ft_write
        sta bwrite_io+1
        lda #>ft_write
        sta bwrite_io+2
        lda #<ft_close
        sta iclose_io+1
        lda #>ft_close
        sta iclose_io+2
        plp
        clc
        rts
@no:    lda #EBUSY
        sec
        rts

; fini: the call sites back, and the drive buffers of every active drive given back.
fini:   php
        sei
        lda #<iec_read
        sta bread_io+1
        lda #>iec_read
        sta bread_io+2
        lda #<iec_write
        sta bwrite_io+1
        lda #>iec_write
        sta bwrite_io+2
        lda #<iec_ch_close
        sta iclose_io+1
        lda #>iec_ch_close
        sta iclose_io+2
        plp
        ldx #3
@l:     stx ft_i
        lda state,x
        beq @n
        bmi @n
        txa
        ora #8
        jsr unreserve
@n:     ldx ft_i
        dex
        bpl @l
        clc
        rts

; unreserve: A = drive number. Close the two code buffers' channels.
unreserve:
        pha
        ldx #4
        jsr iec_ch_close
        pla
        ldx #5
        jmp iec_ch_close

; ft_close: in place of the jmp iec_ch_close that closes a drive's command channel
; (A = drive, X = 15): the drive frees every buffer, so the program has to go up again.
ft_close:
        pha
        and #3
        tay
        lda #0
        sta state,y
        pla
        jmp iec_ch_close

; ft_ready: may this block go the fast way? Carry clear if so. Only a mounted c64fs drive
; (the probe reads of a mount, and CBM DOS disks, take the standard path), and only once
; the drive has taken the program.
ft_ready:
        ldx rq_dev
        lda dev_present,x
        beq @no
        lda dev_type,x
        cmp #FS_C64
        bne @no
        lda cur_drv
        and #3
        tax
        stx ft_i
        lda state,x
        bmi @no
        bne @yes
        jsr install
        ldx ft_i
        lda state,x
        bmi @no
@yes:   clc
        rts
@no:    sec
        rts

; ft_fail: a block went wrong after the drive had started. Three in a row and the drive is
; left alone until it is mounted again.
ft_fail: jsr ft_done
        inc ft_nf
        ldx ft_i
        inc state,x
        lda state,x
        cmp #4
        bcc ft_rts
ft_dead:
        ldx ft_i
        lda #$80
        sta state,x
ft_rts: rts

; ft_done: let go of the bus, and the session's protocol flag back
ft_done: lda #0
        jsr io_set
        lda sv_jif
        sta io_jif
        rts

; ft_good: a block went through
ft_good: jsr ft_done
        inc ft_ng
        bne @n
        inc ft_ng+1
@n:     ldx ft_i
        lda #1
        sta state,x
        clc
        rts

; ft_start: A = job code. Start the drive code for the block in rq_lo/hi and shake hands.
; Carry set: the bus is idle and the caller takes the standard path (a drive whose code
; did not answer is not asked again until it is mounted again).
ft_start:
        sta cmdbuf+5
        jsr blk_to_ts
        lda trk
        sta cmdbuf+6
        lda sct
        sta cmdbuf+7
        lda #'E'
        jsr mhead
        lda #<d_go
        sta cmdbuf+3
        lda #>d_go
        sta cmdbuf+4
        jsr tcodes              ; cmdbuf+8, 9: the track as the disk spells it
        lda sct
        jsr senc                ; cmdbuf+10, 11: the sector, and byte 3 of its header
        stx cmdbuf+10
        ora cmdbuf+8
        sta cmdbuf+11
        jsr hint                ; cmdbuf+12-14: the pass: how to read, and the guess for the next sector
        lda #15
        sta cmdlen
        jsr cmd_send
        bcs @bus
        ldx #0                  ; the drive code pulls CLK when it runs (within 0.7 s)
        ldy #0
@w:     bit PORT
        bvc @up
        dex
        bne @w
        dey
        bne @w
        jsr ft_dead
        sec
        rts
@up:    lda io_jif              ; from here to ft_done the kernel's byte routines speak the
        sta sv_jif              ; fast protocol, whatever the drive's ROM said
        lda #0
        sta io_jif
        sta ST
        sta ft_ck
        lda #A_DAT              ; seen
        jsr io_set
        clc
        rts
@bus:   sec
        rts

; hint: a stride predictor over pairs. The drive reads two sectors a pass, so a file is laid out
; in pairs and the guess for the block after this one is this sector plus the stride the request
; before this one had (modulo the track): the second of a pair is next to the first, the first of
; the next pair is a pitch away, and a uniform stride predicts itself. c64fs blocks carry no link,
; so the disk cannot say. Only a guess on the same track counts; the drive takes it while the
; host is busy and the next request is served from it if it was right.
hint:   lda #0
        sta cmdbuf+14           ; 0: the DOS reads it (the head may be elsewhere)
        lda ft_pt
        cmp trk
        bne @new
        inc cmdbuf+14           ; 1: the head is on this track: read the sector raw
        jsr h_spt
        sta g_h
        lda sct
        sec
        sbc ft_ps
        bcs @p
        adc g_h                 ; carry clear
@p:     sta g_x                 ; this request's stride
        lda ft_s1
        beq @upd                ; no stride yet
        clc
        adc sct
        cmp g_h
        bcc @ok
        sbc g_h
@ok:    cmp sct
        beq @upd
        pha
        jsr senc
        stx cmdbuf+12
        ora cmdbuf+8
        sta cmdbuf+13
        pla
        inc cmdbuf+14           ; 2: and the guessed one in the same pass
@upd:   lda g_x
        sta ft_s1
        jmp @st
@new:   lda #0
        sta ft_s1
@st:    lda trk
        sta ft_pt
        lda sct
        sta ft_ps
        rts

; senc: A = a sector; X = the low nibble of the header's byte 2 for it, A = the high six bits
; of byte 3 (the GCR codes of its two digits, run together).
senc:   pha
        lsr a
        lsr a
        lsr a
        lsr a
        tax
        lda g_et,x
        sta g_c
        pla
        and #$0f
        tax
        lda g_et,x
        asl a
        asl a
        sta g_e
        lda g_c
        lsr a
        tax
        lda #0
        ror a
        ora g_e
        rts

; h_spt: A = the sectors on track trk (1541)
h_spt:  lda #21
        ldy trk
        cpy #18
        bcc @r
        lda #19
        cpy #25
        bcc @r
        lda #18
        cpy #31
        bcc @r
        lda #17
@r:     rts

; tcodes: cmdbuf+8, 9 from trk. c6, c7 = the GCR codes of its two digits; T3 = c6>>3,
; T4 = c6<<5 | c7 (the header's last two bytes).
tcodes: lda trk
        lsr a
        lsr a
        lsr a
        lsr a
        tax
        lda g_et,x
        sta g_c                 ; c6
        lda trk
        and #$0f
        tax
        lda g_et,x
        sta g_e                 ; c7
        lda g_c
        lsr a
        lsr a
        lsr a
        sta cmdbuf+8
        lda g_c
        asl a
        asl a
        asl a
        asl a
        asl a
        ora g_e
        sta cmdbuf+9
        rts

; mhead: "M-" and A into cmdbuf
mhead:  sta cmdbuf+2
        lda #'M'
        sta cmdbuf
        lda #'-'
        sta cmdbuf+1
        rts

; wait for CLK (w_clk) or DATA (w_dat) to be released, interrupts on, up to about 12 s (a
; spin-up, a seek across the disk and the job's own retries). Carry set if it never is.
w_clk:  lda #$40
        .byte $2c               ; bit abs: skip the next instruction
w_dat:  lda #$80
        sta wmask
        php
        cli
        lda #12
        sta wn
        ldx #0
        ldy #0
@w:     lda PORT
        and wmask
        bne @ok
        dex
        bne @w
        dey
        bne @w
        dec wn
        bne @w
        plp
        sec
        rts
@ok:    plp
        clc
        rts

; cksum: ft_ck = (ft_ck rotated left) + A. A is preserved. (The drive code has the same.)
cksum:  pha
        lda ft_ck
        asl a
        adc #0
        sta ft_ck
        pla
        pha
        clc
        adc ft_ck
        sta ft_ck
        pla
        rts

; ft_read: in place of iec_read (cur_drv, rq_dev, rq_lo/hi, bp as there)
ft_read: jsr ft_ready
        bcs @std
        lda #OP_RD
        jsr ft_start
        bcs @std
        jsr w_clk               ; the job is done when the drive lets go of CLK
        bcs @bad
        jsr iec_in_byte         ; its result: 1 a block, 2 a block as it is on the disk
        cmp #2
        beq @raw
        cmp #1
        bne @bad
        ldy #0
@l:     jsr iec_in_byte
        sta (bp),y
        jsr cksum
        lda ST
        and #$02
        bne @bad
        iny
        bne @l
        jsr iec_in_byte
        cmp ft_ck
        bne @bad
        lda ST
        and #$02
        bne @bad
        jmp ft_good
@bad:   jsr ft_fail
@std:   jmp iec_read
@raw:   ldy #0
@r:     jsr iec_in_byte
        sta rawbuf,y
        jsr cksum
        lda ST
        and #$02
        bne @rb
        iny
        bne @r
@s:     jsr iec_in_byte
        sta rawbuf+256,y
        jsr cksum
        lda ST
        and #$02
        bne @rb
        iny
        cpy #69
        bne @s
        jsr iec_in_byte
        cmp ft_ck
        bne @rb
        lda ST
        and #$02
        bne @rb
        jsr hdec
        cmp #1
        bne @rb
        ldy #0
@c:     lda rawbuf+1,y
        sta (bp),y
        iny
        bne @c
        jmp ft_good
@rb:    jmp @bad

; hdec: the 325 bytes in rawbuf, as GCR, become the block's 260 bytes in place (the marker, the
; 256 data bytes from rawbuf+1, the checksum). A = 1 if every code was good, the marker is 7 and
; the checksum holds, else 0.
.macro hi_into dest
        jsr g_nib
        asl a
        asl a
        asl a
        asl a
        sta dest
.endmacro
.macro lo_into dest
        jsr g_nib
        ora dest
        sta dest
.endmacro
.macro getg base
        lda base,x
        sta g_t
        lda base+1,x
        sta g_t+1
        lda base+2,x
        sta g_t+2
        lda base+3,x
        sta g_t+3
        lda base+4,x
        sta g_t+4
.endmacro
.macro putg base
        lda g_o
        sta base,y
        eor g_cs
        sta g_cs
        lda g_o+1
        sta base+1,y
        eor g_cs
        sta g_cs
        lda g_o+2
        sta base+2,y
        eor g_cs
        sta g_cs
        lda g_o+3
        sta base+3,y
        eor g_cs
        sta g_cs
.endmacro
hdec:   lda #0
        sta g_e
        sta g_cs
        tax
        tay
@g1:    getg rawbuf
        stx g_x                 ; (g_nib uses X)
        jsr g_g
        ldx g_x
        putg rawbuf
        iny
        iny
        iny
        iny
        txa
        clc
        adc #5
        tax
        bcc @g1                 ; 52 groups: X wraps after the one that reads rawbuf+255..259
@g2:    getg rawbuf+256
        stx g_x
        jsr g_g
        ldx g_x
        putg rawbuf
        tya
        clc
        adc #4
        tay
        txa
        clc
        adc #5
        tax
        tya
        bne @g2                 ; 12 more: Y wraps to 0
        getg rawbuf+256
        stx g_x                 ; (g_nib uses X)
        jsr g_g
        ldx g_x
        putg rawbuf+256
        lda g_e
        bne @bad
        lda rawbuf
        cmp #7
        bne @bad
        lda g_cs
        cmp #7
        bne @bad
        lda #1
        rts
@bad:   lda #0
        rts

; g_nib: A = a 5-bit code. Returns the nibble; g_e is set if it was not a code. Uses X.
g_nib:  tax
        lda g_dt,x
        cmp #16
        bcc @r
        sta g_e
@r:     rts

; g_g: the five GCR bytes in g_t decode to the four bytes in g_o.
g_g:    lda g_t
        lsr a
        lsr a
        lsr a
        hi_into g_o             ; c0
        lda g_t+1
        asl a
        rol a
        rol a
        and #$03
        sta g_c
        lda g_t
        asl a
        asl a
        and #$1c
        ora g_c
        lo_into g_o             ; c1
        lda g_t+1
        lsr a
        and #$1f
        hi_into g_o+1           ; c2
        lda g_t+1
        asl a
        asl a
        asl a
        asl a
        and #$10
        sta g_c
        lda g_t+2
        lsr a
        lsr a
        lsr a
        lsr a
        ora g_c
        lo_into g_o+1           ; c3
        lda g_t+3
        asl a
        lda g_t+2
        rol a
        and #$1f
        hi_into g_o+2           ; c4
        lda g_t+3
        lsr a
        lsr a
        and #$1f
        lo_into g_o+2           ; c5
        lda g_t+4
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        sta g_c
        lda g_t+3
        asl a
        asl a
        asl a
        and #$18
        ora g_c
        hi_into g_o+3           ; c6
        lda g_t+4
        and #$1f
        lo_into g_o+3           ; c7
        rts

; GCR: the 5-bit code of each nibble, and the nibble of each code ($ff: not a code)
g_et:   .byte $0a,$0b,$12,$13,$0e,$0f,$16,$17,$09,$19,$1a,$1b,$0d,$1d,$1e,$15
g_dt:   .byte $ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$ff,$08,$00,$01,$ff,$0c,$04,$05,$ff,$ff,$02,$03,$ff,$0f,$06,$07,$ff,$09,$0a,$0b,$ff,$0d,$0e,$ff

; ft_write: in place of iec_write
ft_write:
        jsr ft_ready
        bcs @std
        lda #OP_WR
        jsr ft_start
        bcs @std
        jsr w_clk               ; the drive holds DATA and has let go of CLK: it listens
        bcs @bad
        lda #A_CLK
        jsr io_set
        lda #0
        sta io_eoi
        ldy #0
@l:     lda (bp),y
        jsr cksum
        jsr txb
        bcs @bad
        iny
        bne @l
        lda ft_ck
        jsr txb
        bcs @bad
        jsr w_dat               ; the write and the verify are done when it lets go of DATA
        bcs @bad
        lda #A_DAT
        jsr io_set
        jsr iec_in_byte         ; the result
        cmp #1
        bne @bad
        lda ST
        and #$02
        bne @bad
        jmp ft_good
@bad:   jsr ft_fail
@std:   jmp iec_write

; txb: send A to the drive code. Y is preserved; carry set if it was not taken.
txb:    sty sv_y
        php
        sei
        jsr io_txd
        bcs @f
        plp
        ldy sv_y
        clc
        rts
@f:     plp
        ldy sv_y
        sec
        rts

; ---------------------------------------------------------------------
; install: put the program into the drive in cur_drv. Sets state[ft_i] to 1, or to $80
; when this drive cannot take it (not a 1541, its buffers are not where we expect them,
; or the bus failed on the way).
install:
        lda p4
        sta sv_p4
        lda p4+1
        sta sv_p4+1
        jsr ft_dead             ; until proven otherwise
        jsr probe
        bcs @out
        jsr upload
        bcs @out
        ldx ft_i
        lda #1
        sta state,x
@out:   lda sv_p4
        sta p4
        lda sv_p4+1
        sta p4+1
        rts

; probe: carry clear if the drive is one we know and its buffers are where we expect them
probe:  ldx #$fe                ; a 1541? Its ROM ends in the IRQ vector $FE67. (A 1581's
        lda #$ff                ; port is elsewhere: it must never get this code.)
        ldy #2
        jsr mr
        bcs @no
        lda mrb
        cmp #$67
        bne @no
        lda mrb+1
        cmp #$fe
        bne @no
        ldx #$2d                ; the kernel's channel (secondary 2): its entry in the
        lda #$02                ; drive's channel table at $022B...
        ldy #1
        jsr mr
        bcs @no
        lda mrb
        cmp #$ff                ; none: nothing here is as we expect
        beq @no
        and #$0f
        clc
        adc #$a7                ; ... names the slot whose buffer number is at $A7
        tax
        lda #0
        ldy #1
        jsr mr
        bcs @no
        lda mrb                 ; buffer 2, or we stay out
        cmp #2
        bne @no
        clc
        rts
@no:    sec
        rts

; upload: reserve buffers 0 and 1 and fill them. Carry set if the drive did not take it
; all (the buffers are given back).
upload: lda #'0'
        ldx #4
        jsr reserve
        bcc :+
        jmp @cl
:       lda #'1'
        ldx #5
        jsr reserve
        bcc :+
        jmp @cl
:       lda #<blob
        sta p4
        lda #>blob
        sta p4+1
        lda #<DRV
        sta up
        lda #>DRV
        sta up+1
        lda #BLOBLEN / CHUNK
        sta ft_n
        lda #0
        sta up2
@ch:    lda #'W'
        jsr mhead
        lda up
        sta cmdbuf+3
        lda up+1
        sta cmdbuf+4
        lda #CHUNK
        sta cmdbuf+5
        ldy #CHUNK-1
@c:     lda (p4),y
        sta cmdbuf+6,y
        dey
        bpl @c
        lda #CHUNK+6
        sta cmdlen
        jsr cmd_send
        bcs @cl
        clc
        lda p4
        adc #CHUNK
        sta p4
        bcc @p
        inc p4+1
@p:     clc
        lda up
        adc #CHUNK
        sta up
        bcc @u
        inc up+1
@u:     dec ft_n
        bne @ch
        lda up2
        bne @done
        inc up2
        lda #<blob2
        sta p4
        lda #>blob2
        sta p4+1
        lda #<D2
        sta up
        lda #>D2
        sta up+1
        lda #BLOB2LEN / CHUNK
        sta ft_n
        jmp @ch
@done:  jsr cmd_status          ; the drive took every command
        bcs @cl
        rts
@cl:    lda cur_drv
        jsr unreserve
        sec
        rts

; reserve: A = buffer digit, X = secondary. Open "#n" there and see that the drive agreed.
reserve:
        sta rname+1
        lda #<rname
        sta p4
        lda #>rname
        sta p4+1
        ldy #2
        lda cur_drv
        jsr iec_ch_open
        bcs @r
        jmp cmd_status
@r:     rts

; mr: read Y (1 or 2) bytes of drive memory at A:X (hi:lo) into mrb. Carry set if the bus failed.
mr:     stx cmdbuf+3
        sta cmdbuf+4
        sty cmdbuf+5
        sty ft_n
        lda #'R'
        jsr mhead
        lda #6
        sta cmdlen
        jsr cmd_send
        bcs @r
        lda cur_drv
        ldx #15
        jsr iec_in_begin
        bcs @r
        ldy #0
@l:     jsr iec_in_byte
        sta mrb,y
        iny
        cpy ft_n
        bne @l
        lda ST
        pha
        jsr iec_in_end
        pla
        and #$02
        cmp #1                  ; carry set if a byte timed out
@r:     rts

.segment "DATA"
rname:  .byte "#1"

; ---------------------------------------------------------------------
; The drive code. Assembled for DRV ($0300) in the drive; it is data here.
;
; The cycle counts in the two timed routines are from the read of PB that sees the host's
; "go" (the last cycle of the cmp). That read comes 0 to 7 cycles after the line moved,
; so each of our port accesses happens in a window that wide. tools/test_fast_timing.py
; checks the counts against the tables below; the schedule can be shifted for margin
; tests with -D (make MODFLAGS=...).
.ifndef SK1
SK1 = 6                 ; send: the writes of the four bit pairs and of "no EOI, busy"
.endif
.ifndef SK2
SK2 = 17
.endif
.ifndef SK3
SK3 = 27
.endif
.ifndef SK4
SK4 = 38
.endif
.ifndef SK5
SK5 = 49
.endif
.ifndef RK1
RK1 = 13                ; receive: the four reads, and the acknowledge
.endif
.ifndef RK2
RK2 = 26
.endif
.ifndef RK3
RK3 = 37
.endif
.ifndef RK4
RK4 = 50
.endif
RK5 = 62
.ifndef VERIFY
VERIFY = 1              ; a verify job of our own after the write job
.endif
.ifndef WR
WR = 0                  ; EXPERIMENT: the write path is out while the raw reader is tried
.endif

.macro wait n           ; spend n cycles (0, or 2 and up); A, X, Y and the stack are kept
        .assert (n) = 0 .or (n) >= 2, error, "fast.s: a wait of one cycle"
        .if (n) & 1
        bit $00
        .repeat ((n) - 3) / 2
        nop
        .endrepeat
        .else
        .repeat (n) / 2
        nop
        .endrepeat
        .endif
.endmacro
.macro tbr op, dest     ; a branch in a timed loop: taken, it must cost 3 cycles
        op dest
        .assert >* = >(dest), error, "fast.s: a timed branch crosses a page"
.endmacro

.segment "RODATA"
blob:
.org DRV
; (the timed routines and their tables first: they must not cross a page)
; d_send: A = byte. A line is released for a 1 (the host reads the levels). Uses A, X.
; The host has DATA low and we have CLK low; we release CLK when ready, the host releases
; DATA ("go") and reads the pairs at its cycles 16, 26, 37, 48 and the status at 59.
d_send: pha
        lsr a
        lsr a
        lsr a
        lsr a
        tax
        lda d_stab,x
        sta d_s2+1              ; bits 4, 5
        asl a
        and #$0f
        sta d_s3+1              ; bits 6, 7
        pla
        and #$0f
        tax
        lda d_stab,x
        tax                     ; X: bits 0, 1
        asl a
        and #$0f
        sta d_s1+1              ; bits 2, 3
        lda #0
        sta PB                  ; ready
        lda d_exps
        nop                     ; (time for CLK to rise)
        nop
d_sw:   cmp PB                  ; go?                               cycle 0
        tbr beq, d_sw
        wait SK1 - 6
        stx PB                  ;                                   SK1
d_s1:   lda #0
        wait SK2 - SK1 - 6
        sta PB                  ;                                   SK2
d_s2:   lda #0
        wait SK3 - SK2 - 6
        sta PB                  ;                                   SK3
d_s3:   lda #0
        wait SK4 - SK3 - 6
        sta PB                  ;                                   SK4
        lda #$08
        wait SK5 - SK4 - 6
        sta PB                  ; no EOI, and busy: CLK low         SK5
d_send_end:
        bit PB
        bmi d_quit2
        rts

.if WR
; d_recv: returns the byte in A. Uses A, X. A line is low for a 1.
; The host has CLK low and we have DATA low; we release DATA when ready, the host
; releases CLK ("go") and writes the pairs at its cycles 11, 24, 35, 48 and "more" at 61.
d_recv: lda #0
        sta PB                  ; ready
        lda d_expr
        nop                     ; (time for DATA to rise)
        nop
d_rw:   cmp PB                  ; go?                               cycle 0
        tbr beq, d_rw
        wait RK1 - 6
        lda PB                  ; bits 4, 5 on CLK, DATA            RK1
        asl a
        wait RK2 - RK1 - 6
        ora PB                  ; bits 6, 7                         RK2
        and #$0f
        tax
        wait RK3 - RK2 - 8
        lda PB                  ; bits 3, 1                         RK3
        asl a
        wait RK4 - RK3 - 6
        ora PB                  ; bits 2, 0                         RK4
        and #$0f
        ora d_rtab,x
        ldx #$02
        stx PB                  ; taken: DATA low                   RK5
d_recv_end:
        bit PB
        bmi d_quit2
        rts
.endif
d_quit2:
        jmp d_quit

; d_stab: for a nibble, what to put on the port for its bits 0 and 1 (CLK, DATA); shifted
; left once it is bits 2 and 3. A 0 bit pulls the line (port bits 3 and 1).
d_stab:
.repeat 16, n
        .byte ((~n & 1) << 3) | ((~n & 4) << 0) | ((~n & 2) << 0) | ((~n & 8) >> 3)
.endrepeat
.if WR
; d_rtab: the high nibble from the first two reads (bit 3: 4, bit 2: 6, bit 1: 5, bit 0: 7)
d_rtab:
.repeat 16, n
        .byte ((n & 8) << 1) | ((n & 4) << 4) | ((n & 2) << 4) | ((n & 1) << 7)
.endrepeat
.assert >d_stab = >(d_stab + 15), error, "fast.s: d_stab crosses a page"
.assert >d_rtab = >(d_rtab + 15), error, "fast.s: d_rtab crosses a page"
.endif
.assert >d_sw = >d_send_end, error, "fast.s: the timed part of d_send crosses a page"
.if WR
.assert >d_rw = >d_recv_end, error, "fast.s: the timed part of d_recv crosses a page"
.endif


; d_go: the entry (M-E). The command: op, track, sector, T3 T4 (the track as the header spells
; it), e2 e3 (the sector), e2 e3 of the sector to take in the same pass, and how: 0 the DOS reads
; it into DBUF, 1 raw, 2 raw and the second sector too. A raw block goes out as it is on the disk
; (status 2, 325 bytes); the second one waits in RB2 for the next request.
d_go:   sei
        tsx
        stx d_sp
        lda PB                  ; the device number jumpers read back in bits 5 and 6
        and #$60
        ora #$01
        sta d_exps              ; the port as send waits: host DATA low, nothing else
        lda #$08
        sta PB                  ; running: CLK low
@s:     lda PB                  ; the host pulls DATA: seen
        bmi d_quit2
        lsr a
        bcc @s
        lda $0206               ; track and sector from the command
        sta $0a
        lda $0207
        sta $0b
        ldy #0
        sty d_ck
        lda $0205
        cmp #OP_RD
        bne d_quit2
        lda d_kt                ; the sector kept from the last pass, if it is the one asked for
        sty d_kt                ; (it is good for one request)
        cmp $0a
        bne @cap
        lda d_k2
        cmp $020a
        bne @cap
        lda d_k3
        cmp $020b
        bne @cap
        inc d_nh
        lda #<RB2
        ldx #>RB2
        jsr d_setp
        lda #2
        bne @go
@cap:   lda #<DBUF
        ldx #>DBUF
        jsr d_setp
        lda $020e
        beq @job
        lda $020a
        sta d_e2
        lda $020b
        sta d_e3
        jsr d_cap
        bcs @job
        lda $020e
        cmp #2
        bne @raw
        lda #<RB2
        ldx #>RB2
        jsr d_setp
        lda $020c
        sta d_e2
        lda $020d
        sta d_e3
        jsr d_cap
        bcs @none
        lda $0a
        sta d_kt
        lda $020c
        sta d_k2
        lda $020d
        sta d_k3
        jmp @raw
@none:  inc d_nm
@raw:   lda #<DBUF
        ldx #>DBUF
        jsr d_setp
        lda #2
        bne @go
@job:   lda #OP_RD
        jsr d_job
@go:    sta d_st
        ldy #0
        jsr d_send
        lda d_st
        cmp #1
        beq d_lp
        cmp #2
        beq d_lp
        jmp d_quit
d_lp:
d_l1:   lda DBUF,y
        jsr d_cksum
        jsr d_send
        iny
        bne d_l1
        lda d_st
        cmp #2
        bne d_ck2
d_l2:   lda DBUF+256,y
        jsr d_cksum
        jsr d_send
        iny
        cpy #69
        bne d_l2
d_ck2:  lda d_ck
        jsr d_send
d_quit: ldx d_sp
        txs
        lda #0
        sta PB
        cli
        rts                     ; back into the DOS

; d_job: A = job code for buffer 2. Returns its result (1 = good). The disk controller
; runs in the drive's interrupt.
d_job:  sta $02
        cli
@w:     bit PB
        bmi d_quit
        lda $02
        bmi @w
        sei
        rts

; d_cap: take the block whose header holds d_e2/d_e3 and the track's T3/T4, raw (325 bytes), to
; where d_setp said. Carry set if it did not come by in two revolutions.
d_cap:  lda #48
        sta d_try
@h:     jsr d_sync
        bcs @f
        ldy #0
@hb:    bvc @hb
        clv
        lda $1c01
        sta d_hd,y
        iny
        cpy #5
        bne @hb
        lda d_hd
        cmp #$52
        bne @n
        lda d_hd+2
        and #$0f
        cmp d_e2
        bne @n
        lda d_hd+3
        cmp d_e3
        bne @n
        lda d_hd+4
        cmp $0209
        beq @hit
@n:     dec d_try
        bne @h
@f:     sec
        rts
@hit:   jsr d_sync
        bcs @f
        ldy #0
d_d1:   bvc d_d1
        clv
        lda $1c01
d_c1:   sta DBUF,y
        iny
        bne d_d1
d_d2:   bvc d_d2
        clv
        lda $1c01
d_c2:   sta DBUF+256,y
        iny
        cpy #69
        bne d_d2
        clc
        rts


d_st:   .res 1
d_kt:   .res 1          ; the track, and the header bytes, of the sector kept in RB2 (0: none)
d_k2:   .res 1
d_k3:   .res 1
d_e2:   .res 1
d_e3:   .res 1
d_try:  .res 1
d_hd:   .res 5
d_nh:   .res 1          ; (counters) sectors served from RB2, passes whose second sector missed
d_nm:   .res 1
d_sp:   .res 1
d_ck:   .res 1
d_exps: .res 1

        .res (CHUNK - ((* - DRV) .mod CHUNK)) .mod CHUNK, 0
d_end:
.reloc
BLOBLEN = d_end - DRV
.assert BLOBLEN <= $200, error, "fast.s: the drive code outgrew two buffers"

; ---------------------------------------------------------------------------------------
; The rest of the drive code, above the two raw sectors (D2, the end of the BAM buffer)
.segment "RODATA"
blob2:
.org D2
.macro atn
        bit PB
        bpl :+
        jmp d_quit
:
.endmacro

; d_setp: A, X = lo, hi of where the raw sector goes (and is sent from)
d_setp: sta d_c1+1
        sta d_l1+1
        sta d_c2+1
        sta d_l2+1
        stx d_c1+2
        stx d_l1+2
        inx
        stx d_c2+2
        stx d_l2+2
        rts

; d_cksum: as cksum above
d_cksum:
        pha
        lda d_ck
        asl a
        adc #0
        sta d_ck
        pla
        pha
        clc
        adc d_ck
        sta d_ck
        pla
        rts

; d_sync: wait for sync and read the first byte as the DOS does ($F556). Carry set: none in
; about 0.35 s. ATN leaves.
d_sync: lda #$ee
        sta $1c0c               ; read mode, byte-ready to V
        ldx #0
        ldy #$70
@l:     bit $1c00
        bpl @ok
        dex
        bne @l
        atn
        dey
        bne @l
        sec
        rts
@ok:    lda $1c01
        clv
        clc
        rts

        .res (CHUNK - ((* - D2) .mod CHUNK)) .mod CHUNK, 0
d_end2:
.reloc
BLOB2LEN = d_end2 - D2
.assert BLOB2LEN <= 96, error, "fast.s: the second drive blob outgrew its room"
