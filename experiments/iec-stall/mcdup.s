; mcdup: copy a whole 35-track disk image from one drive to another sector by sector, then read every
; sector back from the target and compare. The Ultimate mounts the image as a drive (device 9), this copies
; it onto the physical disk (device 8), so a D64 gets onto real media with no keyboard. Stock KERNAL
; routines only (run it on the STOCK KERNAL host: standard protocol). Own code, no third-party source.
;
; Per sector: U1:2 0 t s on the source, read the status, read 256 bytes from its "#" buffer; B-P:3 0 on the
; target, write 256 bytes to its "#" buffer, U2:3 0 t s, read the status; U1:3 0 t s, read the sector back and
; compare. The target disk must already be formatted. The first drive error is recorded and the copy goes on.
; Variables (read them by DMA): srcdev $C7E0, dstdev $C7E1 (set before SYS 49152); done $C7F0, sectors
; copied $C7F1/2, drive errors $C7F3, read-back mismatches $C7F4, first error at track $C7F5, sector $C7F6,
; status digits $C7F7/8. The sectors to copy are a list of (track, sector) byte pairs at $CA00, their number
; (16 bits) at $C7E2/3: all 683, or only those that differ from what is already on the media.
; Assemble: ca65 mcdup.s -o mcdup.o && ld65 -t none -S 0xC000 -o mcdup.bin mcdup.o   (see mcdup.py)
CHROUT = $FFD2
CHRIN  = $FFCF
OPEN   = $FFC0
SETLFS = $FFBA
SETNAM = $FFBD
CHKIN  = $FFC6
CHKOUT = $FFC9
CLRCHN = $FFCC

srcdev = $C7E0
dstdev = $C7E1
total  = $C7E2              ; 2 bytes: number of (track, sector) pairs at tab
tab    = $CA00
done   = $C7F0
cnt    = $C7F1              ; 2 bytes
errs   = $C7F3
vmis   = $C7F4
e_t    = $C7F5
e_s    = $C7F6
e_c1   = $C7F7
e_c2   = $C7F8
buf    = $C800
vbuf   = $C900

tt     = $FB
ss     = $FC
idx    = $FD
nsec   = $FE
c1     = $F7
c2     = $F8
ptr    = $F9                ; 2 bytes: the list pointer
lin    = $C7E4              ; 2 bytes: how many pairs are done

        .segment "CODE"
start:  lda #0
        sta done
        sta cnt
        sta cnt+1
        sta errs
        sta vmis
        sta e_t
        lda #15             ; command channel of the source
        ldx srcdev
        ldy #15
        jsr open_nm
        lda #14             ; command channel of the target
        ldx dstdev
        ldy #15
        jsr open_nm
        lda #2              ; data buffer of the source
        ldx srcdev
        ldy #2
        jsr open_hash
        lda #3              ; data buffer of the target
        ldx dstdev
        ldy #3
        jsr open_hash
        lda #<tab
        sta ptr
        lda #>tab
        sta ptr+1
        lda #0
        sta lin
        sta lin+1
@next:  lda lin             ; stop when lin = total
        cmp total
        bne @go
        lda lin+1
        cmp total+1
        beq @fin
@go:    ldy #0
        lda (ptr),y
        sta tt
        iny
        lda (ptr),y
        sta ss
        jsr copy
        inc ptr
        inc ptr
        bne @p
        inc ptr+1
@p:     inc lin
        bne @next
        inc lin+1
        jmp @next
@fin:   lda #1
        sta done
        rts

open_nm: jsr SETLFS         ; A = file number, X = device, Y = secondary address
        lda #0
        jsr SETNAM
        jmp OPEN

open_hash: jsr SETLFS
        lda #1
        ldx #<hash
        ldy #>hash
        jsr SETNAM
        jmp OPEN

copy:   lda #(s_u1a - strs) ; read the sector from the source
        ldx #15
        jsr sendcmd
        ldx #15
        jsr status
        beq :+
        jmp @err
:
        ldx #2
        jsr CHKIN
        lda #0
        sta idx
@rd:    jsr CHRIN
        ldy idx
        sta buf,y
        inc idx
        bne @rd
        jsr CLRCHN
        lda #(s_bp - strs)  ; buffer pointer to 0 on the target
        ldx #14
        jsr sendstr
        ldx #3
        jsr CHKOUT
        lda #0
        sta idx
@wr:    ldy idx
        lda buf,y
        jsr CHROUT
        inc idx
        bne @wr
        jsr CLRCHN
        lda #(s_u2 - strs)  ; write the buffer to the target's sector
        ldx #14
        jsr sendcmd
        ldx #14
        jsr status
        beq :+
        jmp @err
:
        lda #(s_u1b - strs) ; read it back
        ldx #14
        jsr sendcmd
        ldx #14
        jsr status
        beq :+
        jmp @err
:
        ldx #3
        jsr CHKIN
        lda #0
        sta idx
@vr:    jsr CHRIN
        ldy idx
        sta vbuf,y
        inc idx
        bne @vr
        jsr CLRCHN
        ldy #0
@cp:    lda buf,y
        cmp vbuf,y
        bne @mis
        iny
        bne @cp
        beq @ok
@mis:   inc vmis
@ok:    inc cnt
        bne @r
        inc cnt+1
@r:     rts
@err:   inc errs
        lda e_t
        bne @r              ; keep the first error only
        lda tt
        sta e_t
        lda ss
        sta e_s
        lda c1
        sta e_c1
        lda c2
        sta e_c2
        rts

; sendstr: A = offset in strs, X = file number. Sends the zero-terminated string.
sendstr: pha
        jsr CHKOUT
        pla
        sta idx
@c:     ldy idx
        lda strs,y
        beq @e
        jsr CHROUT
        inc idx
        bne @c
@e:     jmp CLRCHN

; sendcmd: as sendstr, then " t s" and a carriage return
sendcmd: pha
        jsr CHKOUT
        pla
        sta idx
@c:     ldy idx
        lda strs,y
        beq @e
        jsr CHROUT
        inc idx
        bne @c
@e:     lda tt
        jsr pr2
        lda #' '
        jsr CHROUT
        lda ss
        jsr pr2
        lda #13
        jsr CHROUT
        jmp CLRCHN

; status: X = file number. Reads the drive status line; Z set if it begins "00".
status: jsr CHKIN
        jsr CHRIN
        sta c1
        jsr CHRIN
        sta c2
@r:     jsr CHRIN
        cmp #13
        bne @r
        jsr CLRCHN
        lda c1
        cmp #'0'
        bne @bad
        lda c2
        cmp #'0'
@bad:   rts

pr2:    ldx #'0'            ; A = 0..99 as two decimal digits
@t:     cmp #10
        bcc @u
        sbc #10
        inx
        bne @t
@u:     pha
        txa
        jsr CHROUT
        pla
        clc
        adc #'0'
        jmp CHROUT

strs:
s_u1a:  .byte "U1:2 0 ", 0
s_bp:   .byte "B-P:3 0", 13, 0
s_u2:   .byte "U2:3 0 ", 0
s_u1b:  .byte "U1:3 0 ", 0
hash:   .byte "#"
