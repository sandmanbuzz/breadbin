; Ported from upstream Breadbin (https://github.com/kpatr1981/breadbin, MIT; Copyright 2026 Konstantinos Patronas),
; tetris.s by Elena (upstream commit 246ec88; "vibed by Lenu").
; Adapted: the library calls are ours (.import print, putc, print_dec instead of the SYS_PRINT family),
; and the PRNG is seeded from SYS_TIME (jiffies), as this system has no wall clock call.
; tetris.s: basic terminal Tetris for Unix Breadbin
; Uses ESC = row+32 col+32 cursor positioning (no direct screen write)
;
; Keys: a/left = left, d/right = right, w/up = rotate, s/down = step down,
;       space = hard drop, q = quit
; Pieces fall by themselves (GRAV_TICKS); each type has its own glyph.

.include "../../include/breadbin.inc"
.import print, putc, print_dec

.segment "CODE"

BOARD_W     = 10
BOARD_H     = 20
BOARD_TOP   = 2
BOARD_LEFT  = 14
SCORE_ROW   = 2
SCORE_COL   = 28

KBNDX       = $c6       ; KERNAL: keys in the keyboard buffer (only read)
JIFFY       = $a2       ; KERNAL: low byte of the jiffy clock (60 Hz, only read)
GRAV_TICKS  = 30        ; jiffies per automatic step down (30 = 0.5 s)

; Zero-page scratch ($23-$2F is free for user programs)
ptr1        = $23       ; 2 bytes
ptr2        = $25       ; 2 bytes
tmp_row     = $27
tmp_col     = $28
cur_piece   = $29       ; 0..6
cur_rot     = $2a       ; 0..3
cur_x       = $2b       ; signed, -2..BOARD_W
cur_y       = $2c       ; 0..BOARD_H
rng_state   = $2d       ; 1 byte (must never be 0)
loop_i      = $2f

start:
        ; Seed the PRNG from the clock (falls back to a constant)
        lda #$a5
        sta rng_state
        jsr SYS_TIME        ; seed from the jiffy clock
        ora #1              ; never zero
        sta rng_state
@seeded:

        ; Enable raw terminal input so single keys take effect immediately
        lda #1
        jsr SYS_CONMODE

        ; Clear screen
        lda #K_CLR
        jsr putc

        jsr clear_board
        jsr draw_frame
        jsr draw_score
        jsr spawn_piece
        jsr draw_piece
        lda JIFFY
        sta last_tick

main_loop:
        ; Never block in read: only read a key when the KERNAL buffer has one.
        lda KBNDX
        bne @key
        jsr SYS_YIELD       ; idle: let other processes run
        lda JIFFY
        sec
        sbc last_tick       ; elapsed jiffies (wraps correctly mod 256)
        cmp #GRAV_TICKS
        bcc main_loop
        jmp move_down       ; gravity tick
@key:   jsr read_key        ; A = key code
        cmp #'q'
        beq @quit
        cmp #'Q'
        beq @quit
        cmp #'a'
        beq @left
        cmp #K_LEFT
        beq @left
        cmp #'d'
        beq @right
        cmp #K_RIGHT
        beq @right
        cmp #'s'
        beq @down
        cmp #K_DOWN
        beq @down
        cmp #'w'
        beq @rot
        cmp #K_UP
        beq @rot
        cmp #' '
        beq @drop
        jmp main_loop
; (the handlers are out of branch range, so go through jmp)
@quit:  jmp quit_game
@left:  jmp move_left
@right: jmp move_right
@down:  jmp move_down
@rot:   jmp rotate_cw
@drop:  jmp hard_drop

move_left:
        jsr erase_piece
        dec cur_x
        jsr check_collision
        bcc @ok
        inc cur_x
@ok:    jsr draw_piece
        jmp main_loop

move_right:
        jsr erase_piece
        inc cur_x
        jsr check_collision
        bcc @ok
        dec cur_x
@ok:    jsr draw_piece
        jmp main_loop

move_down:
        lda JIFFY
        sta last_tick       ; restart the gravity timer
        jsr erase_piece
        inc cur_y
        jsr check_collision
        bcc @ok
        dec cur_y
        jsr draw_piece
        jsr settle          ; carry set = game over
        bcs @over
        jmp main_loop
@over:  jmp quit_game
@ok:    jsr draw_piece
        jmp main_loop

rotate_cw:
        jsr erase_piece
        lda cur_rot
        pha
        clc
        adc #1
        and #3
        sta cur_rot
        jsr check_collision
        pla                 ; (pla leaves carry alone)
        bcc @ok
        sta cur_rot         ; collided: restore old rotation
@ok:    jsr draw_piece
        jmp main_loop

hard_drop:
        lda JIFFY
        sta last_tick
        jsr erase_piece
@drop:  inc cur_y
        jsr check_collision
        bcc @drop
        dec cur_y
        jsr draw_piece
        jsr settle
        bcs @over
        jmp main_loop
@over:  jmp quit_game

quit_game:
        lda #BOARD_TOP+10
        ldx #BOARD_LEFT+1
        jsr goto_xy
        lda #<msg_over
        ldx #>msg_over
        jsr print

        lda #0
        jsr SYS_CONMODE

        lda #BOARD_TOP+22
        ldx #0
        jsr goto_xy

        lda #0
        jsr SYS_EXIT

; settle: current piece has landed. Lock it, clear lines, spawn the next.
; Returns carry set if the new piece does not fit (game over).
settle:
        jsr lock_piece
        lda #0
        sta cleared
        jsr clear_lines
        lda cleared
        beq @nd
        jsr draw_board
        jsr draw_score
@nd:    jsr spawn_piece
        jsr check_collision
        bcs @over
        jsr draw_piece
        clc
@over:  rts

; ----------------------------------------------------------------------
; Terminal helpers (ESC = row+32 col+32)
; ----------------------------------------------------------------------

; goto_xy: A = row (0..24), X = col (0..39)
goto_xy:
        sta tmp_row
        stx tmp_col
        lda #ESC
        jsr putc
        lda #'='
        jsr putc
        lda tmp_row
        clc
        adc #32
        jsr putc        ; row + 32
        lda tmp_col
        clc
        adc #32
        jmp putc        ; col + 32

; draw_cell: A = row, X = col, Y = 0 (empty) or piece+1 (1..7)
; Each piece type has its own ASCII glyph (see glyphs).
draw_cell:
        sty ptr2
        jsr goto_xy
        ldy ptr2
        lda glyphs,y
        jmp putc

; read_key: read 1 byte from stdin (fd 0) -> A ('q' on error/EOF)
read_key:
        lda #<key_buf
        sta r0
        lda #>key_buf
        sta r0+1
        lda #1
        sta r1
        lda #0
        sta r1+1
        lda #0              ; fd 0 = stdin
        jsr SYS_READ
        bcs @eof
        lda key_buf
        rts
@eof:   lda #'q'
        rts

; ----------------------------------------------------------------------
; Board & rendering
; ----------------------------------------------------------------------

clear_board:
        ldx #0
        txa
@l:     sta board,x
        inx
        cpx #BOARD_W * BOARD_H
        bne @l
        sta score
        sta score+1
        rts

draw_frame:
        ; Top border
        lda #BOARD_TOP-1
        ldx #BOARD_LEFT-1
        jsr goto_xy
        lda #'+'
        jsr putc
        lda #BOARD_W
        sta loop_i          ; (counter in memory: syscalls may trash X)
@top:   lda #'-'
        jsr putc
        dec loop_i
        bne @top
        lda #'+'
        jsr putc

        ; Side walls
        lda #0
        sta loop_i
@side:  lda loop_i
        clc
        adc #BOARD_TOP
        ldx #BOARD_LEFT-1
        jsr goto_xy
        lda #'|'
        jsr putc
        lda loop_i
        clc
        adc #BOARD_TOP
        ldx #BOARD_LEFT+BOARD_W
        jsr goto_xy
        lda #'|'
        jsr putc
        inc loop_i
        lda loop_i
        cmp #BOARD_H
        bne @side

        ; Bottom border
        lda #BOARD_TOP+BOARD_H
        ldx #BOARD_LEFT-1
        jsr goto_xy
        lda #'+'
        jsr putc
        lda #BOARD_W
        sta loop_i
@bot:   lda #'-'
        jsr putc
        dec loop_i
        bne @bot
        lda #'+'
        jmp putc

draw_board:
        lda #0
        sta b_row
@row:   lda #0
        sta b_col
@col:   lda b_row
        ldx b_col
        jsr board_get
        tay
        lda b_row
        clc
        adc #BOARD_TOP
        pha
        lda b_col
        clc
        adc #BOARD_LEFT
        tax
        pla
        ; A = row, X = col, Y = cell
        jsr draw_cell
        inc b_col
        lda b_col
        cmp #BOARD_W
        bne @col
        inc b_row
        lda b_row
        cmp #BOARD_H
        bne @row
        rts

draw_score:
        lda #SCORE_ROW
        ldx #SCORE_COL
        jsr goto_xy
        lda #<msg_score
        ldx #>msg_score
        jsr print
        lda score
        ldx score+1
        jmp print_dec

; ----------------------------------------------------------------------
; Piece logic
; ----------------------------------------------------------------------

spawn_piece:
@r:     jsr next_rand
        and #7
        cmp #7
        bcs @r              ; reject 7 so all pieces are equally likely
        sta cur_piece
        lda #0
        sta cur_rot
        lda #3
        sta cur_x
        lda #0
        sta cur_y
        rts

draw_piece:
        ldy cur_piece
        iny                 ; cell value = piece + 1 (0 = empty)
        jmp plot_piece

erase_piece:
        ldy #0
        jmp plot_piece

; cell_x: X = table index of cell loop_i of the current piece/rotation
;         (piece*16 + rot*4 + loop_i)
cell_x:
        lda cur_piece
        asl a
        asl a
        asl a
        asl a
        sta ptr1
        lda cur_rot
        asl a
        asl a
        clc
        adc ptr1
        adc loop_i
        tax
        rts

; plot_piece: Y = 0 (erase) or piece+1 (draw)
plot_piece:
        sty ptr2+1
        lda #0
        sta loop_i
@i:     jsr cell_x
        lda cur_y
        clc
        adc cell_dy,x
        cmp #BOARD_H
        bcs @skip
        sta tmp_row
        lda cur_x
        clc
        adc cell_dx,x
        cmp #BOARD_W        ; negative x looks >= 128, so it is skipped too
        bcs @skip
        sta tmp_col
        lda tmp_row
        clc
        adc #BOARD_TOP
        pha
        lda tmp_col
        clc
        adc #BOARD_LEFT
        tax
        pla
        ldy ptr2+1
        jsr draw_cell
@skip:  inc loop_i
        lda loop_i
        cmp #4
        bne @i
        rts

check_collision:
        ; Returns Carry=1 on collision, Carry=0 if clear
        lda #0
        sta loop_i
@i:     jsr cell_x
        lda cur_x
        clc
        adc cell_dx,x
        bmi @hit
        cmp #BOARD_W
        bcs @hit
        sta tmp_col

        lda cur_y
        clc
        adc cell_dy,x
        bmi @hit
        cmp #BOARD_H
        bcs @hit
        sta tmp_row

        lda tmp_row
        ldx tmp_col
        jsr board_get
        bne @hit
        inc loop_i
        lda loop_i
        cmp #4
        bne @i
        clc
        rts
@hit:   sec
        rts

lock_piece:
        lda #0
        sta loop_i
@i:     jsr cell_x
        lda cur_y
        clc
        adc cell_dy,x
        sta tmp_row
        lda cur_x
        clc
        adc cell_dx,x
        sta tmp_col
        lda tmp_row
        ldx tmp_col
        jsr board_set
        inc loop_i
        lda loop_i
        cmp #4
        bne @i
        rts

; clear_lines: remove every full row (bottom to top), shifting the rows
; above down, add 1 to score per row and count them in `cleared`.
clear_lines:
        lda #BOARD_H-1
        sta b_row
@row:   lda b_row
        ldx #0
        jsr board_idx       ; Y = b_row * BOARD_W
        sty base
        ldx #0
@chk:   txa
        clc
        adc base
        tay
        lda board,y
        beq @next_row       ; hole: row not full
        inx
        cpx #BOARD_W
        bne @chk

        ; Full row: score it
        inc score
        bne @s1
        inc score+1
@s1:    inc cleared

        ; Shift rows 0..b_row-1 down by one row
        ldy base
        beq @clr
@sh:    dey
        lda board,y
        sta board+BOARD_W,y
        tya
        bne @sh
@clr:   ldx #BOARD_W-1
        lda #0
@c:     sta board,x
        dex
        bpl @c
        jmp @row            ; same row now holds new data: check it again

@next_row:
        dec b_row
        bmi @done
        jmp @row
@done:  rts

; board_idx: A = row, X = col -> Y = row*BOARD_W + col
board_idx:
        stx ptr1            ; col
        sta ptr1+1          ; row
        asl a
        sta ptr2            ; row*2
        lda ptr1+1
        asl a
        asl a
        asl a               ; row*8
        clc
        adc ptr2            ; row*10
        clc
        adc ptr1
        tay
        rts

; board_get: A = row, X = col -> A = cell (0 = empty, else piece+1), Z set if empty
board_get:
        jsr board_idx
        lda board,y
        rts

; board_set: A = row, X = col -> sets board cell to piece+1
board_set:
        jsr board_idx
        lda cur_piece
        clc
        adc #1
        sta board,y
        rts

; 8-bit Galois LFSR (period 255), A = new value
next_rand:
        lda rng_state
        asl a
        bcc @ok
        eor #$1d
@ok:    sta rng_state
        rts

; ----------------------------------------------------------------------
; Data
; ----------------------------------------------------------------------

msg_score:  .byte "SCORE: ", 0
msg_over:   .byte "GAME OVER", 0

; Glyph for each cell value: empty, then I O T S Z J L
glyphs:     .byte ' ', '#', 'O', '@', '%', '&', '*', '='

; Cell offsets inside a 4x4 box. Index = piece*16 + rot*4 + cell.
; Pieces: I O T S Z J L
cell_dx:
        .byte 0,1,2,3,  2,2,2,2,  0,1,2,3,  1,1,1,1     ; I
        .byte 1,2,1,2,  1,2,1,2,  1,2,1,2,  1,2,1,2     ; O
        .byte 1,0,1,2,  1,1,2,1,  0,1,2,1,  1,0,1,1     ; T
        .byte 1,2,0,1,  1,1,2,2,  1,2,0,1,  0,0,1,1     ; S
        .byte 0,1,1,2,  2,1,2,1,  0,1,1,2,  1,0,1,0     ; Z
        .byte 0,0,1,2,  1,2,1,1,  0,1,2,2,  1,1,0,1     ; J
        .byte 2,0,1,2,  1,1,1,2,  0,1,2,0,  0,1,1,1     ; L
cell_dy:
        .byte 1,1,1,1,  0,1,2,3,  2,2,2,2,  0,1,2,3     ; I
        .byte 0,0,1,1,  0,0,1,1,  0,0,1,1,  0,0,1,1     ; O
        .byte 0,1,1,1,  0,1,1,2,  1,1,1,2,  0,1,1,2     ; T
        .byte 0,0,1,1,  0,1,1,2,  1,1,2,2,  0,1,1,2     ; S
        .byte 0,0,1,1,  0,1,1,2,  1,1,2,2,  0,1,1,2     ; Z
        .byte 0,1,1,1,  0,0,1,2,  1,1,1,2,  0,1,2,2     ; J
        .byte 0,1,1,1,  0,1,2,2,  1,1,1,2,  0,0,1,2     ; L

b_row:      .byte 0
b_col:      .byte 0
base:       .byte 0
cleared:    .byte 0
last_tick:  .byte 0
key_buf:    .byte 0
clk_buf:    .res 4
score:      .word 0
board:      .res BOARD_W * BOARD_H