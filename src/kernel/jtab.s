; Breadbin syscall entry: the whole thing lives in the fixed page at $CF00
;
; Programs `jsr SYS_x` (SYS_BASE + 3*n). Each table entry is a `jsr enter`; the return
; address `enter` finds on the stack is that entry's last byte, $CF00 + 3*n + 2, so the
; syscall number needs no per-call stub. `enter` marks the kernel busy and calls the
; handler. Handlers return carry/A/X/r-registers; `sys_return` acts on pending signals
; and deferred reschedules before going back to user code.
.include "k.inc"
.import sys_isatty, sys_conmode, sys_getuid, sys_setuid, sys_mount, sys_umount, sys_mntinfo, sys_diskio, sys_cache

NSYS = 32               ; the page holds the table (3*NSYS), enter, sys_return and the two address tables

.segment "JUMPTAB"
.repeat NSYS
        jsr enter
.endrep

; enter: A, X, carry as the caller left them. Interrupts stay off until in_kernel is set,
; because k_a/k_x/k_p are shared.
enter:
        sei
        cld                     ; the kernel's adc/sbc are binary whatever the caller left in D
        sta k_a
        stx k_x
        php
        pla
        sta k_p
        pla                     ; low byte of the return address: 3*n + 2
        ldx #$ff
        sec
@n:     inx
        sbc #3
        bcs @n                  ; X = n
        pla                     ; high byte
        stx k_n
        lda #1
        sta in_kernel
        lda #>(sys_return-1)
        pha
        lda #<(sys_return-1)
        pha
        lda sys_hi,x
        pha
        lda sys_lo,x
        pha
        lda k_p                 ; the caller's flags back (carry in), then interrupts on, binary mode
        pha
        ldx k_x
        lda k_a
        plp
        cli
        cld
        rts

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

sys_lo: .lobytes sys_exit-1, sys_spawn-1, sys_wait-1, sys_kill-1, sys_getpid-1
        .lobytes sys_yield-1, sys_sleep-1, sys_open-1, sys_close-1, sys_read-1
        .lobytes sys_write-1, sys_pipe-1, sys_mkdir-1, sys_rmdir-1, sys_unlink-1
        .lobytes sys_rename-1, sys_chdir-1, sys_getcwd-1, sys_stat-1
        .lobytes sys_procinfo-1, sys_meminfo-1, sys_fsinfo-1, sys_time-1, sys_isatty-1, sys_conmode-1
        .lobytes sys_getuid-1, sys_setuid-1, sys_mount-1, sys_umount-1, sys_mntinfo-1, sys_diskio-1, sys_cache-1
sys_hi: .hibytes sys_exit-1, sys_spawn-1, sys_wait-1, sys_kill-1, sys_getpid-1
        .hibytes sys_yield-1, sys_sleep-1, sys_open-1, sys_close-1, sys_read-1
        .hibytes sys_write-1, sys_pipe-1, sys_mkdir-1, sys_rmdir-1, sys_unlink-1
        .hibytes sys_rename-1, sys_chdir-1, sys_getcwd-1, sys_stat-1
        .hibytes sys_procinfo-1, sys_meminfo-1, sys_fsinfo-1, sys_time-1, sys_isatty-1, sys_conmode-1
        .hibytes sys_getuid-1, sys_setuid-1, sys_mount-1, sys_umount-1, sys_mntinfo-1, sys_diskio-1, sys_cache-1
