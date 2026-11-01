; atnprobe: can a stalled physical 1541 be freed by ATN (UNTALK), and does a fresh TALK then deliver data?
; Not a program: this code is placed in free RAM at $7000 while the stage-2 kernel is hung in its bus wait, and the IRQ
; vector ($FFFE) is pointed at it; the next timer tick runs it on top of the frozen kernel. It uses the driver's own
; routines (addresses passed to ca65 with -D from the build's label file) and leaves its findings at res.
;   res+0 $DD00 before     res+1 ST before        (bit 6 of $DD00 = CLK in, bit 7 = DATA in; 1 = released)
;   res+2 $DD00 after UNTALK   res+3 ST after UNTALK
;   res+4 carry of iec_in_begin (1 = the drive did not answer TALK)   res+5 ST after it
;   res+6 bytes received   res+7 ST at the end (bit 6 = EOI seen, bit 1 = timeout)   res+8 first byte   res+9 done = 1
;   res+10 .. res+15 the first 6 bytes, res+16 set if 256 bytes came with no EOI
; Assemble: ca65 -D BUS_UNTLK=$xxxx -D IN_BEGIN=$xxxx -D IN_BYTE=$xxxx atnprobe.s -o atnprobe.o
;           ld65 -t none -S 0x7000 -o atnprobe.bin atnprobe.o
res    = $7F00
buf    = $7E00

        .segment "CODE"
start:  lda #<stub          ; first, make the next interrupts harmless (the driver's bus wait re-enables them)
        sta $FFFE
        lda #>stub
        sta $FFFF
        lda $DD00
        sta res+0
        lda $90
        sta res+1
        lda #0
        sta $90
        jsr BUS_UNTLK       ; UNTALK under ATN: the thing a recovery would do
        lda $DD00
        sta res+2
        lda $90
        sta res+3
        lda #0
        sta $90
        lda #8              ; TALK device 8, secondary address 2: the drive's data buffer
        ldx #2
        jsr IN_BEGIN
        lda #0
        rol a
        sta res+4
        lda $90
        sta res+5
        ldx #0
@l:     jsr IN_BYTE         ; preserves X and Y
        sta buf,x
        lda $90
        and #$42
        bne @end            ; EOI or a timeout: stop
        inx
        bne @l
        ldx #0              ; 256 bytes with no EOI
        inc res+16          ; (marks "256 and no EOI")
        jmp @fin
@end:   inx
@fin:   stx res+6
        lda $90
        sta res+7
        lda buf
        sta res+8
        ldy #5
@c:     lda buf,y
        sta res+10,y
        dey
        bpl @c
        jsr BUS_UNTLK
        lda #1
        sta res+9
@halt:  jmp @halt

stub:   pha
        lda $DC0D           ; acknowledge the CIA1 timer and return
        pla
        rti
