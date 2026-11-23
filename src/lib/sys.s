; Breadbin user library: the two syscalls with a library name
.include "../../include/breadbin.inc"
.export exit, write_buf

.segment "CODE"
exit:   jmp SYS_EXIT

; write_buf: A = fd, r0/r1 set
write_buf:
        jmp SYS_WRITE
