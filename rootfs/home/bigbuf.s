; bigbuf.s - a program with a 12 KB buffer that costs nothing on disk:
;   as bigbuf.s bigbuf
;   ./bigbuf
; A .res at the very end of the source is the program's BSS: zeroed when it loads, not stored in
; the file (a .res with anything after it is still stored as zeros).
start:  lda buf+5000        ; zero at load (the kernel clears the BSS, also on a second run)
        bne bad
        lda buf+9000
        bne bad
        lda #42
        sta buf+9000
        lda buf+9000
        cmp #42
        bne bad
        lda #<okmsg
        sta r0
        lda #>okmsg
        sta r0+1
        lda #7
        sta r1
        lda #0
        sta r1+1
        lda #1              ; fd 1 = stdout
        jsr sys_write
        lda #0
        jmp sys_exit
bad:    lda #1
        jmp sys_exit
okmsg:  .byte "bss ok", 10
buf:    .res 12000
