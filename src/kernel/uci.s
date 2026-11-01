; Breadbin: the Ultimate's file storage through the Command Interface (UCI v1)
;
; THROWAWAY v1, dev-only (docs/design/next/uci-v1.md). `mount uci DIR` puts the Ultimate's
; whole file tree (host "/") on DIR as device DEV_UCI (5, dev_type FS_UCI = $80). Paths are
; resolved as whole strings: namei hands anything below the mount to uci_namei, which
; normalizes the path (build_path), strips the mount prefix and asks the Ultimate about the
; rest in one go. Pseudo inodes: 1 = the mount root, 2 = a file (size from the last probe),
; 3 = another directory. Two host handles (DOS targets 1 and 2) are cached between the
; open files; a file's host path lives in a path slot (a pool page taken at mount).
;
; Classic is untouched: nothing here runs, and $DF1B-$DF1F is never read or written, until
; `mount uci` is asked for. Everything is polled (the completion IRQ hangs firmware 1.1.0)
; with bounded waits (about 5 s, then ABORT and EIO); interrupts stay on.
;
; CUT IN THE NEXT FOOTPRINT PASS (all of this file goes to a loadable module in v2; until
; then, in this order): the 11-character IDENTIFY check (keep the $C9 test), the readdir
; "~" mark, O_APPEND, the rmdir ENOTEMPTY mapping, the probe-handle adoption, the text error
; map (-> EIO). The bmi sites in file.s/fs.s/exec.s/cbm.s become the C2 ops row.
.include "k.inc"
.include "uci.inc"

.importzp fb, pp
.import build_path, pbuf, mnt_of_dev, mt_path, nm_dev, nm_ino, nm_parent, f_done
.import of_flags, open_exists

.export uci_namei, uci_iget, uci_read, uci_xread, uci_write, uci_open, uci_create
.export uci_release, uci_hw, uci_attach, uci_umount, uci_fsinfo, uci_mkdir
.export uci_rmdir, uci_unlink, uci_rename

UCI_CTL = $DF1C         ; write: 1 push, 2 data accepted, 4 abort, 8 clear error
UCI_CMD = $DF1D         ; write: command FIFO; read: identification ($C9)
UCI_DAT = $DF1E         ; response data
UCI_ST  = $DF1F         ; status text
UCI_ID  = $C9
UCI_TMO = 4             ; wait bound: UCI_TMO * 65536 polls of ~19 cycles, about 5 s

C_IDENT = $01
C_OPEN  = $02           ; attribute: 1 read, 2 write, 4 create new, 8 create always
C_CLOSE = $03
C_READ  = $04
C_WRITE = $05
C_SEEK  = $06
C_INFO  = $07           ; size(4) date(2) time(2) ext(3) attrib(1) name
C_DEL   = $09
C_REN   = $0A
C_CD    = $11
C_ODIR  = $13
C_RDIR  = $14
C_MKDIR = $16

HS_FREE  = $FF          ; handle slot owners: an open-file entry, or one of these
HS_PROBE = $FE          ; left open by the last probe (a read handle at position 0)
HS_OLD   = $FD          ; left open by an earlier probe: closed when taken
NUPATH   = 5            ; path slots of CWDLEN bytes in the mount page

.segment "BSS"
hs_own:  .res 2         ; owner of DOS target 1 / 2
hs_p0:   .res 2         ; the host's position in that file, 24 bits
hs_p1:   .res 2
hs_p2:   .res 2
hs_lru:  .res 1         ; the slot to take next
ps_used: .res NUPATH
u_page:  .res 1         ; the path-slot page
u_hp:    .res 1         ; host path = pbuf + u_hp
u_root:  .res 1         ; the path is the mount point itself
u_cr:    .res 1         ; uci_create -> uci_open: create the file
u_size:  .res 3
u_info:  .res 12
u_pos:   .res 3
u_pp:    .res 2
u_s:     .res 1
u_e:     .res 1
u_x:     .res 1
u_c:     .res 2
u_w:     .res 2
u_j:     .res 2
u_err:   .res 1
ut_m:    .res 1
ut_v:    .res 1
ut_t:    .res 1
ut_n:    .res 2         ; bytes still wanted
ut_got:  .res 2         ; bytes received
stbuf:   .res 7         ; the head of the last status text

.segment "RODATA"
ps_off:  .byte 0, 48, 96, 144, 192
omode:   .byte 1, 2, 3, 3
s_ident: .byte "ULTIMATE"
; ut_map's table, searched from the end: {first, sixth (0 = any), errno}
mtab:    .byte 'F', 0,   ENOENT     ; FILE DOESN'T EXIST
         .byte 'A', 0,   EPERM      ; ACCESS DENIED
         .byte 'F', 'E', EEXIST     ; FILE EXISTS
         .byte 'F', 'I', EBUSY      ; FILE IS IN USE
         .byte 'D', 'T', ENOTEMPTY  ; DIRECTORY NOT EMPTY
         .byte 'D', 'I', ENOSPC     ; DISK IS FULL

.segment "CODE"
; ---------------------------------------------------------------------
; transport
; ut_idle / ut_data: wait for the state idle / data (last or more). Carry set, A = EIO
; on timeout (after an ABORT). Uses X/Y.
ut_idle: lda #$30
        ldx #$00
        beq ut_poll
ut_data: lda #$20
        tax
ut_poll: sta ut_m
        stx ut_v
        lda #UCI_TMO
        sta ut_t
        ldx #0
        ldy #0
@w:     lda UCI_CTL
        and ut_m
        cmp ut_v
        beq @ok
        dex
        bne @w
        dey
        bne @w
        dec ut_t
        bne @w
        lda #$04
        sta UCI_CTL
        lda #EIO
        sec
        rts
@ok:    clc
        rts

; ut_tc: A = command, X = slot: start a command to DOS target X+1
ut_tc:  pha
        inx
        txa
        pha
        lda UCI_CTL
        and #$38
        beq @go
        lda #$0C            ; ABORT | CLR_ERR: whatever an earlier command left behind
        sta UCI_CTL
        jsr ut_idle
@go:    pla
        sta UCI_CMD
        pla
        sta UCI_CMD
        rts

; ut_hpath: send the host path (pbuf + u_hp); ut_str: send the string at p3
ut_hpath:
        lda u_hp
        clc
        adc #<pbuf
        sta p3
        lda #>pbuf
        adc #0
        sta p3+1
ut_str: ldy #0
@l:     lda (p3),y
        beq @r
        sta UCI_CMD
        iny
        bne @l
@r:     rts

; ut_run: push the command, throw its data away -> carry/A from the status (ut_got kept).
; ut_recv: the same, keeping up to ut_n bytes at (p4) -> ut_got = bytes kept
ut_run: lda #0
        sta ut_n
        sta ut_n+1
        beq ut_go
ut_recv:
        lda #0
        sta ut_got
        sta ut_got+1
ut_go:  sta stbuf
        lda #$01
        sta UCI_CTL
        jsr ut_data
        bcs @r
@b:     lda UCI_CTL
        bpl @pk
        lda UCI_DAT
        ldy ut_n
        bne @st
        ldy ut_n+1
        beq @b
        dec ut_n+1
@st:    dec ut_n
        ldy #0
        sta (p4),y
        inc p4
        bne @c
        inc p4+1
@c:     inc ut_got
        bne @b
        inc ut_got+1
        jmp @b
@pk:    jsr ut_pkt
        bcc @b
        jmp ut_map
@r:     rts

; ut_pkt: keep the status of this packet (if it has one), accept it. Carry clear: the next
; packet of the chain is there; carry set: that was the last
ut_pkt: ldy #0
@s:     bit UCI_CTL
        bvc @sd
        lda UCI_ST
        cpy #6
        bcs @s
        sta stbuf,y
        iny
        bne @s
@sd:    cpy #0
        beq @ns
        lda #0
        sta stbuf,y
@ns:    lda UCI_CTL
        and #$30
        tax
        lda #$02
        sta UCI_CTL
        cpx #$30
        bne @last
        jsr ut_data
        bcc @r
        lda #'T'
        sta stbuf
@last:  sec
@r:     rts

; ut_map: the status text -> carry clear, or carry set and A = errno
ut_map: lda stbuf
        beq @ok             ; empty: past the end of a file
        cmp #'0'            ; 00 OK, 01 directory empty, 02 truncated
        beq @ok
        cmp #'O'            ; "OK!"
        beq @ok
        ldx #ENOENT
        cmp #'P'            ; PATH DOESN'T EXIST
        beq @e
        cmp #'8'
        bne @nn
        lda stbuf+1         ; 82 file not found, 83 no such directory, 88 no information
        cmp #'2'
        beq @e
        cmp #'3'
        beq @e
        cmp #'8'
        beq @e
        bne @io
@nn:    ldy #15             ; the file system's texts: first and sixth character
@t:     lda mtab,y
        cmp stbuf
        bne @tn
        lda mtab+1,y
        beq @hit            ; 0: any
        cmp stbuf+5
        bne @tn
@hit:   ldx mtab+2,y
        bne @e
@tn:    dey
        dey
        dey
        bpl @t
@io:    ldx #EIO
@e:     txa
        sec
        rts
@ok:    clc
        rts

; u_get12: A = command, X = slot: run it, keep 12 bytes of the answer in u_info
u_get12:
        jsr ut_tc
        lda #<u_info
        sta p4
        lda #>u_info
        sta p4+1
        lda #12
        sta ut_n
        lda #0
        sta ut_n+1
        jmp ut_recv

; ---------------------------------------------------------------------
; handle slots
; hs_close: X = slot. Close what it holds (an error is of no interest). Uses X/Y.
hs_close:
        ldy hs_own,x
        iny                 ; HS_FREE
        beq @r
        lda #HS_FREE
        sta hs_own,x
        lda #C_CLOSE
        jsr ut_tc
        jmp ut_run
@r:     rts

uci_closeall:
        ldx #1
        jsr hs_close
        ldx #0
        jmp hs_close

; u_dropprobe: close the handles the probes left open
u_dropprobe:
        ldx #1
@l:     lda hs_own,x
        cmp #HS_OLD
        bcc @n
        cmp #HS_FREE
        beq @n
        jsr hs_close
        jmp u_dropprobe
@n:     dex
        bpl @l
        rts

; hs_find: A = owner -> X = its slot (N clear), or X = $FF (N set)
hs_find: ldx #1
@l:     cmp hs_own,x
        beq @r
        dex
        bpl @l
@r:     rts

; hs_claim: X = slot, A = owner. At position 0; the other slot is taken next
hs_claim:
        sta hs_own,x
        lda #0
        sta hs_p0,x
        sta hs_p1,x
        sta hs_p2,x
hs_used:
        txa
        eor #1
        sta hs_lru
        rts

; hs_at: X = slot. SEEK it to u_pos unless the host is there already
hs_at:  stx u_s
        jsr hs_used
        lda u_pos
        cmp hs_p0,x
        bne @sk
        lda u_pos+1
        cmp hs_p1,x
        bne @sk
        lda u_pos+2
        cmp hs_p2,x
        beq @ok
@sk:    jsr hs_set
        lda #C_SEEK
        jsr ut_tc
        lda u_pos
        sta UCI_CMD
        lda u_pos+1
        sta UCI_CMD
        lda u_pos+2
        sta UCI_CMD
        lda #0
        sta UCI_CMD
        jmp ut_run
@ok:    clc
        rts

; u_adv: u_pos += ut_got; the host of slot u_s is there now
u_adv:  clc
        lda u_pos
        adc ut_got
        sta u_pos
        lda u_pos+1
        adc ut_got+1
        sta u_pos+1
        lda u_pos+2
        adc #0
        sta u_pos+2
        ldx u_s
hs_set: lda u_pos
        sta hs_p0,x
        lda u_pos+1
        sta hs_p1,x
        lda u_pos+2
        sta hs_p2,x
        rts

; u_open: A = OPEN attribute, p3 = path, u_e = owner -> u_s = its slot
u_open: pha
        ldx hs_lru
        stx u_s
        jsr hs_close
        ldx u_s
        lda #C_OPEN
        jsr ut_tc
        pla
        sta UCI_CMD
        jsr ut_str
        jsr ut_run
        bcs @r
        ldx u_s
        lda u_e
        jsr hs_claim        ; (carry clear from ut_run)
@r:     rts

; uci_ensure: X = open-file entry, u_pos = where it is -> u_s = a slot open on it, there
uci_ensure:
        stx u_e
        txa
        jsr hs_find
        bpl @have
        ldx u_e
        lda f_ino,x
        jsr ps_ptr
        ldx u_e
        lda f_flags,x
        and #3
        tay
        lda omode,y         ; reopening never creates or truncates
        jsr u_open
        bcs @r
        ldx u_s
@have:  jmp hs_at
@r:     rts

; ps_ptr: A = path slot -> p3
ps_ptr: tay
        lda ps_off,y
        sta p3
        lda u_page
        sta p3+1
        rts

; e_getpos / e_putpos: X = entry <-> u_pos
e_getpos:
        lda f_pos0,x
        sta u_pos
        lda f_pos1,x
        sta u_pos+1
        lda f_pos2,x
        sta u_pos+2
        rts
e_putpos:
        lda u_pos
        sta f_pos0,x
        lda u_pos+1
        sta f_pos1,x
        lda u_pos+2
        sta f_pos2,x
        rts

; ---------------------------------------------------------------------
; path resolution
; uci_hpath: (pp) -> pbuf (normalized) and u_hp, u_root. Carry set: A = errno, or A = 0
; when the path is not below the UCI mount any more ("/u/..")
uci_hpath:
        jsr build_path
        bcs @r
        ldy #0              ; the host splits on '\' as well: refuse it
@bs:    lda pbuf,y
        beq @bd
        iny
        cmp #'\'
        bne @bs
        lda #EINVAL
        sec
        rts
@bd:
        lda #DEV_UCI
        jsr mnt_of_dev
        bcs @out
        txa
        asl a
        asl a
        asl a
        asl a
        asl a
        tax
        ldy #0
@c:     lda mt_path,x
        beq @e
        cmp pbuf,y
        bne @out
        inx
        iny
        bne @c
@e:     lda #0
        sta u_root
        lda pbuf,y
        bne @sl
        inc u_root          ; the mount point itself: host "/"
        lda #'/'
        sta pbuf,y
        lda #0
        sta pbuf+1,y
        beq @ok
@sl:    cmp #'/'
        bne @out
@ok:    sty u_hp
        clc
@r:     rts
@out:   lda #0
        sec
        rts

; uci_namei: from namei, at the component at (pp),y on DEV_UCI: resolve the rest at once
uci_namei:
        lda #0
        sta u_cr
        lda nm_parent
        beq @path
        ; fs_name = the last component, as the c64fs walk leaves it (for the "." checks)
        ldx #0
@cc:    lda (pp),y
        beq @ce
        cmp #'/'
        beq @sl
        cpx #15
        bcs @sk
        sta fs_name,x
        inx
@sk:    iny
        bne @cc
        beq @lg             ; 256 bytes of path: Y would wrap
@sl:    iny
        beq @lg
        lda (pp),y
        cmp #'/'
        beq @sl
        cmp #0
        beq @ce
        ldx #0
        beq @cc
@ce:    lda #0
@pz:    cpx #16
        bcs @path
        sta fs_name,x
        inx
        bne @pz
@path:  jsr uci_hpath
        bcc @in
        tax
        bne @err            ; A = errno, carry set
        ; walked out of the mount: resolve the normalized path from the top
        lda pp
        sta u_pp
        lda pp+1
        sta u_pp+1
        lda #<pbuf
        sta pp
        lda #>pbuf
        sta pp+1
        jsr namei
        php
        ldx u_pp
        stx pp
        ldx u_pp+1
        stx pp+1
        plp
        rts
@lg:    lda #ENAMETOOLONG
        sec
@err:   rts
@in:    lda nm_parent
        beq @full
        lda u_root
        bne @busy
        lda #3              ; the parent: some directory (the host checks it)
        bne @ino
@full:  lda u_root
        beq uci_probe
        lda #ROOT_INO
@ino:   sta nm_ino
        clc
        rts
@busy:  lda #EBUSY
        sec
        rts

; uci_probe: what is at the host path? -> nm_ino 2 (a file: u_size, left open as a probe
; handle) or 3 (a directory). OPEN + FILE INFO, then CHANGE DIR (FILE STAT does not work).
uci_probe:
        lda #HS_PROBE       ; only the newest probe's handle may be adopted or read by spawn
        jsr hs_find
        bmi @n
        lda #HS_OLD
        sta hs_own,x
@n:     ldx hs_lru
        stx u_s
        jsr hs_close
        ldx u_s
        lda #C_OPEN
        jsr ut_tc
        lda #$01
        sta UCI_CMD
        jsr ut_hpath
        jsr ut_run
        bcs @nf
        ldx u_s
        lda #HS_PROBE       ; held from here on: hs_close undoes it
        jsr hs_claim
        lda #C_INFO
        jsr u_get12
        bcs @bad
        lda u_info+11
        and #$10            ; the DIR attribute
        bne @dir
        ldx #2
@c:     lda u_info,x
        sta u_size,x
        dex
        bpl @c
        lda u_info+3        ; 16 MB or more: clamp
        beq @s
        lda #$ff
        sta u_size
        sta u_size+1
        sta u_size+2
@s:     lda #2
        bne @ino
@bad:   pha
        ldx u_s
        jsr hs_close
        pla
        sec
        rts
@nf:    sta u_err
        ldx u_s
        lda #C_CD
        jsr u_path
        bcc @isd
        lda u_err
        rts
@dir:   ldx u_s
        jsr hs_close
@isd:   lda #3
@ino:   sta nm_ino
        clc
        rts

; uci_iget: ci_ino 1/3 -> a directory, 2 -> the probed file
uci_iget:
        ldx #INO_SIZE-1
        lda #0
@z:     sta ci,x
        dex
        bpl @z
        lda #1
        sta ci+I_NLINK
        ldy #T_DIR
        lda ci_ino
        cmp #2
        bne @t
        ldy #T_FILE
        ldx #2
@s:     lda u_size,x
        sta ci+I_SIZE,x
        dex
        bpl @s
@t:     sty ci+I_TYPE
        clc
        rts

; ---------------------------------------------------------------------
; open files
; uci_create: from sys_open, a file that is not there (nameiparent left its path in pbuf)
uci_create:
        lda #1
        sta u_cr
        ldx #2
        lda #0
@z:     sta u_size,x
        dex
        bpl @z
        lda #2
        sta nm_ino
        jmp open_exists

; uci_open: X = new entry (f_dev, f_flags set), nm_ino = what the probe found.
; -> X = entry; carry set (A = errno): the caller drops the entry
uci_open:
        stx u_e
        jsr uci_hpath       ; pp is still the path (namei stops at "/u" without building it)
        bcs @hp
        ldx #NUPATH-1       ; a path slot, holding the host path
@ps:    lda ps_used,x
        beq @pg
        dex
        bpl @ps
        lda #EMFILE
@hp:    ldx u_e
        inc f_dev,x         ; not DEV_UCI any more: nothing for uci_release to undo
        sec
        rts
@pg:    lda #1
        sta ps_used,x
        txa
        ldx u_e
        sta f_ino,x
        jsr ps_ptr
        ldx u_hp
        ldy #0
@cp:    lda pbuf,x
        sta (p3),y
        beq @cd
        inx
        iny
        bne @cp
@cd:    lda nm_ino
        cmp #2
        bne @ok             ; a directory: nothing to open until it is read
        lda of_flags
        and #3
        ora u_cr
        bne @now
        lda #HS_PROBE       ; reading: the probe has just opened this very file
        jsr hs_find
        bmi @ok             ; (or it is opened when first read)
        lda u_e
        sta hs_own,x
        bpl @ok
@now:   jsr u_dropprobe
        lda of_flags
        and #3
        beq @m0             ; read-only: O_TRUNC means nothing
        lda of_flags
        and #O_TRUNC
@m0:    ora u_cr
        beq @m
        lda #$08            ; create always (truncates)
@m:     sta u_c
        lda of_flags
        and #3
        tay
        lda omode,y
        ora u_c
        jsr u_open
        bcs @fail
        lda of_flags
        and #O_APPEND
        beq @ok
        ldx u_s             ; appending: start at the end
        lda #C_INFO
        jsr u_get12
        bcs @fail
        ldx u_e
        lda u_info
        sta f_pos0,x
        lda u_info+1
        sta f_pos1,x
        lda u_info+2
        sta f_pos2,x
@ok:    ldx u_e             ; (u_cr is cleared by the next uci_namei)
        clc
        rts
@fail:  ldx u_e
        rts

; uci_release: from oft_unref, X = an entry being freed. Keeps X.
uci_release:
        lda f_dev,x
        cmp #DEV_UCI
        bne @r
        stx u_x
        ldy f_ino,x
        lda #0
        sta ps_used,y
        txa
        jsr hs_find
        bmi @x
        jsr hs_close
@x:     ldx u_x
@r:     rts

; uci_read: from sys_read, entry sb6, r0 = buffer, r1 = count -> r1 = bytes read
uci_read:
        ldx sb6
        lda f_type,x
        cmp #FT_DIR
        bne @f
        jmp uci_readdir
@f:     jsr e_getpos
        jsr uci_ensure
        bcs @r
        lda r0
        sta p4
        lda r0+1
        sta p4+1
        lda r1
        sta ut_n
        lda r1+1
        sta ut_n+1
        jsr u_rd
        php
        pha
        ldx sb6
        jsr e_putpos
        lda ut_got
        sta r1
        lda ut_got+1
        sta r1+1
        pla
        plp
@r:     rts

; u_rd: READ DATA ut_n bytes into (p4) on slot u_s; u_pos advances
u_rd:   ldx u_s
        lda #C_READ
        jsr ut_tc
        lda ut_n
        sta UCI_CMD
        lda ut_n+1
        sta UCI_CMD
        jsr ut_recv
        php
        pha
        jsr u_adv
        pla
        plp
        rts

; uci_xread: fs_read for spawn: f_off, f_cnt, fb, from the probe's handle -> f_done
uci_xread:
        ldy #2
@i:     lda f_off,y
        sta u_pos,y
        dey
        bpl @i
        lda #HS_PROBE
        jsr hs_find
        bpl @g
        lda #EIO
        sec
        rts
@g:     jsr hs_at
        bcs @r
        lda fb
        sta p4
        lda fb+1
        sta p4+1
        lda f_cnt
        sta ut_n
        lda f_cnt+1
        sta ut_n+1
        jsr u_rd
        php
        ldx #2
@o:     lda u_pos,x
        sta f_off,x
        dex
        bpl @o
        lda ut_got
        sta f_done
        lda ut_got+1
        sta f_done+1
        plp
@r:
u_ret0: rts

; uci_write: from sys_write, entry sb6, r0 = data, r1 = count -> r1 = written.
; WRITE DATA in requests of up to 512 bytes; no write-behind.
uci_write:
        ldx sb6
        jsr e_getpos
        lda u_pos           ; positions are 24 bits: stop at 16 MB rather than wrap
        clc
        adc r1
        lda u_pos+1
        adc r1+1
        lda u_pos+2
        adc #0
        bcc @fit
        lda #EFBIG
        rts
@fit:   jsr uci_ensure
        bcs u_ret0
        lda r0
        sta p4
        lda r0+1
        sta p4+1
        lda r1              ; u_w = bytes left
        sta u_w
        lda r1+1
        sta u_w+1
@ch:    ldx #2              ; n = min(512, left)
        lda #0
        ldy u_w+1
        cpy #2
        bcs @cap
        tya
        tax
        lda u_w
@cap:   sta ut_got
        stx ut_got+1
        ora ut_got+1
        beq @done
        ldx u_s
        lda #C_WRITE
        jsr ut_tc
        lda #0
        sta UCI_CMD
        sta UCI_CMD
        lda ut_got
        sta u_c
        lda ut_got+1
        sta u_c+1
@b:     ldy #0
        lda (p4),y
        sta UCI_CMD
        inc p4
        bne @c
        inc p4+1
@c:     lda u_c
        bne @d
        dec u_c+1
@d:     dec u_c
        lda u_c
        ora u_c+1
        bne @b
        jsr ut_run          ; (keeps ut_got = n)
        bcs @err
        jsr u_adv
        lda u_w
        sec
        sbc ut_got
        sta u_w
        lda u_w+1
        sbc ut_got+1
        sta u_w+1
        jmp @ch
@err:   pha                 ; the host's position is unknown now: drop the handle
        ldx u_s
        jsr hs_close
        pla
        sec
        ldx u_w             ; something written: report the count
        cpx r1
        bne @done
        ldx u_w+1
        cpx r1+1
        bne @done
        sec
        rts
@done:  ldx sb6
        jsr e_putpos
        lda r1
        sec
        sbc u_w
        sta r1
        lda r1+1
        sbc u_w+1
        sta r1+1
        clc
u_ret:  rts

; uci_readdir: entry sb6 (path slot, entries delivered so far in f_pos0/1), r0, r1 ->
; 16-byte records {ino, name[15]}. Lists the directory again on every call (k skipped).
; Directory commands leave a target's open file alone, so no handle is closed.
uci_readdir:
        lda r0
        sta p4
        lda r0+1
        sta p4+1
        lda #0
        sta u_w
        sta u_w+1
        sta u_j
        sta u_j+1
        lda f_ino,x
        jsr ps_ptr
        ldx hs_lru
        stx u_s
        lda #C_CD
        jsr ut_tc
        jsr ut_str
        jsr ut_run
        bcs u_ret
        ldx u_s
        lda #C_ODIR
        jsr ut_tc
        jsr ut_run
        bcs u_ret
        lda stbuf+1
        cmp #'1'            ; 01 DIRECTORY EMPTY: READ DIR would answer an internal error
        beq @done
        ldx u_s
        lda #C_RDIR
        jsr ut_tc
        lda #$01
        sta UCI_CTL
        jsr ut_data
        bcs u_ret
@pk:    lda UCI_CTL         ; one entry per packet: attribute, name
        bpl @next
        lda UCI_DAT
        sta u_c
        ldx sb6
        lda u_j             ; delivered by an earlier call?
        cmp f_pos0,x
        lda u_j+1
        sbc f_pos1,x
        bcc @skip
        lda r1              ; room for a record?
        sec
        sbc u_w
        tay
        lda r1+1
        sbc u_w+1
        bne @room
        cpy #16
        bcc @skip
@room:  jsr u_rec
@k:     ldx sb6
        inc f_pos0,x
        bne @skip
        inc f_pos1,x
@skip:  inc u_j
        bne @next
        inc u_j+1
@next:  lda UCI_CTL         ; the rest of this packet
        bpl @nx
        lda UCI_DAT
        jmp @next
@nx:    jsr ut_pkt
        bcc @pk
        jsr ut_map
        bcs @r
@done:  lda u_w
        sta r1
        lda u_w+1
        sta r1+1
        clc
@r:     rts

; u_rec: one record {ino, name[15]} at (p4) from the packet (attribute in u_c); p4, u_w += 16
u_rec:  ldy #0
        lda u_c
        and #$10
        beq @fi
        lda #3
        bne @ty
@fi:    lda #2
@ty:    sta (p4),y
@nm:    iny
        cpy #15
        beq @tl
        lda UCI_CTL
        bpl @pad
        lda UCI_DAT
        sta (p4),y
        jmp @nm
@tl:    lda UCI_CTL         ; longer than 14: mark the cut
        bpl @pad
        dey
        lda #'~'
        sta (p4),y
        iny
@pad:   lda #0
@pd:    sta (p4),y
        iny
        cpy #16
        bne @pd
        lda p4
        clc
        adc #16
        sta p4
        bcc @p4
        inc p4+1
@p4:    lda u_w
        clc
        adc #16
        sta u_w
        bcc @r
        inc u_w+1
@r:     rts

; ---------------------------------------------------------------------
; directory operations (after nameiparent: pbuf/u_hp = the full path)
uci_mkdir:
        ldx #0
        lda #C_MKDIR
u_path: jsr ut_tc
        jsr ut_hpath
        jmp ut_run

; u_del: DELETE the path in pbuf, every handle closed first
u_del:  jsr u_nofiles
        bcs u_dret
        jsr uci_closeall
        ldx #0
        lda #C_DEL
        bne u_path

; u_nofiles: EBUSY while any UCI file is open: a handle closed here would be reopened by
; its path later, which after a delete or rename is another file (or none)
u_nofiles:
        ldx #NFILE-1
@l:     lda f_type,x
        cmp #FT_FILE
        bne @n
        lda f_dev,x
        cmp #DEV_UCI
        beq @b
@n:     dex
        bpl @l
        clc
        rts
@b:     lda #EBUSY
        sec
u_dret: rts

uci_rmdir:              ; pp = the path
        jsr namei
        bcs @r
        lda nm_ino
        cmp #3
        beq @d
        ldx #EBUSY          ; 1: the mount point
        cmp #ROOT_INO
        beq @e
        ldx #ENOTDIR
@e:     txa
        sec
        rts
@d:     jsr u_del
        bcc @r
        cmp #EPERM          ; ACCESS DENIED: not empty (UNVERIFIED on the bench)
        bne @x
        lda #ENOTEMPTY
@x:     sec
@r:     rts

uci_unlink:             ; pp = the path
        jsr namei
        bcs @r
        lda nm_ino
        cmp #2
        beq u_del
        lda #EISDIR
        sec
@r:     rts

; uci_rename: r0 = old (its parent is on UCI), r1 = new. No replacing: EEXIST if new exists.
uci_rename:
        lda r1
        sta pp
        lda r1+1
        sta pp+1
        jsr nameiparent
        bcs @r
        lda nm_dev
        cmp #DEV_UCI
        beq @s
        lda #EXDEV
        sec
@r:     rts
@s:     jsr u_nofiles
        bcs @r
        jsr uci_closeall
        lda r0
        sta pp
        lda r0+1
        sta pp+1
        jsr uci_hpath       ; both are strings now (both resolved by uci_namei just now:
        ldx #0              ; they cannot fail), built straight into the FIFO
        lda #C_REN
        jsr ut_tc
        jsr ut_hpath
        lda #0
        sta UCI_CMD
        lda r1
        sta pp
        lda r1+1
        sta pp+1
        jsr uci_hpath
        jsr ut_hpath
        jmp ut_run

uci_fsinfo:             ; no free-space command exists: 65535 of 65535 blocks, no inodes
        ldy #6
        lda #DEV_UCI
        sta (r1),y
        lda #0
        dey
        sta (r1),y
        dey
        sta (r1),y
        lda #$ff
@l:     dey
        sta (r1),y
        bne @l
        clc
        rts

; ---------------------------------------------------------------------
; mount
; uci_hw: is a Command Interface there? Three ID reads (open bus can show $C9 once),
; then IDENTIFY on target 1. Carry set, A = ENODEV if not.
uci_hw: ldx #3
@id:    lda UCI_CMD
        cmp #UCI_ID
        bne @no
        dex
        bne @id
        ldx #0              ; (ut_tc aborts and clears whatever a reset left)
        lda #C_IDENT
        jsr u_get12
        bcs @no
        ldx #7
@cm:    lda u_info,x
        cmp s_ident,x
        bne @no
        dex
        bpl @cm
        clc
        rts
@no:    lda #ENODEV
        sec
        rts

; uci_attach: from sys_mount once the mount point checks passed (pbuf = it; keep pbuf)
uci_attach:
        ldy #1
        jsr page_alloc
        bcs @r
        sta u_page
        lda #HS_FREE
        sta hs_own
        sta hs_own+1        ; (ps_used is all clear: umount needs every file closed)
        lda #FS_UCI
        sta dev_type+DEV_UCI
        clc
@r:     rts

uci_umount:
        jsr uci_closeall
        lda u_page
        ldy #1
        jmp page_free
