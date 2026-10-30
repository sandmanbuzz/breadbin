; Breadbin keyboard: matrix scan, decode, key repeat, jiffy clock
;
; Replaces the KERNAL's SCNKEY, GETIN and UDTIM. The stock locations keep
; their stock meaning, so anything written against the C64 memory map (and
; VICE's `keybuf`, which feeds the buffer directly) still works:
;
;   $0277  keyboard buffer (10 keys)      $0289  buffer length (10)
;   $C6    keys in the buffer             $028A  repeat: $00 cursor/space/del,
;   $CB    key being held ($40 = none)           $40 none, $80 all keys
;   $C5    key held at the previous scan  $028B  repeat speed counter
;   $028C  repeat delay counter           $028D  SHIFT 1, C= 2, CTRL 4
;   $91    CIA1 port B read with line 7 selected (bit 7 low = RUN/STOP down)
;   $A0-$A2 jiffy clock, big-endian, wraps at 24 hours
;
; Where this differs from the ROM (all internal):
;   - Keys are taken on press edges, from the whole matrix at once, so a key
;     pressed while another is still held is not lost.
;   - RUN/STOP and the modifier keys never enter the buffer.
;   - SHIFT+C= does not switch the character set.
;
; Called from the IRQ: it uses only A, X, Y and its own storage, never the
; kernel's scratch bytes, which the interrupted code may be using.
.include "k.inc"

.export kbd_init, kbd_scan, key_get

KEYD    = $0277
KEYMAX  = $0289
KEYREP  = $028a
KEYSPD  = $028b
KEYDLY  = $028c
KEYSHF  = $028d
KEYCUR  = $cb
KEYPRV  = $c5
KEYCNT  = $c6
STOPRAW = $91
JIFFY   = $a0

REP_DELAY = 16      ; ticks before a held key starts repeating
REP_SPEED = 4       ; ticks between repeats

CIA1_PA = $dc00
CIA1_PB = $dc01

.segment "BSS"
kb_cur:  .res 8     ; keys down in this scan, one byte per line (modifiers removed)
kb_prev: .res 8     ; the same at the previous scan
kb_rkey: .res 1     ; key being repeated ($40 = none)
kb_t:    .res 1

.segment "RODATA"
; line 1 bit 7 = left SHIFT, line 6 bit 4 = right SHIFT, line 7 bit 2 = CTRL,
; bit 5 = C=, bit 7 = RUN/STOP: not keys that produce characters
kb_mask:  .byte $ff, $7f, $ff, $ff, $ff, $ff, $ef, $5b
; modifier flags -> table (0 plain, 1 shift, 2 commodore, 3 control)
kb_tabsel: .byte 0, 1, 2, 1, 3, 3, 3, 3

.include "keytab.inc"

.segment "CODE"
kbd_init:
        ldx #7
        lda #0
@c:     sta kb_cur,x
        sta kb_prev,x
        dex
        bpl @c
        sta KEYCNT
        sta KEYSHF
        sta KEYREP
        sta JIFFY
        sta JIFFY+1
        sta JIFFY+2
        lda #$40
        sta KEYCUR
        sta KEYPRV
        sta kb_rkey
        lda #10
        sta KEYMAX
        lda #REP_SPEED
        sta KEYSPD
        lda #REP_DELAY
        sta KEYDLY
        lda #$ff
        sta STOPRAW
        rts

; key_get: take the oldest key from the buffer. A = key, or 0 if none.
; Carry clear. X and Y are preserved.
key_get:
        lda KEYCNT
        beq @none
        php
        sei
        lda KEYD
        pha                 ; the key
        txa
        pha                 ; X
        ldx #0
@s:     lda KEYD+1,x
        sta KEYD,x
        inx
        cpx KEYCNT
        bne @s
        dec KEYCNT
        pla
        tax
        pla                 ; A = key; held in a register across PLP, since
        plp                 ; an interrupt may follow it
        clc
        rts
@none:  clc
        rts

; kbd_scan: once per interrupt. Updates the jiffy clock, scans the matrix
; and queues keys.
kbd_scan:
        ; ---- jiffy clock
        inc JIFFY+2
        bne @jd
        inc JIFFY+1
        bne @jd
        inc JIFFY
@jd:    lda JIFFY
        cmp #$4f            ; 24 hours = $4F1A00 jiffies
        bne @jok
        lda JIFFY+1
        cmp #$1a
        bne @jok
        lda JIFFY+2
        cmp #$01
        bne @jok
        lda #0
        sta JIFFY
        sta JIFFY+1
        sta JIFFY+2
@jok:
        ; ---- read the matrix: line X driven low, pressed keys read as 0
        ldx #0
        lda #$fe
@line:  sta CIA1_PA
        pha
        lda CIA1_PB
        cmp CIA1_PB         ; unstable: skip this scan
        beq @stable
        jmp @bad
@stable:
        eor #$ff
        sta kb_cur,x
        pla
        sec
        rol a
        inx
        cpx #8
        bne @line
        lda #$ff
        sta CIA1_PA
        ; $91: the raw read of line 7 (RUN/STOP is bit 7, low = down)
        lda kb_cur+7
        eor #$ff
        sta STOPRAW
        ; ---- modifiers
        ldy #0
        lda kb_cur+1
        and #$80
        bne @sh
        lda kb_cur+6
        and #$10
        beq @nsh
@sh:    iny
@nsh:   lda kb_cur+7
        and #$20
        beq @nc
        iny
        iny
@nc:    lda kb_cur+7
        and #$04
        beq @nct
        tya
        ora #4
        tay
@nct:   sty KEYSHF
        ; ---- keep only keys that make characters
        ldx #7
@m:     lda kb_cur,x
        and kb_mask,x
        sta kb_cur,x
        dex
        bpl @m
        ; ---- a key pressed since the last scan?
        ldx #0
@f:     lda kb_prev,x
        eor #$ff
        and kb_cur,x
        bne @new
        inx
        cpx #8
        bne @f
        jmp @held
@new:   ldy #0              ; lowest new bit of line X
@b:     lsr a
        bcs @got
        iny
        bne @b
@got:   sty kb_t
        txa
        asl a
        asl a
        asl a
        ora kb_t            ; A = key index
        sta kb_rkey
        lda #REP_DELAY
        sta KEYDLY
        lda #REP_SPEED
        sta KEYSPD
        lda kb_rkey
        jsr kb_emit
        jmp @done
@held:  ; no new key: repeat the last one while it stays down
        lda kb_rkey
        cmp #$40
        beq @done
        pha
        and #7
        tay
        pla
        lsr a
        lsr a
        lsr a
        tax                 ; X = line, Y = bit
        lda kb_cur,x
        and bitmask,y
        beq @rel
        lda KEYDLY
        beq @rep
        dec KEYDLY
        jmp @done
@rep:   dec KEYSPD
        bne @done
        lda #REP_SPEED
        sta KEYSPD
        lda kb_rkey
        jsr kb_emit
        jmp @done
@rel:   lda #$40
        sta kb_rkey
@done:  ldx #7
@p:     lda kb_cur,x
        sta kb_prev,x
        dex
        bpl @p
        lda KEYCUR
        sta KEYPRV
        lda kb_rkey
        sta KEYCUR
        rts
@bad:   pla
        lda #$ff
        sta CIA1_PA
        rts

bitmask: .byte 1, 2, 4, 8, $10, $20, $40, $80

; kb_emit: A = key index. Decode with the current modifiers and queue the
; character (dropped if the buffer is full or the key makes nothing).
kb_emit:
        sta kb_t
        ldy KEYSHF
        lda kb_tabsel,y
        lsr a               ; table number * 64
        ror a
        ror a
        clc
        adc kb_t
        tax
        lda keytab,x
        cmp #$ff
        beq @r
        ; a first press always counts. A repeat (the delay has run out) is
        ; filtered: $80 all keys, $40 none, $00 cursor keys, DEL and SPACE only
        ldy KEYDLY
        bne @put
        ldy KEYREP
        bmi @put            ; $80: all keys
        bne @r              ; $40: none
        cmp #$20
        beq @put
        cmp #$14
        beq @put
        cmp #$94
        beq @put
        cmp #$1d
        beq @put
        cmp #$9d
        beq @put
        cmp #$11
        beq @put
        cmp #$91
        bne @r
@put:   ldx KEYCNT
        cpx KEYMAX
        bcs @r
        sta KEYD,x
        inc KEYCNT
@r:     rts
