; Breadbin kernel: ROM pool — "poach pieces" of the C64 ROM
;
; The qkumba-style insight: ROM is not just entry points. It's a pool
; of useful bytes (data tables, instruction sequences, constants) that
; can be accessed on demand.
;
; The C64 bank register at $01:
;   Bit 7: BASIC ROM  (0=in  $C000-$DFFF, 1=out  -> RAM)
;   Bit 6: KERNAL ROM (0=in  $E000-$FFFF, 1=out  -> RAM)
;   Bit 5: I/O        (0=RAM  $A000-$BFFF, 1=I/O)
;
; Current kernel bank: $35 = BASIC IN, KERNAL OUT, I/O IN
;
; Kernel layout:
;   CODE:     $A300-$CF00  (below BASIC ROM, safe from both ROMs)
;   JUMPTAB:  $CF00-$D000  (overlaps BASIC ROM $C000-$DFFF)
;   BSS:      $E000-$FFFA  (overlaps KERNAL ROM $E000-$FFFF)
;
; BASIC ROM ($C000-$DFFF) — already paged in:
;   Read $C000-$CF00 freely (3840 bytes, not shadowed by jump table)
;   Read $D000-$DFFF only if we back up jump table first
;   Overhead to read full 8KB: ~768 cycles (256B backup + restore)
;   Contains: character set, PETSCII mappings, BASIC string functions
;
; KERNAL ROM ($E000-$FFFF) — paged out (RAM):
;   Access: back up BSS (8192B), clear bit 6 of $01, read ROM
;   Constraint: BSS at $E000-$FFFA overlaps; back up first
;   Overhead: ~49K cycles (8192B backup + restore)
;   Contains: I/O routines, string ops, memory management, disk I/O

.include "k.inc"

.ifdef ROMPOOL

.importzp p1, p2
.import __JUMPTAB_RUN__, __JUMPTAB_SIZE__

; ROM pool shadow page: first page of user pool ($0800-$08FF)
ROMPOOL_SHADOW = $0800

.export rompool_init, rompool_kernal_in, rompool_kernal_out
.export rompool_read_kernal, rompool_basic_read
.export rompool_read_basic_safe

; ROM pool BSS state: goes into the BSS segment (overlaps KERNAL ROM area)
.segment "BSS"
rompool_active: .res 1    ; 1 = KERNAL ROM paged in, 0 = out

; ROM pool code: goes into its own ROMPOOL segment (in KRAM, not KHI)
.segment "ROMPOOL"

; ---------------------------------------------------------------------
; rompool_init: initialize ROM pool
; ---------------------------------------------------------------------
rompool_init:
        lda #0
        sta rompool_active
        rts

; ---------------------------------------------------------------------
; rompool_kernal_in: page in the KERNAL ROM
;   Backs up BSS to shadow page, clears bit 6 of $01
;   Must be called with interrupts off (sei)
;   Returns: carry clear = success
;
; The KERNAL ROM is at $E000-$FFFF. The BSS table lives at $E000-$FFFA.
; When the KERNAL ROM is paged in, the BSS is shadowed.
; We back up the BSS to the shadow page, then page in the KERNAL ROM.
; ---------------------------------------------------------------------
rompool_kernal_in:
        ; Set up pointer to BSS start
        lda #$00
        sta p1
        lda #$E0
        sta p1+1                ; p1 = $E000

        ; Set up pointer to shadow page
        lda #<ROMPOOL_SHADOW
        sta p2
        lda #>ROMPOOL_SHADOW
        sta p2+1                ; p2 = $0800

        ; Copy 8192 bytes (32 pages): BSS -> shadow
        ldx #32
@bss_backup_loop:
        ldy #0
@bss_page:
        lda (p1),y
        sta (p2),y
        iny
        bne @bss_page
        inc p1+1
        inc p2+1
        dex
        bne @bss_backup_loop

        ; Page in KERNAL ROM (clear bit 6 of $01)
        ; $35 -> $15: clear bit 6
        lda #$15
        sta $01

        lda #1
        sta rompool_active
        clc
        rts

; ---------------------------------------------------------------------
; rompool_kernal_out: page out the KERNAL ROM
;   Restores BSS from shadow, sets bit 6 of $01
;   Returns: carry clear = success
; ---------------------------------------------------------------------
rompool_kernal_out:
        sei

        ; Set up pointers
        lda #$00
        sta p1
        lda #$E0
        sta p1+1                ; p1 = $E000

        lda #<ROMPOOL_SHADOW
        sta p2
        lda #>ROMPOOL_SHADOW
        sta p2+1                ; p2 = $0800

        ; Copy 8192 bytes (32 pages): shadow -> BSS
        ldx #32
@bss_restore_loop:
        ldy #0
@bss_page_restore:
        lda (p2),y
        sta (p1),y
        iny
        bne @bss_page_restore
        inc p1+1
        inc p2+1
        dex
        bne @bss_restore_loop

        ; Page out KERNAL ROM (set bit 6 of $01)
        ; $15 -> $35: set bit 6
        lda #$35
        sta $01

        lda #0
        sta rompool_active
        clc
        rts

; ---------------------------------------------------------------------
; rompool_read_kernal: read N bytes from KERNAL ROM into r0
;   A = count (1-255)
;   r0 = destination buffer (in user pool)
;   Requires: KERNAL ROM paged in (rompool_kernal_in called)
;   Returns: carry clear = success
;
; Reads from $E000-$FFFF (KERNAL ROM) into user buffer.
; Use this to "poach" useful bytes from the ROM.
; ---------------------------------------------------------------------
rompool_read_kernal:
        tay                     ; save count in Y
        ldx #0
@kern_read:
        lda $E000,x             ; read from KERNAL ROM
        sta (r0),y
        iny
        inx
        dey
        bne @kern_read
        bpl @kern_read          ; count = 255: dey wraps to $FF

        clc
        rts

; ---------------------------------------------------------------------
; rompool_basic_read: read bytes from BASIC ROM while paged in
;   A = count (1-255)
;   r0 = destination buffer
;   Returns: count bytes from BASIC ROM at $C000-$C000+A-1
;
; The BASIC ROM is already paged in. We can read from it directly
; without any bank switching.
; ---------------------------------------------------------------------
rompool_basic_read:
        tay
        ldx #0
@basic_read:
        lda $C000,x             ; read from BASIC ROM
        sta (r0),y
        iny
        inx
        dey
        bne @basic_read
        bpl @basic_read

        clc
        rts

; ---------------------------------------------------------------------
; rompool_read_basic_safe: read bytes from BASIC ROM below jump table
;   A = count (1-3840)
;   r0 = destination buffer
;   Returns: count bytes from BASIC ROM at $C000
;
; Reads from $C000-$CF00 (3840 bytes) which is NOT shadowed by the
; jump table. No backup needed — the BASIC ROM is already paged in.
; This gives us access to character set, PETSCII mappings, and other
; useful data tables in the BASIC ROM.
; ---------------------------------------------------------------------
rompool_read_basic_safe:
        tay                     ; save count
        ldx #0
@basic_safe_read:
        lda $C000,x             ; read from BASIC ROM
        sta (r0),y
        iny
        inx
        dey
        bne @basic_safe_read
        bpl @basic_safe_read

        clc
        rts

.endif
