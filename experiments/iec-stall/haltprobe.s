; haltprobe: does the CPU get halted for long stretches (DMA from the Ultimate's REST reads, REU
; transfers, firmware bus use)? Interrupts are off; CIA2 timer A free-runs from $FFFF (phi2, one
; count per cycle) and timer B counts its underflows (a 32-bit clock). A tight loop reads timer A,
; takes the difference to the previous read and files it in a histogram. A badline steals about
; 40-43 cycles (+ up to 19 with sprites); a delta far above the loop period is a foreign halt.
;
; Assemble and load at $C000 (see haltprobe.py):
;   ca65 haltprobe.s -o haltprobe.o && ld65 -t none -S 0xC000 -o haltprobe.bin haltprobe.o
; Start with SYS 49152 (entry $C000) on the stock KERNAL's BASIC. Returns to READY when the host
; sets the stop byte (or the optional time limit passes): then DONE ($C810) is 1.
;
; Loop period (the fast path, no halt): P = 56 cycles. Count: lda abs 4 + ldx abs 4 + cmp abs 4 +
; bne 2 (the hi/lo/hi read, race-free) = 14; sta thi 3, lda plo 3, sec 2, stx plo 3, sbc plo 3,
; tay 2, lda phi 3, ldx thi 3, stx phi 3, sbc thi 3 = 28; bne 2, cpy# 2, bcs 2 = 6; inc zp 5, bne 3
; = 8. Total 56. (Not <= 25: a 16-bit delta without a read race cannot be done in fewer; the
; histogram edges are therefore on cycles OVER the period, i.e. stolen cycles, = delta - P.)
; The hi/lo/hi read retries when the low byte wraps between the two hi reads (8 of every 256
; cycles are in that window): a retry costs about 17 cycles, still inside the first bucket, but
; it makes the average period about 57.5 (VICE: 57.50 cycles/loop screen blanked, which is 56 +
; retries + the 256-iteration housekeeping), and the largest 'stolen' value for a single badline
; about 43 + 17 = 58 (seen: 58). tests/haltprobe_vice.py has the VICE runs.
;
; The delta is a 16-bit modulus: a gap of 65536 cycles (66 ms) or more aliases. The slow path
; (any delta > P+20) and the every-256th-iteration housekeeping re-read the timer last, so their
; own work never shows as a gap (and a halt landing inside them is not seen).
;
; Memory map (everything outside $C000-$C8FF and zp $F7-$FD is left alone):
;   config, written by the host (before the start, or live):
;     $C800 MODE    bit0: blank the screen ($D011 bit 4 off; badlines vanish); bit1: REU mode
;     $C801 STOP    nonzero: finish (checked every 256 iterations, ~14 ms)
;     $C802/3 LIMIT stop after this many 65536-cycle units (0 = until STOP)
;     $C804 REUEV   REU mode: one 256-byte C64->REU transfer every REUEV x 256 iterations (0 = 1)
;     $C806/7 REULEN REU mode: bytes per transfer (0 = 256; under VICE each byte steals a cycle)
;     $C805 CLEAR   nonzero: zero the histogram, max and transfer count; the program zeroes it
;                   when done (live "reset results" for an arm)
;   results (live, refreshed every 256 iterations; final when DONE = 1):
;     $C810 DONE   $C811 REUPRES (REU found)   $C812/3 XFERS (REU transfers started)
;     $C814/5 MAXDELTA (cycles, raw)   $C816/7 timer A value at that read (FFFF - it = cycles
;     into its 65536 period)   $C818/9 timer B at the last refresh (counts down 1 per 65536
;     cycles from $FFFF)   $C81A/B timer A at the end   $C81C PNOM (= 56)   $C81D RUNNING
;     $C820 + 4*i  bucket i, 32-bit little endian counts, i = 0..8, by delta - P:
;       0: <=20  1: 21-40  2: 41-65  3: 66-100  4: 101-200  5: 201-400  6: 401-800
;       7: 801-1600  8: >1600
;     (bucket 0 is counted in zero page and copied every 256 iterations: stale by < 256)
;   edges table ELO/EHI in the code: the 8 inclusive upper limits on delta (P + 20 ... P + 1600)

P       = 56
T       = P + 21                ; fast path while the low byte of delta < T and the high byte is 0

plo     = $FB                   ; previous timer A (lo, hi)
phi     = $FC
thi     = $FD                   ; current hi
c0      = $F7                   ; bucket 0 count, 32 bit
c1      = $F8
c2      = $F9
c3      = $FA

mode    = $C800
stopf   = $C801
limlo   = $C802
limhi   = $C803
reuev   = $C804
clearf  = $C805
reulen  = $C806                 ; REU transfer length, 16 bit (0 = 256)
donef   = $C810
reupres = $C811
xferlo  = $C812
xferhi  = $C813
maxlo   = $C814
maxhi   = $C815
tmlo    = $C816
tmhi    = $C817
bnlo    = $C818
bnhi    = $C819
afinlo  = $C81A
afinhi  = $C81B
pnom    = $C81C
runf    = $C81D
cnt     = $C820
dlo     = $C850
dhi     = $C851
reucnt  = $C852
d011s   = $C853
elo     = $C854
ehi     = $C855
srcbuf  = $C900                 ; 256 bytes sent by the REU transfer (any contents)

TALO    = $DD04
TAHI    = $DD05
TBLO    = $DD06
TBHI    = $DD07
CRA     = $DD0E
CRB     = $DD0F
REUCMD  = $DF01

        .segment "CODE"
start:  sei
        lda #0
        ldx #$43
@clr:   sta donef,x             ; $C810-$C853 results and scratch
        dex
        bpl @clr
        sta c0
        sta c1
        sta c2
        sta c3
        lda #P
        sta pnom
        lda reuev
        bne @e1
        lda #1
        sta reuev
@e1:    sta reucnt
        lda $D011
        sta d011s
        lda mode
        and #1
        beq @scr
        lda $D011
        and #$EF
        sta $D011
@scr:   ; REU present? the address registers read back what was written (a bare bus reads $DF)
        lda #$AA
        sta $DF04
        lda #$55
        sta $DF05
        lda $DF04
        cmp #$AA
        bne @noreu
        lda $DF05
        cmp #$55
        bne @noreu
        lda #1
        sta reupres
        lda #0
        sta $DF02               ; C64 address $C900
        sta $DF04               ; REU address 0
        sta $DF05
        sta $DF06
        sta $DF09
        sta $DF0A
        lda #$C9
        sta $DF03
        lda reulen              ; transfer length (0 = 256: the default)
        sta $DF07
        lda reulen+1
        bne @lh
        ldx reulen
        bne @lh
        lda #1
@lh:    sta $DF08
@noreu: lda #$FF                ; timers: both from $FFFF; B counts A's underflows
        sta TALO
        sta TAHI
        sta TBLO
        sta TBHI
        lda #$10                ; force load, stopped
        sta CRA
        lda #$50
        sta CRB
        lda #$41                ; B: start, count A underflows; then A: start, phi2
        sta CRB
        lda #$01
        sta CRA
        lda #1
        sta runf
        jsr rb

loop:   lda TAHI                ; hi, lo, hi: retry if the low byte wrapped in between
        ldx TALO
        cmp TAHI
        bne loop
        sta thi
        lda plo
        sec
        stx plo
        sbc plo                 ; A = old lo - cur lo
        tay
        lda phi
        ldx thi
        stx phi
        sbc thi                 ; A = hi of the 16-bit delta, Y = its lo
        bne slow
        cpy #T
        bcs slow
        inc c0
        bne loop
        jmp carry

; a delta over P+20: Y = lo, A = hi
slow:   sty dlo
        sta dhi
        lda dlo
        cmp maxlo
        lda dhi
        sbc maxhi
        bcc @nomax
        lda dlo
        sta maxlo
        lda dhi
        sta maxhi
        lda plo
        sta tmlo
        lda phi
        sta tmhi
@nomax: ldx #0
@find:  lda elo_tab,x           ; first edge >= delta
        sec
        sbc dlo
        lda ehi_tab,x
        sbc dhi
        bcs @found
        inx
        cpx #8
        bne @find
@found: txa
        asl
        asl
        tax
        inc cnt,x
        bne @done
        inc cnt+1,x
        bne @done
        inc cnt+2,x
        bne @done
        inc cnt+3,x
@done:  jsr rb
        jmp loop

; every 256 iterations: housekeeping, none of it counted as a gap
carry:  inc c1
        bne @c1
        inc c2
        bne @c1
        inc c3
@c1:    lda clearf
        beq @nocl
        jsr doclear
@nocl:  lda c0                  ; publish bucket 0
        sta cnt
        lda c1
        sta cnt+1
        lda c2
        sta cnt+2
        lda c3
        sta cnt+3
@brd:   lda TBHI                ; timer B, race-free
        ldx TBLO
        cmp TBHI
        bne @brd
        sta bnhi
        stx bnlo
        lda stopf
        beq @run
        jmp finish
@run:   lda limlo
        ora limhi
        beq @nolim
        lda bnhi                ; elapsed = not B
        eor #$FF
        sta ehi
        lda bnlo
        eor #$FF
        sta elo
        cmp limlo
        lda ehi
        sbc limhi
        bcc @nolim
        jmp finish
@nolim: lda mode
        and #2
        beq @norb
        lda reupres
        beq @norb
        dec reucnt
        bne @norb
        lda reuev
        sta reucnt
        inc xferlo
        bne @x1
        inc xferhi
@x1:    jsr rb                  ; stamp, then start the transfer: the next delta holds the halt
        lda #$B0                ; execute now, autoload, C64 -> REU
        sta REUCMD
        jmp loop
@norb:  jsr rb
        jmp loop

; stamp the timer into plo/phi
rb:     lda TAHI
        ldx TALO
        cmp TAHI
        bne rb
        sta phi
        stx plo
        rts

doclear:
        lda #0
        ldx #35
@z:     sta cnt,x
        dex
        bpl @z
        sta c0
        sta c1
        sta c2
        sta c3
        sta maxlo
        sta maxhi
        sta tmlo
        sta tmhi
        sta xferlo
        sta xferhi
        sta clearf
        rts

finish: lda c0
        sta cnt
        lda c1
        sta cnt+1
        lda c2
        sta cnt+2
        lda c3
        sta cnt+3
@fa:    lda TAHI
        ldx TALO
        cmp TAHI
        bne @fa
        sta afinhi
        stx afinlo
        lda #0
        sta CRA
        sta CRB
        lda d011s
        sta $D011
        lda #0
        sta runf
        lda #1
        sta donef
        cli
        rts

; inclusive upper limits on delta: P + 20, 40, 65, 100, 200, 400, 800, 1600
elo_tab: .byte <(P+20), <(P+40), <(P+65), <(P+100), <(P+200), <(P+400), <(P+800), <(P+1600)
ehi_tab: .byte >(P+20), >(P+40), >(P+65), >(P+100), >(P+200), >(P+400), >(P+800), >(P+1600)
