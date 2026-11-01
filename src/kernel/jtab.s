; Breadbin syscall entry: the table, `enter` and the per-call address records live in the
; fixed page at $CF00
;
; Programs `jsr SYS_x` (SYS_BASE + 3*n). Each table entry is a `jsr enter`; the return address
; `enter` finds on the stack is that entry's last byte, $CF00 + 3*n + 2, so its low byte
; indexes the address record (3 bytes per call, same stride as the table) directly: no
; division, no per-call stub, and the caller's carry is never touched. `enter` marks the kernel
; busy and calls the handler. Handlers return carry/A/X/r-registers; `sys_return` acts on
; pending signals and deferred reschedules before going back to user code.
.include "k.inc"
.import sys_isatty, sys_conmode, sys_getuid, sys_setuid, sys_mount, sys_umount, sys_mntinfo, sys_diskio, sys_cache

NSYS = 32               ; the page holds 3*NSYS (table) + 3*NSYS (records) + enter (about 36 bytes)

.segment "JUMPTAB"
.repeat NSYS
        jsr enter
.endrep

; enter: A, X, carry as the caller left them. Interrupts stay off until in_kernel is set,
; because k_a/k_x are shared.
enter:
        sei
        cld                     ; the kernel's adc/sbc are binary whatever the caller left in D
        sta k_a
        stx k_x
        pla                     ; low byte of the return address: 3*n + 2
        tax
        pla                     ; high byte
        lda #1
        sta in_kernel
        lda #>(sys_return-1)
        pha
        lda #<(sys_return-1)
        pha
        lda records-1,x         ; record n is at records + 3*n, X = 3*n + 2
        pha
        lda records-2,x
        pha
        ldx k_x
        lda k_a
        cli
        rts

; handler address - 1 (for rts), one 3-byte record per call
records:
        .word sys_exit-1
        .byte 0
        .word sys_spawn-1
        .byte 0
        .word sys_wait-1
        .byte 0
        .word sys_kill-1
        .byte 0
        .word sys_getpid-1
        .byte 0
        .word sys_yield-1
        .byte 0
        .word sys_sleep-1
        .byte 0
        .word sys_open-1
        .byte 0
        .word sys_close-1
        .byte 0
        .word sys_read-1
        .byte 0
        .word sys_write-1
        .byte 0
        .word sys_pipe-1
        .byte 0
        .word sys_mkdir-1
        .byte 0
        .word sys_rmdir-1
        .byte 0
        .word sys_unlink-1
        .byte 0
        .word sys_rename-1
        .byte 0
        .word sys_chdir-1
        .byte 0
        .word sys_getcwd-1
        .byte 0
        .word sys_stat-1
        .byte 0
        .word sys_procinfo-1
        .byte 0
        .word sys_meminfo-1
        .byte 0
        .word sys_fsinfo-1
        .byte 0
        .word sys_time-1
        .byte 0
        .word sys_isatty-1
        .byte 0
        .word sys_conmode-1
        .byte 0
        .word sys_getuid-1
        .byte 0
        .word sys_setuid-1
        .byte 0
        .word sys_mount-1
        .byte 0
        .word sys_umount-1
        .byte 0
        .word sys_mntinfo-1
        .byte 0
        .word sys_diskio-1
        .byte 0
        .word sys_cache-1
        .byte 0

.segment "CODE"
sys_return:
        php
        sei
        pha
        txa
        pha
        jsr check_signal
        lda need_resched
        beq @out
        lda #0
        sta need_resched
        jsr sched
        jsr check_signal
@out:   lda #0
        sta in_kernel
        pla
        tax
        pla
        plp
        rts
