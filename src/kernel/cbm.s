; Breadbin: normal Commodore DOS disks on drives 9-11, and mount()
;
; A CBM disk mounted with mount() shows up as one flat directory.
; Reading uses raw sectors through the block cache: the directory chain
; on track 18 and each file's track/sector chain. Writing, scratching
; and renaming go through the drive's own DOS (so its BAM stays right);
; afterwards the cache for that drive is dropped.
;
; Pseudo inodes: 1 = the root directory, k+2 = directory entry k.
.include "k.inc"
.include "uci.inc"

.importzp bp, pp
.import binval, cmdbuf, cmdlen, to_ascii, to_petscii, build_path, pbuf
.import mt_used, mt_pdev, mt_pino, mt_dev, mt_path, mnt_point, mount_dev
.import nm_dev, nm_ino, f_done

.export cbm_iget, cbm_lookup, cbm_read, cbm_readdir, cbm_open_write
.export cbm_write, cbm_wclose, cbm_scratch, cbm_rename, cbm_fsinfo
.export sys_mount, sys_umount, sys_mntinfo, sys_diskio
.import uci_hw, uci_attach, uci_umount, mod_load, uci_load, uci_drop
.export cbmv, w_busy, cbm_none

.segment "BSS"
cbm_up:  .res 1         ; the cbm module is loaded
cb_cnt:  .res 1         ; scratch for diskio
w_busy:  .res NDEV
mo_dev:  .res 1
mo_pdev: .res 1
mo_pino: .res 1
mo_ent:  .res 1

.segment "RODATA"
magic:   .byte "C64FS"

; ---------------------------------------------------------------------
; The CBM filesystem lives in /lib/km/cbm (src/mod/cbm.s). These stubs are what file.s and
; fs.s call; the module's init points cbmv at its routines.
.segment "DATA"
cbmv:   .word cbm_none, cbm_none, cbm_none, cbm_none, cbm_none
        .word cbm_none, cbm_none, cbm_none, cbm_none, cbm_none

.segment "CODEHI"            ; runs above the BSS, out of the way of the user pool
cbm_iget:       jmp (cbmv+0)
cbm_lookup:     jmp (cbmv+2)
cbm_read:       jmp (cbmv+4)
cbm_readdir:    jmp (cbmv+6)
cbm_open_write: jmp (cbmv+8)
cbm_write:      jmp (cbmv+10)
cbm_wclose:     jmp (cbmv+12)
cbm_scratch:    jmp (cbmv+14)
cbm_rename:     jmp (cbmv+16)
cbm_fsinfo:     jmp (cbmv+18)
cbm_none:       lda #ENODEV
        sec
        rts

; cbm_ensure: load the module the first time a CBM disk is mounted. Carry set on failure.
cbm_ensure:
        lda cbm_up
        bne @ok
        lda #<s_km
        sta r0
        lda #>s_km
        sta r0+1
        jsr mod_load
        bcs @r
        lda #1
        sta cbm_up
@ok:    clc
@r:     rts

.segment "RODATA"
s_km:   .byte "/lib/km/cbm", 0

.segment "CODEHI"
; ---------------------------------------------------------------------
; mount(A = drive 9-11, or 'U' for the Ultimate's storage, r0 = directory)
sys_mount:
        cmp #'U'            ; with X = 'U' too: mount 85 stays a bad drive number
        bne @drv
        cpx #'U'
        bne @drv
        lda $DF1D           ; nothing answering as a UCI here: ENODEV without loading the module
        cmp #$C9            ; (the same first read the module's probe makes; Classic touches only this)
        beq @load
        lda #ENODEV
        sec
        rts
@load:  jsr uci_load        ; the probe and the rest are module code: load uci.km first
        bcs @rr
        jsr @uci            ; (every way out of the code below is an rts)
        bcc @rr
        jmp uci_drop        ; the mount failed: unload uci.km again (keeps A and carry)
@uci:   lda dev_present+DEV_UCI
        bne @onboot         ; one UCI mount at a time
        jsr uci_hw          ; probe the hardware first (only here, never at boot)
        bcs @rr
        lda #DEV_UCI
        sta mo_dev
        bne @np
@drv:   sec
        sbc #7
        cmp #2
        bcc @inval
        cmp #NDEV
        bcs @inval
        sta mo_dev
        tax
        lda dev_drive,x
        cmp dev_drive       ; the boot drive holds the running system
        beq @onboot
        lda dev_present,x
        beq @np
@onboot: lda #EBUSY
        sec
@rr:    rts
@inval: lda #EINVAL
        sec
        rts
@np:    ; free mount entry
        ldx #NMNT-1
@fe:    lda mt_used,x
        beq @got
        dex
        bpl @fe
        lda #EBUSY
        sec
        rts
@got:   stx mo_ent
        lda r0
        sta pp
        lda r0+1
        sta pp+1
        jsr namei
        bcs @r
        lda nm_dev
        sta mo_pdev
        lda nm_ino
        sta mo_pino
        lda nm_dev
        ldx nm_ino
        jsr iget
        bcs @r
        lda ci+I_TYPE
        cmp #T_DIR
        beq @dir
        lda #ENOTDIR
        sec
@r:     rts
@dir:   lda mo_pdev         ; not inside UCI (its namei never sees mount points)
        cmp #DEV_UCI
        beq @busy
        lda mo_pino         ; not on top of another mount
        cmp #ROOT_INO
        bne @nr
        lda mo_pdev
        bne @busy
@nr:    lda mo_pdev
        ldx mo_pino
        jsr mnt_point
        bcs @ok
@busy:  lda #EBUSY
        sec
        rts
@ok:    jsr build_path
        bcs @r
        ldx #0              ; mt_path holds 31 characters: refuse to cut the mount point
@ln:    lda pbuf,x
        beq @lok
        inx
        cpx #32
        bne @ln
        lda #ENAMETOOLONG
        sec
        rts
@lok:   ldx mo_dev
        cpx #DEV_UCI
        bne @iec
        jsr uci_attach
        bcs @r
        jmp @add
@iec:   jsr iec_open
        bcs @r
        lda mo_dev
        jsr binval
        ; a Breadbin disk?
        lda mo_dev
        ldx #<376
        ldy #>376
        jsr bread
        bcs @nodisk
        ldy #4
@m:     lda (bp),y
        cmp magic,y
        bne @cbm
        dey
        bpl @m
        ldx mo_dev
        lda #FS_C64
        sta dev_type,x
        lda mo_dev
        ldx #<376
        ldy #>376
        jsr mount_dev
        bcs @nodisk
        jmp @add
@cbm:   ; a CBM DOS disk: track 18 sector 0 is a BAM with format 'A'
        lda mo_dev
        ldx #<357
        ldy #>357
        jsr bread
        bcs @nodisk
        ldy #2
        lda (bp),y
        cmp #$41
        bne @nodisk
        jsr cbm_ensure      ; the filesystem code is a module: load it on first use
        bcs @nodisk
        ldx mo_dev
        lda #FS_CBM
        sta dev_type,x
@add:   ldx mo_dev
        lda #1
        sta dev_present,x
        ldx mo_ent
        lda #1
        sta mt_used,x
        lda mo_pdev
        sta mt_pdev,x
        lda mo_pino
        sta mt_pino,x
        lda mo_dev
        sta mt_dev,x
        jsr ent_path
        ldy #0
@cp:    lda pbuf,y
        sta (p1),y
        beq @fin
        iny
        cpy #31
        bne @cp
        lda #0
        sta (p1),y
@fin:   clc
        rts
@nodisk:
        ldx mo_dev
        jsr iec_close
        lda mo_dev
        jsr binval
        lda #ENODEV
        sec
        rts

; ---------------------------------------------------------------------
; diskio(A = drive 9-11, X = op): raw access to an unmounted drive, for
; /bin/format.  op 0: send the DOS command at r0 (NUL-terminated)
;               op 1: write the 256 bytes at r0 to block r1
;               op 2: read block r1 into the 256 bytes at r0
sys_diskio:
        stx mo_ent
        sec
        sbc #7
        cmp #2
        bcc @inval
        cmp #NDEV
        bcs @inval
        sta mo_dev
        tax
        lda dev_drive,x
        cmp dev_drive       ; the boot drive holds the running system
        beq @onboot
        lda dev_present,x
        beq @free
@onboot: lda #EBUSY
        sec
        rts
@inval: lda #EINVAL
        sec
        rts
@free:  ldx mo_dev
        jsr iec_open
        bcs @r
        lda mo_dev
        jsr binval
        lda mo_ent
        beq @cmd
        cmp #1
        beq @wr
        ; read
        lda mo_dev
        ldx r1
        ldy r1+1
        jsr bread
        bcs @done
        ldy #0
@rl:    lda (bp),y
        sta (r0),y
        iny
        bne @rl
        clc
        jmp @done
@wr:    lda mo_dev
        ldx r1
        ldy r1+1
        jsr bget_buf
        stx cb_cnt
        ldy #0
@wl:    lda (r0),y
        sta (bp),y
        iny
        bne @wl
        ldx cb_cnt
        jsr bwrite
        jmp @done
@cmd:   ldy #0
@cl:    lda (r0),y
        beq @ce
        sta cmdbuf,y
        iny
        cpy #39
        bne @cl
@ce:    sty cmdlen
        lda mo_dev
        jsr iec_command
@done:  php
        ldx mo_dev
        jsr iec_close
        lda mo_dev
        jsr binval
        plp
        bcc @r
        lda #EIO
@r:     rts
.import bwrite

; ent_path: X = mount entry -> p1 = &mt_path[x*32]
ent_path:
        txa
        asl a
        asl a
        asl a
        asl a
        asl a
        clc
        adc #<mt_path
        sta p1
        lda #>mt_path
        adc #0
        sta p1+1
        rts

; umount(r0 = mounted directory)
sys_umount:
        lda r0
        sta pp
        lda r0+1
        sta pp+1
        jsr namei
        bcs @r
        lda nm_ino
        cmp #ROOT_INO
        bne @inval
        lda nm_dev
        cmp #2
        bcc @inval
        sta mo_dev
        ; busy? open files or working directories on it
        ldx #NFILE-1
@f:     lda f_type,x
        cmp #FT_FILE
        beq @fd
        cmp #FT_DIR
        beq @fd
        cmp #FT_CBMW
        bne @fn
@fd:    lda f_dev,x
        cmp mo_dev
        beq @busy
@fn:    dex
        bpl @f
        ldx #MAXPROC-1
@p:     lda p_state,x
        beq @pn
        lda p_cwddev,x
        cmp mo_dev
        beq @busy
@pn:    dex
        bpl @p
        lda mo_dev
        jsr mnt_of_dev
        bcs @inval
        lda #0
        sta mt_used,x
        ldx mo_dev
        sta dev_present,x
        sta dev_type,x
        cpx #DEV_UCI
        bne @iec
        jsr uci_umount
        jsr uci_drop        ; the last (only) UCI mount: unload uci.km
        clc
        rts
@iec:   jsr iec_close
        lda mo_dev
        jsr binval
        clc
@r:     rts
@inval: lda #EINVAL
        sec
        rts
@busy:  lda #EBUSY
        sec
        rts
.import mnt_of_dev

; mntinfo(A = entry, r0 = buf[34]): drive (0 = REU), type, path[32]
sys_mntinfo:
        cmp #$ff            ; the root: drive, c64fs, "/"
        beq @root
        cmp #NMNT
        bcs @no
        tax
        lda mt_used,x
        beq @no
        lda mt_dev,x
        tay
        lda dev_drive,y
        ldy #0
        sta (r0),y
        lda mt_dev,x
        tay
        lda dev_type,y
        ldy #1
        sta (r0),y
        jsr ent_path
        lda r0
        clc
        adc #2
        sta p2
        lda r0+1
        adc #0
        sta p2+1
        ldy #0
@c:     lda (p1),y
        sta (p2),y
        iny
        cpy #32
        bne @c
        clc
        rts
@no:    lda #EINVAL
        sec
        rts
@root:  ldy #0
        lda dev_drive
        sta (r0),y
        iny
        lda #FS_C64
        sta (r0),y
        iny
        lda #'/'
        sta (r0),y
        iny
        lda #0
        sta (r0),y
        clc
        rts

.segment "RODATA"
