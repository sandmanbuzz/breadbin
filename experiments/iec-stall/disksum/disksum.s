; disksum.s: read every sector of the disk on device 8 (U1 block reads through the stock KERNAL) and keep a
; 3-byte checksum of each sector at TABLE: sum of the 256 bytes mod 65536 (lo, hi) and their XOR. Reads only: no
; write command is sent to the drive. Host side: disksum.py (run with BREADBIN_ULTIMATE set, stock KERNAL, Software
; IEC off, the physical 1541 on bus 8). Build: ca65 disksum.s; ld65 -t none -S $C000 (see disksum.py).
;
; Sectors are visited in the d64 order: track 1 to 35, sector 0 to the track's count (21/19/18/17).
; State for the host, all in C64 RAM:
;   COUNT ($C7F0, 2 bytes)  sectors done
;   ERRCH ($C7F2, 2 bytes)  the status of the failing command (for example "74" on a drive error)
;   STATE ($C7F4)           0 running, 1 done, $EE block error (see ERRCH), $EF could not open the channels
; The track and sector in progress are at TRK and SECT (ordinary RAM, see below).

SETNAM = $FFBD
SETLFS = $FFBA
OPEN   = $FFC0
CLOSE  = $FFC3
CHKIN  = $FFC6
CHKOUT = $FFC9
CLRCHN = $FFCC
CHRIN  = $FFCF
CHROUT = $FFD2
READST = $FFB7

BUF    = $4F00      ; 256-byte sector buffer
TABLE  = $5000      ; 683 entries x 3 bytes
COUNT  = $C7F0
ERRCH  = $C7F2
STATE  = $C7F4

; state lives in ordinary RAM: the stock KERNAL writes zero page ($F1-$FE) on the serial path (seen in the
; stall dump: the table pointer moved from $5000 to $1800). $FB/$FC is used only for the one indirect store.
TMPX   = $C7EB      ; X saved across KERNAL calls
TPL    = $C7E4      ; pointer into TABLE, TPL/TPH
TPH    = $C7E5
XS     = $C7E9      ; running XOR
TMP    = $C7EA
TRK    = $C7E0
SECT   = $C7E1
IDX    = $C7E2      ; sectors done, IDX/IDX+1
SPT    = $C7E6      ; sectors on the current track
SUML   = $C7E7      ; running sum, SUML/SUMH
SUMH   = $C7E8

start:
        lda #0
        sta IDX
        sta IDX+1
        sta STATE
        sta COUNT
        sta COUNT+1
        sta ERRCH
        sta ERRCH+1
        ; command channel 15 to device 8, then the direct-access channel 2 ("#")
        lda #0
        ldx #0
        ldy #0
        jsr SETNAM
        lda #15
        ldx #8
        ldy #15
        jsr SETLFS
        jsr OPEN
        bcc @o1
        jmp open_fail
@o1:    lda #1
        ldx #<hashnm
        ldy #>hashnm
        jsr SETNAM
        lda #2
        ldx #8
        ldy #2
        jsr SETLFS
        jsr OPEN
        bcc @o2
        jmp open_fail
@o2:
        lda #<TABLE
        sta TPL
        lda #>TABLE
        sta TPH
        lda #1
        sta TRK
        lda #0
        sta SECT

sector:
        ; "U1:2 0 tt ss" on channel 15
        lda #15
        jsr CHKOUT
        ldx #0
@cmd:   stx TMPX
        lda cmdstr,x
        beq @cmdd
        jsr CHROUT
        ldx TMPX
        inx
        jmp @cmd
@cmdd:  lda TRK
        jsr senddec
        lda #' '
        jsr CHROUT
        lda SECT
        jsr senddec
        jsr CLRCHN

        ; the two status characters, then the rest of the line up to CR (or end of data)
        lda #15
        jsr CHKIN
        jsr CHRIN
        sta ERRCH
        jsr CHRIN
        sta ERRCH+1
@st:    jsr READST
        bne @std
        jsr CHRIN
        cmp #13
        bne @st
@std:   jsr CLRCHN
        lda ERRCH
        cmp #'0'
        beq @e1
        jmp block_err
@e1:    lda ERRCH+1
        cmp #'0'
        beq @e2
        jmp block_err
@e2:

        ; the 256 bytes of the sector, channel 2
        lda #2
        jsr CHKIN
        ldx #0
@rd:    stx TMPX
        jsr CHRIN
        ldx TMPX
        sta BUF,x
        inx
        bne @rd
        jsr CLRCHN

        ; sum (16 bit) and XOR of the sector, stored at the table entry
        lda #0
        sta SUML
        sta SUMH
        sta XS
        ldx #0
@cs:    lda BUF,x
        sta TMP
        clc
        adc SUML
        sta SUML
        lda SUMH
        adc #0
        sta SUMH
        lda XS
        eor TMP
        sta XS
        inx
        bne @cs
        lda TPL
        sta $FB
        lda TPH
        sta $FC
        ldy #0
        lda SUML
        sta ($FB),y
        iny
        lda SUMH
        sta ($FB),y
        iny
        lda XS
        sta ($FB),y
        lda TPL
        clc
        adc #3
        sta TPL
        bcc @tn
        inc TPH
@tn:

        ; count it
        inc IDX
        bne @ic
        inc IDX+1
@ic:    lda IDX
        sta COUNT
        lda IDX+1
        sta COUNT+1

        ; next sector: wrap to the next track at the track's count, stop after track 35
        inc SECT
        lda TRK
        jsr spt
        sta SPT
        lda SECT
        cmp SPT
        bcc @go
        lda #0
        sta SECT
        inc TRK
        lda TRK
        cmp #36
        bcc @go
        jmp done
@go:    jmp sector

done:   lda #1
        sta STATE
        jmp closeall

block_err:
        lda #$EE
        sta STATE
        jmp closeall

open_fail:
        lda #$EF
        sta STATE
        rts

closeall:
        lda #2
        jsr CLOSE
        lda #15
        jsr CLOSE
        jsr CLRCHN
        rts

; spt: A = track (1 to 35) -> A = sectors on that track (21, 19, 18 or 17)
spt:
        cmp #18
        bcs @a
        lda #21
        rts
@a:     cmp #25
        bcs @b
        lda #19
        rts
@b:     cmp #31
        bcs @c
        lda #18
        rts
@c:     lda #17
        rts

; senddec: A = 0 to 99 -> decimal digits on channel 15, no leading zero (sent with CHROUT; A is clobbered)
senddec:
        ldy #0
@t:     cmp #10
        bcc @d
        sec
        sbc #10
        iny
        jmp @t
@d:     pha
        tya
        beq @u              ; no leading zero: the drive hangs on "U1:2 0 01 00" (hand test, 2026-11-02)
        clc
        adc #'0'
        jsr CHROUT
@u:     pla
        clc
        adc #'0'
        jsr CHROUT
        rts

hashnm: .byte '#'
cmdstr: .byte "U1:2 0 ", 0
