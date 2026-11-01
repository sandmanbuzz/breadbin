; Breadbin block devices and buffer cache
;
; dev 0: 1541 on IEC device 8, raw 256-byte sectors via "U1"/"U2"/"B-P"
; dev 1: REU RAM disk (block b = REU bank b>>8, page b&$ff)
; dev 2-4: drives 9-11 (mounted with mount()), same sector commands
; Cache is write-through: bwrite writes the buffer to its device at once.
.include "k.inc"


REU_STATUS = $df00
REU_CMD    = $df01
REU_C64LO  = $df02
REU_C64HI  = $df03
REU_LO     = $df04
REU_HI     = $df05
REU_BANK   = $df06
REU_LENLO  = $df07
REU_LENHI  = $df08
REU_CTRL   = $df0a

.segment "ZEROPAGE"
bp:      .res 2         ; pointer to the buffer returned by bread
.exportzp bp

.segment "BSS"
bufs:    .res NBUF*256
b_valid: .res NBUF
b_dev:   .res NBUF
b_lo:    .res NBUF
b_hi:    .res NBUF
b_age:   .res NBUF
b_clock: .res 1
b_idx:   .res 1
rq_dev:  .res 1
rq_lo:   .res 1
rq_hi:   .res 1
trk:     .res 1
sct:     .res 1
reu_banks: .res 1
dev_present: .res NDEV
dev_type: .res NDEV
cur_drv: .res 1          ; drive number the IEC routines below talk to
dev_drive: .res NDEV    ; drive number of each device (0 = the boot drive)
cmdbuf:  .res 40
cmdlen:  .res 1
rd_try:  .res 1
reu_tmp: .res 1

.export bwrite, buf_idx_ptr

.segment "RODATA"
; first linear block of each track (tracks 1..36), 16-bit
trk_lo: .lobytes 0,21,42,63,84,105,126,147,168,189,210,231,252,273,294,315,336,357,376,395,414,433,452,471,490,508,526,544,562,580,598,615,632,649,666,683
trk_hi: .hibytes 0,21,42,63,84,105,126,147,168,189,210,231,252,273,294,315,336,357,376,395,414,433,452,471,490,508,526,544,562,580,598,615,632,649,666,683
s_hash: .byte "#"
s_init: .byte "i0"

.segment "CODE"
blk_init:
        ldx #NBUF-1
        lda #0
@l:     sta b_valid,x
        dex
        bpl @l
        ; the root disk is on the drive we were booted from: the KERNAL leaves
        ; its number in $BA (stock "current device"). Drives 9-11 are for mount.
        lda $ba
        cmp #8
        bcc @bd
        cmp #12
        bcc @bk
@bd:    lda #8
@bk:    sta dev_drive
        lda #0
        sta dev_drive+1
        lda #9
        sta dev_drive+2
        lda #10
        sta dev_drive+3
        lda #11
        sta dev_drive+4
        ldx #0
        jsr iec_open
        lda #1
        sta dev_present
        jmp reu_detect

; iec_open: X = dev. Open the drive's command channel (15) and a data channel
; (2) with a drive buffer. Carry set (A = ENODEV) if the drive is not there.
iec_open:
        stx tmp2
        lda #<s_init
        sta p4
        lda #>s_init
        sta p4+1
        ldy #2
        lda dev_drive,x
        ldx #15
        jsr iec_ch_open
        bcs @nodev
        lda #<s_hash
        sta p4
        lda #>s_hash
        sta p4+1
        ldy #1
        ldx tmp2
        lda dev_drive,x
        ldx #2
        jsr iec_ch_open
        bcs @nodev
        clc
        rts
@nodev: ldx tmp2
        jsr iec_close
        lda #ENODEV
        sec
        rts

; iec_close: X = dev
iec_close:
        stx tmp2
        lda dev_drive,x
        ldx #2
        jsr iec_ch_close
        ldx tmp2
        lda dev_drive,x
        ldx #15
        jmp iec_ch_close

; cur_dev_set: A = dev -> the drive number the IEC routines below talk to
cur_dev_set:
        tax
        lda dev_drive,x
        sta cur_drv
        rts

; iec_command: A = dev, cmdbuf/cmdlen = command. Sends it and reads the
; drive status; carry clear if it reports 00 or 01.
iec_command:
        jsr cur_dev_set
        jsr cmd_send
        bcs @r
        jmp cmd_status
@r:     rts
.export cmdbuf, cmdlen, iec_status

; iec_status: A = dev -> carry clear if the drive's status is 00 or 01
iec_status:
        jsr cur_dev_set
        jmp cmd_status

; ts_block: A = track, X = sector -> X/Y = linear block number
ts_block:
        stx tmp0
        tay
        dey
        lda trk_lo,y
        clc
        adc tmp0
        tax
        lda trk_hi,y
        adc #0
        tay
        rts

; buf_idx_ptr: X = buffer index -> bp. Preserves X.
buf_idx_ptr:
        lda #<bufs
        sta bp
        txa
        clc
        adc #>bufs
        sta bp+1
        rts

; bread: A = dev, X/Y = block lo/hi -> X = buffer index, bp = data.
; carry set on I/O error (A = EIO).
bread:
        jsr cache_find
        bcs @miss
        rts
@miss:  jsr cache_victim
        lda rq_dev
        cmp #1
        beq @reu
        jsr cur_dev_set
        jsr iec_read
        jmp @chk
@reu:   jsr reu_read
@chk:   ldx b_idx
        bcc @ok
        lda #0
        sta b_valid,x
        lda #EIO
        rts
@ok:    lda #1
        sta b_valid,x
        jsr buf_idx_ptr
        clc
        rts

; bget_buf: like bread, but the block's old contents are not needed:
; returns a zeroed buffer assigned to that block (not written yet).
bget_buf:
        jsr cache_find
        bcc @have
        jsr cache_victim
        ldx b_idx
        lda #1
        sta b_valid,x
        jsr buf_idx_ptr
@have:  ldy #0
        tya
@z:     sta (bp),y
        iny
        bne @z
        clc
        rts

; bwrite: X = buffer index. Write it to its device.
bwrite:
        stx b_idx
        lda b_dev,x
        sta rq_dev
        lda b_lo,x
        sta rq_lo
        lda b_hi,x
        sta rq_hi
        jsr buf_idx_ptr
        lda rq_dev
        cmp #1
        beq @reu
        jsr cur_dev_set
        jsr iec_write
        jmp @r
@reu:   jsr reu_write
@r:     ldx b_idx
        bcc @ok
        lda #EIO
@ok:    rts
bdirty = bwrite

bflush_all:
        rts

; binval: A = dev. Forget its cached blocks (after the drive's own DOS
; changed the disk behind our back).
binval:
        ldx #NBUF-1
        sta tmp0
@l:     lda b_dev,x
        cmp tmp0
        bne @n
        lda #0
        sta b_valid,x
@n:     dex
        bpl @l
        rts

; cache_find: A = dev, X/Y = block. Hit: carry clear, X = idx, bp set.
cache_find:
        sta rq_dev
        stx rq_lo
        sty rq_hi
        inc b_clock
        ldx #NBUF-1
@l:     lda b_valid,x
        beq @n
        lda b_dev,x
        cmp rq_dev
        bne @n
        lda b_lo,x
        cmp rq_lo
        bne @n
        lda b_hi,x
        cmp rq_hi
        bne @n
        lda b_clock
        sta b_age,x
        jsr buf_idx_ptr
        clc
        rts
@n:     dex
        bpl @l
        sec
        rts

; cache_victim: choose a buffer (invalid, else least recently used),
; assign it to rq_*; sets b_idx and bp.
cache_victim:
        ldx #NBUF-1
@inv:   lda b_valid,x
        beq @got
        dex
        bpl @inv
        ; LRU: largest (clock - age)
        lda #0
        sta tmp0
        ldx #NBUF-1
        stx b_idx
@l:     lda b_clock
        sec
        sbc b_age,x
        cmp tmp0
        bcc @n
        sta tmp0
        stx b_idx
@n:     dex
        bpl @l
        ldx b_idx
@got:   stx b_idx
        lda #0
        sta b_valid,x
        lda rq_dev
        sta b_dev,x
        lda rq_lo
        sta b_lo,x
        lda rq_hi
        sta b_hi,x
        lda b_clock
        sta b_age,x
        jmp buf_idx_ptr

; ---- IEC (1541) ----
; rq_lo/hi -> trk/sec
blk_to_ts:
        ldx #34
@l:     lda rq_hi
        cmp trk_hi,x
        bcc @n
        bne @f
        lda rq_lo
        cmp trk_lo,x
        bcs @f
@n:     dex
        bpl @l
        ldx #0
@f:     lda rq_lo
        sec
        sbc trk_lo,x
        sta sct
        inx
        stx trk
        rts

; append decimal A (0-99) to cmdbuf
cmd_num:
        ldx #'0'-1
@t:     inx
        sec
        sbc #10
        bcs @t
        adc #10+'0'
        pha
        txa
        cmp #'0'
        beq @one
        jsr cmd_ch
@one:   pla
        ; fall through
cmd_ch: ldx cmdlen
        sta cmdbuf,x
        inc cmdlen
        rts

; build "U1:2 0 t s" style command; A = command letter digit ('1' or '2')
cmd_us:
        pha
        lda #0
        sta cmdlen
        lda #'U'
        jsr cmd_ch
        pla
        jsr cmd_ch
        lda #':'
        jsr cmd_ch
        lda #'2'
        jsr cmd_ch
        lda #' '
        jsr cmd_ch
        lda #'0'
        jsr cmd_ch
        lda #' '
        jsr cmd_ch
        lda trk
        jsr cmd_num
        lda #' '
        jsr cmd_ch
        lda sct
        jmp cmd_num

; send cmdbuf to the command channel
cmd_send:
        lda cur_drv
        ldx #15
        jsr iec_out_begin
        bcs @e
        ldy #0
@l:     lda cmdbuf,y
        jsr iec_out_byte
        iny
        cpy cmdlen
        bne @l
        jsr iec_out_end
        clc
        rts
@e:     sec
        rts

; read the drive's error channel: carry set unless "00"
cmd_status:
        lda cur_drv
        ldx #15
        jsr iec_in_begin
        bcs @bad
        jsr iec_in_byte
        sta tmp0
        jsr iec_in_byte
        sta tmp1
@skip:  jsr iec_in_byte
        cmp #$0d
        beq @d
        lda ST
        beq @skip
@d:     jsr iec_in_end
        lda tmp0
        cmp #'0'
        bne @bad
        lda tmp1
        cmp #'2'            ; 00 or 01 are fine
        bcs @bad
        clc
        rts
@bad:   sec
        rts

; iec_read: read the block in cmdbuf's t/s into (bp). A talker that stalls
; mid-byte (seen on the physical 1541) makes bus_acptr time out; UNTALK under
; ATN frees the drive, so ask again, up to three times.
iec_read:
        lda #3
        sta rd_try
@try:   jsr iec_read1
        bcc @ok
        dec rd_try
        bne @redo
        sec
@ok:    rts
@redo:  jsr iec_in_end
        jmp @try

iec_read1:
        jsr blk_to_ts
        lda #'1'
        jsr cmd_us
        jsr cmd_send
        bcs @e
        jsr cmd_status
        bcs @e
        lda cur_drv
        ldx #2
        jsr iec_in_begin
        bcs @e
        ldy #0
@l:     jsr iec_in_byte
        sta (bp),y
        lda ST
        and #$02
        bne @t              ; timed out: stop waiting byte by byte
        iny
        bne @l
        jsr iec_in_end
        clc
        rts
@t:     jsr iec_in_end
@e:     sec
        rts

s_bp:   .byte "B-P:2 0"
iec_write:
        jsr blk_to_ts
        ldx #6
@c:     lda s_bp,x
        sta cmdbuf,x
        dex
        bpl @c
        lda #7
        sta cmdlen
        jsr cmd_send
        bcs @e
        lda cur_drv
        ldx #2
        jsr iec_out_begin
        bcs @e
        ldy #0
@l:     lda (bp),y
        jsr iec_out_byte
        iny
        bne @l
        jsr iec_out_end
        lda #'2'
        jsr cmd_us
        jsr cmd_send
        bcs @e
        jmp cmd_status
@e:     sec
        rts

; ---- REU ----
reu_setup:                  ; rq_* and bp -> REU registers
        lda bp
        sta REU_C64LO
        lda bp+1
        sta REU_C64HI
        lda #0
        sta REU_LO
        sta REU_LENLO
        sta REU_CTRL
        lda rq_lo
        sta REU_HI
        lda rq_hi
        sta REU_BANK
        lda #1
        sta REU_LENHI
        rts

reu_read:
        jsr reu_setup
        lda #$91
        sta REU_CMD
        clc
        rts

reu_write:
        jsr reu_setup
        lda #$90
        sta REU_CMD
        clc
        rts

; transfer 1 byte (reu_tmp) to/from REU bank A offset 0; Y = command
reu_byte:
        sta REU_BANK
        lda #<reu_tmp
        sta REU_C64LO
        lda #>reu_tmp
        sta REU_C64HI
        lda #0
        sta REU_LO
        sta REU_HI
        sta REU_LENHI
        sta REU_CTRL
        lda #1
        sta REU_LENLO
        sty REU_CMD
        rts

reu_detect:
        lda #0
        sta reu_banks
        ldx #3
@p:     lda pat,x
        sta REU_C64LO,x
        dex
        bpl @p
        ldx #3
@q:     lda REU_C64LO,x
        cmp pat,x
        bne @none
        dex
        bpl @q
        ; write bank number into each bank, highest first
        ldx #127
@w:     stx reu_tmp
        txa
        ldy #$90
        jsr reu_byte
        dex
        bpl @w
        ; count banks that read back their own number
        ldx #0
@r:     txa
        ldy #$91
        jsr reu_byte
        cpx reu_tmp
        bne @done
        inx
        cpx #128
        bne @r
@done:  stx reu_banks
        cpx #0
        beq @none
        lda #1
        sta dev_present+1
        lda #FS_C64
        sta dev_type+1
@none:  rts
pat:    .byte $5a, $a5, $3c, $c3
