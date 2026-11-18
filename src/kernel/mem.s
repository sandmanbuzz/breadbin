; Breadbin memory: 256-byte page allocator for the user pool
.include "k.inc"

POOL_FIRST = $08
POOL_END   = >KSTART                ; first page owned by the kernel
NPOOL      = POOL_END - POOL_FIRST


.segment "BSS"
pg_used:     .res NPOOL
free_pages:  .res 1
total_pages: .res 1
pa_n:        .res 1
pa_run:      .res 1
pa_start:    .res 1

.segment "INIT"
mem_init:
        ldx #0
        txa
@l:     sta pg_used,x
        inx
        cpx #NPOOL
        bne @l
        lda #NPOOL
        sta free_pages
        sta total_pages
        rts

; page_alloc: Y = number of pages -> A = first page (carry clear),
; or carry set (A = ENOMEM). First fit from the bottom of the pool.
; page_alloc_hi: the same, first fit from the TOP of the pool (kernel modules live there,
; out of the way of processes).
; One scan serves both: the step instruction at pa_step is patched to inx or dex (not
; reentrant; nothing allocates from an interrupt). Out of range is X >= NPOOL either way:
; up, X reaches NPOOL; down, it wraps from 0 to $FF. Y = 0 never fits (ENOMEM).
; On return X = first page index + count and Y = 0, as callers may expect.
.segment "CODE"
page_alloc:
        ldx #$ff            ; the first step takes it to 0
        lda #$e8            ; inx
        bne pa_go           ; (always)
page_alloc_hi:
        ldx #NPOOL
        lda #$ca            ; dex
pa_go:  sta pa_step
        sty pa_n
        lda #0
        sta pa_run
pa_step:
        inx                 ; patched: inx or dex
        cpx #NPOOL
        bcs @fail
        lda pg_used,x
        beq @free
        lda #0
        sta pa_run
        beq pa_step         ; (always)
@free:  inc pa_run
        lda pa_run
        cmp pa_n
        bne pa_step
        lda pa_step         ; carry is set (cmp equal); lda/and keep it
        and #$20            ; inx is $E8, dex is $CA: bit 5 tells them apart
        beq @low            ; dex: X is the lowest page of the run
        txa                 ; inx: X is the highest; lowest = X - n + 1
        sbc pa_n
        tax
        inx
@low:   stx pa_start
        ldy pa_n
        lda #1
@m:     sta pg_used,x
        inx
        dey
        bne @m
        lda free_pages
        sec
        sbc pa_n
        sta free_pages
        lda pa_start
        clc
        adc #POOL_FIRST
        clc
        rts
@fail:  lda #ENOMEM
        sec
        rts

; page_free: A = first page, Y = count
page_free:
        cpy #0
        beq @r
        sec
        sbc #POOL_FIRST
        tax
        tya
        clc
        adc free_pages
        sta free_pages
        lda #0
@l:     sta pg_used,x
        inx
        dey
        bne @l
@r:     rts

; meminfo(r0 = buf): free pages, total pages, reu banks, procs used, max procs
sys_meminfo:
        ldy #0
        lda free_pages
        sta (r0),y
        iny
        lda total_pages
        sta (r0),y
        iny
        lda reu_banks
        sta (r0),y
        ldx #MAXPROC-1
        lda #0
        sta tmp0
@c:     lda p_state,x
        beq @n
        inc tmp0
@n:     dex
        bpl @c
        iny
        lda tmp0
        sta (r0),y
        iny
        lda #MAXPROC
        sta (r0),y
        clc
        rts
