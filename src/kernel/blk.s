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

; The REU block cache holds the boot drive's blocks (dev 0) in REU banks above the
; /tmp RAM disk (banks 0-7): page 0 = header (magic, build id), pages 1-3 = one valid
; byte per block, then block b at page 4+b. It is write-through, and keyed by the build
; id in the c64fs superblock: a different id on the disk discards it. Needs 11 banks.
.ifndef CACHE_DEFAULT
CACHE_DEFAULT = 1       ; make CACHE=0: reads always use the bus; 1: the cache; 2: the cache, but
                        ; every boot starts cold (nothing a previous boot left is trusted)
.endif
CACHE_BANK  = 8
CACHE_NBLK  = 683       ; a 35-track 1541
SB_BLOCK    = 376
CH_LEN      = 24        ; cache header: magic(4) build id(4) disk label(16)
BAM_BLOCK   = 357       ; track 18 sector 0: the CBM disk label is at offset $90
BAM_LABEL   = $90
SB_BUILD_ID = 15        ; superblock offset of the 4-byte build id (tools/mkimage.py)

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
dev_present: .res NDEV+1  ; +1: DEV_UCI (uci.inc)
dev_type: .res NDEV+1
cur_drv: .res 1          ; drive number the IEC routines below talk to
dev_drive: .res NDEV+1  ; drive number of each device (0 = the boot drive)
cmdbuf:  .res 40
cmdlen:  .res 1
rd_try:  .res 1
reu_tmp: .res 1
cache_ok: .res 1         ; attached to a valid REU cache
cache_on: .res 1         ; reads consult it
c_hit:   .res 2
c_miss:  .res 2          ; reads that went to the bus
c_err:   .res 2          ; bus read/write errors
c_hdr:   .res CH_LEN     ; magic, build id, disk label of the disk
c_rd:    .res CH_LEN
cd_regs: .res 7          ; C64 addr, REU addr (lo, hi, bank), length: the REU registers $df02-$df08
cd_ctl:  .res 1
ep_done: .res 1          ; this boot has given the disk a new build id (it is being written)
ep_x:    .res 1

.export bwrite, buf_idx_ptr, cache_attach, sys_cache

.segment "RODATA"
; first linear block of each track (tracks 1..36), 16-bit
trk_lo: .lobytes 0,21,42,63,84,105,126,147,168,189,210,231,252,273,294,315,336,357,376,395,414,433,452,471,490,508,526,544,562,580,598,615,632,649,666,683
trk_hi: .hibytes 0,21,42,63,84,105,126,147,168,189,210,231,252,273,294,315,336,357,376,395,414,433,452,471,490,508,526,544,562,580,598,615,632,649,666,683
s_hash: .byte "#"
s_init: .byte "i0"
cmagic: .byte "BBCH"

.segment "CODE"
.segment "INIT"
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

.segment "CODE"
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
        jsr cache_get       ; carry clear: served from the REU
        bcc @chk
        lda rq_dev
        jsr cur_dev_set
        jsr iec_read
        bcs @e
        jsr cache_put
        clc
        jmp @chk
@e:     jsr cache_err
        sec
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
        bne @go
        lda cache_ok
        beq @go
        lda ep_done
        bne @go
        lda b_clock             ; keep this buffer from being the victim of the superblock read
        sta b_age,x
        stx ep_x
        jsr cache_epoch
        ldx ep_x
        stx b_idx
        bcs @r
@go:    lda b_dev,x
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
        jsr cache_inval     ; not valid while the disk is being changed (a reset in between)
        jsr iec_write
        bcs @we
        jsr cache_wr        ; write-through: the REU copy follows the disk
        clc
        jmp @r
@we:    jsr cache_err
        jsr cache_inval
        sec
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

.segment "INIT"
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
        ; keep byte 0 of every bank (the cache header lives there); bufs is free this early
        ldx #127
@sv:    txa
        ldy #$91
        jsr reu_byte
        lda reu_tmp
        sta bufs,x
        dex
        bpl @sv
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
        ldx #127
@rs:    lda bufs,x
        sta reu_tmp
        txa
        ldy #$90
        jsr reu_byte
        dex
        bpl @rs
        lda reu_banks
        beq @none
        lda #1
        sta dev_present+1
        lda #FS_C64
        sta dev_type+1
@none:  rts
pat:    .byte $5a, $a5, $3c, $c3

.segment "CODE"
; ---- REU block cache ----
; cdma: A = command ($90 stash, $91 fetch); cd_regs and cd_ctl set
cdma:   pha
        ldx #6
@l:     lda cd_regs,x
        sta REU_C64LO,x
        dex
        bpl @l
        lda cd_ctl
        sta REU_CTRL
        pla
        sta REU_CMD
        rts

; cache_chk: carry clear if rq_dev/rq_lo/rq_hi is a block the cache holds
cache_chk:
        lda cache_ok
        beq @no
        lda rq_dev
        bne @no
        lda rq_hi
        cmp #>CACHE_NBLK
        bcc @yes
        bne @no
        lda rq_lo
        cmp #<CACHE_NBLK
        bcs @no
@yes:   clc
        rts
@no:    sec
        rts

; the block's valid byte is in the REU at bank CACHE_BANK, offset $0100+block
cache_vaddr:
        lda #<reu_tmp
        sta cd_regs
        lda #>reu_tmp
        sta cd_regs+1
        lda rq_lo
        sta cd_regs+2
        lda rq_hi
        clc
        adc #1
        sta cd_regs+3
        lda #CACHE_BANK
        sta cd_regs+4
        lda #1
        sta cd_regs+5
        lda #0
        sta cd_regs+6
        rts

cache_valid:                ; -> A = valid byte (Z clear if valid)
        jsr cache_vaddr
        lda #$91
        jsr cdma
        lda reu_tmp
        rts

cache_setvalid:             ; A = 0 or 1
        sta reu_tmp
        jsr cache_vaddr
        lda #$90
        jmp cdma

; the block's data is at page 4+block; bp is the C64 side
cache_page:
        lda bp
        sta cd_regs
        lda bp+1
        sta cd_regs+1
        lda #0
        sta cd_regs+2
        lda rq_lo
        clc
        adc #4
        sta cd_regs+3
        lda rq_hi
        adc #CACHE_BANK
        sta cd_regs+4
        lda #0
        sta cd_regs+5
        lda #1
        sta cd_regs+6
        rts

; cache_get: carry clear if the block was fetched from the REU into bp
cache_get:
        jsr cache_chk
        bcs @no
        lda cache_on
        beq @no
        jsr cache_valid
        beq @no
        jsr cache_page
        lda #$91
        jsr cdma
        ldx #0
        jsr cinc
        clc
        rts
@no:    sec
        rts

; cache_put: a block was just read from the bus into bp
cache_put:
        jsr cache_chk
        bcs @r
        ldx #2
        jsr cinc
        jmp cache_wr
@r:     rts

; cache_wr: bp holds the block's current contents; keep the REU copy in step
cache_wr:
        jsr cache_chk
        bcs @r
        jsr cache_page
        lda #$90
        jsr cdma
        lda #1
        jmp cache_setvalid
@r:     rts

; cache_inval: forget the block (the disk's contents are in doubt)
cache_inval:
        jsr cache_chk
        bcs @r
        lda #0
        jmp cache_setvalid
@r:     rts

; cache_err: a bus error on the boot drive (the other drives are not the cache's business)
cache_err:
        lda rq_dev
        bne cinc_r
        ldx #4
        ; fall through
; cinc: count one in the 16-bit counter at c_hit+X, saturating at $ffff
cinc:   inc c_hit,x
        bne cinc_r
        inc c_hit+1,x
        bne cinc_r
        lda #$ff
        sta c_hit,x
        sta c_hit+1,x
cinc_r: rts

; cache_clear: forget every block and write c_hdr as the header
cache_clear:
        lda #0
        sta reu_tmp
        sta cd_regs+2
        sta cd_regs+3
        sta cd_regs+5
        lda #<reu_tmp
        sta cd_regs
        lda #>reu_tmp
        sta cd_regs+1
        lda #CACHE_BANK
        sta cd_regs+4
        lda #4              ; header page + three map pages
        sta cd_regs+6
        lda #$80            ; C64 address fixed: fills with the zero byte
        sta cd_ctl
        lda #$90
        jsr cdma
        lda #0
        sta cd_ctl
        ; fall through
; cache_hdr_put: write c_hdr to the REU header
cache_hdr_put:
        lda #<c_hdr
        sta cd_regs
        lda #>c_hdr
        sta cd_regs+1
        lda #0
        sta cd_regs+2
        sta cd_regs+3
        lda #CACHE_BANK
        sta cd_regs+4
        lda #CH_LEN
        sta cd_regs+5
        lda #0
        sta cd_regs+6
        lda #$90
        jmp cdma

.segment "INIT"
; cache_attach: before the root is mounted. Reads the superblock from the bus, and
; discards the REU cache unless it belongs to this disk (same build id).
ca_r:   rts
cache_attach:
        lda #0
        sta cache_ok
        sta cache_on
        sta cd_ctl
        sta ep_done
.if CACHE_DEFAULT = 0
        rts                     ; no cache at all: the bus is all there is
.endif
        lda reu_banks
        cmp #CACHE_BANK+3
        bcc ca_r
        lda #0
        ldx #<BAM_BLOCK
        ldy #>BAM_BLOCK
        jsr bread               ; cache_ok is clear: from the bus
        bcs ca_r
        ldx #15                 ; the label tells disks apart even when the build id cannot
        ldy #BAM_LABEL+15
@lb:    lda (bp),y
        sta c_hdr+8,x
        dey
        dex
        bpl @lb
        lda #0
        ldx #<SB_BLOCK
        ldy #>SB_BLOCK
        jsr bread
        bcs ca_r
        ldy #3
@m:     lda cmagic,y
        sta c_hdr,y
        dey
        bpl @m
        ldx #3
        ldy #SB_BUILD_ID+3
@i:     lda (bp),y
        sta c_hdr+4,x
        dey
        dex
        bpl @i
        lda c_hdr+4             ; no id: a disk the cache cannot vouch for
        ora c_hdr+5
        ora c_hdr+6
        ora c_hdr+7
        beq ca_r
        lda #<c_rd
        sta cd_regs
        lda #>c_rd
        sta cd_regs+1
        lda #0
        sta cd_regs+2
        sta cd_regs+3
        sta cd_regs+6
        lda #CACHE_BANK
        sta cd_regs+4
        lda #CH_LEN
        sta cd_regs+5
        lda #$91
        jsr cdma
.if CACHE_DEFAULT <> 2
        ldx #CH_LEN-1
@c:     lda c_rd,x
        cmp c_hdr,x
        bne @fmt
        dex
        bpl @c
        bmi @ok
.endif
@fmt:   jsr cache_clear
@ok:    lda #1
        sta cache_ok
        sta cache_on
        jmp cache_wr            ; the superblock (bp) goes in

.segment "CODE"
; cache_epoch: the first write to the boot drive in a boot. Gives the disk a new build id
; (and the cache header the same), so a copy of the disk that was not written by this
; boot, such as the pristine image mounted again, no longer matches the cache.
; Carry set if the superblock could not be changed (the write must then not go ahead).
cache_epoch:
        lda #1
        sta ep_done
        lda #0
        ldx #<SB_BLOCK
        ldy #>SB_BLOCK
        jsr bread
        bcs @r
        ldy #SB_BUILD_ID
        lda $dc04               ; free-running timers stand in for a random number
        ora #1                  ; and the id always changes
        eor (bp),y
        sta (bp),y
        sta c_hdr+4
        iny
        lda (bp),y
        eor $dc05
        sta (bp),y
        sta c_hdr+5
        iny
        lda (bp),y
        eor $dd04
        sta (bp),y
        sta c_hdr+6
        iny
        lda (bp),y
        eor $dd05
        sta (bp),y
        sta c_hdr+7
        jsr bwrite              ; the superblock; ep_done is set, so no recursion
        bcs @r
        jmp cache_hdr_put
@r:     rts

; sys_cache(A = op, r0 = buf): 0 = status into buf: state (0 none, 1 off, 2 on), hits,
; bus reads, bus errors (16 bits each); 1 = off, 2 = on, 3 = flush
sys_cache:
        cmp #4
        bcs @inval
        cmp #0
        beq @stat
        ldx cache_ok
        beq @nodev
        cmp #3
        beq @flush
        and #1                  ; 1 -> 1 (off), 2 -> 0
        eor #1
        sta cache_on
        clc
        rts
@flush: jmp cache_clear_c
@stat:  ldx #0
        lda cache_ok
        beq @st
        inx
        lda cache_on
        beq @st
        inx
@st:    txa
        ldy #0
        sta (r0),y
        ldx #0
@cp:    lda c_hit,x
        iny
        sta (r0),y
        inx
        cpx #6
        bne @cp
        clc
        rts
@inval: lda #EINVAL
        sec
        rts
@nodev: lda #ENODEV
        sec
        rts
cache_clear_c:
        jsr cache_clear
        clc
        rts
