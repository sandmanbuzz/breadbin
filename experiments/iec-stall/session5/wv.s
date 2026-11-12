; wv N PATH EVICT NREAD: session 5 arm B, one-block write-verify under Breadbin
; (docs/design/io-trial-protocol.md, "Session 5"; driver: experiments/iec-stall/session5.py).
;
; For cycle k = 1..N:
;   step 1  unlink PATH                         (ENOENT is accepted on cycle 1 only)
;   step 2  open PATH O_WRONLY|O_CREAT|O_TRUNC
;   step 3  write 254 bytes: byte i = (k*7 + i*13) & 255  (the same pattern as arm W)
;   step 4  close
;   step 5  evict: read 8 x 256 bytes of EVICT (cache on), so none of the 6 RAM block
;           buffers still holds PATH's data block
;   step 6  REU cache off for the read-back (writes keep the cache in step, so with it on
;           the read would be served from the REU, not the disk); open PATH O_RDONLY; then
;           note io_nread (the 16-bit kernel counter at address NREAD, decimal), so only the
;           data reads of step 7 can move it
; PATH must be on the boot drive: with an REU, /tmp is a RAM disk and never reaches the bus.
;   step 7  read until EOF
;   step 8  close; the cache back on if it was on
;   step 9  length must be 254            step 10  bytes must match
;   step 11 io_nread must have moved (else the read-back never reached the bus: counted in
;           nobus, reported, not a stop)   step 12  a cache syscall failed
;   step 13 the final unlink after the last cycle
; The first failure (any step but 11) stops the run. Output (screen only; no other I/O):
;   wv c=K                                  every 50 cycles
;   wv fail c=K s=STEP e=ERRNO i=INDEX g=GOT w=WANT     on a failure
;   wv end n=N ok=OK mis=MIS err=ERR nobus=NB
; Exit status 0 if mis = err = 0, else 1.
.include "breadbin.inc"   ; ca65 -I TREE/include (the release tree's)
.import argn, print, print_dec, newline, parse_dec, putc

k     = $23     ; 2: the cycle, 1-based
pth   = $25     ; 2
ev    = $27     ; 2
nr    = $29     ; 2: address of io_nread
tot   = $2b     ; 2: bytes read back
s     = $2d     ; pattern byte
fd    = $2e
t     = $2f

.segment "CODE"
        lda argc
        cmp #5
        beq @args
        lda #<usage
        ldx #>usage
        jsr print
        lda #2
        jmp SYS_EXIT
@args:  lda #1
        jsr argn
        jsr parse_dec
        sta n
        stx n+1
        lda #2
        jsr argn
        sta pth
        stx pth+1
        lda #3
        jsr argn
        sta ev
        stx ev+1
        lda #4
        jsr argn
        jsr parse_dec
        sta nr
        stx nr+1
        lda #0
        ldx #cnt_end-cnt-1
@z:     sta cnt,x
        dex
        bpl @z
        sta k
        sta k+1

cycle:  inc k
        bne :+
        inc k+1
:       lda n               ; k > n: done
        cmp k
        lda n+1
        sbc k+1
        bcs :+
        jmp finish
        ; ---- 1 unlink
:       lda #1
        sta step
        jsr setpth
        jsr SYS_UNLINK
        bcc fill
        cmp #ENOENT
        bne fail_e
        lda k+1
        bne fail_e2
        lda k
        cmp #1
        bne fail_e2
        ; ---- 2 open for writing, with the pattern ready
fill:   lda k
        asl a
        asl a
        asl a
        sec
        sbc k               ; k*7 & 255
        ldx #0
@f:     sta wbuf,x
        clc
        adc #13
        inx
        cpx #254
        bne @f
        lda #2
        sta step
        jsr setpth
        lda #O_WRONLY|O_CREAT|O_TRUNC
        jsr SYS_OPEN
        bcs fail_e
        sta fd
        ; ---- 3 write
        lda #3
        sta step
        lda #<wbuf
        sta r0
        lda #>wbuf
        sta r0+1
        lda #254
        sta r1
        lda #0
        sta r1+1
        lda fd
        jsr SYS_WRITE
        bcs fail_e
        lda r1+1
        bne @short
        lda r1
        cmp #254
        beq close1
@short: lda r1
        sta got
        lda #254
        sta want
        lda #0
        jmp fail_e
fail_e2:
        lda #ENOENT
fail_e: jmp fail
close1: lda #4
        sta step
        lda fd
        jsr SYS_CLOSE
        bcs fail_e
        ; ---- 5 evict the RAM buffers
        lda #5
        sta step
        lda ev
        sta r0
        lda ev+1
        sta r0+1
        lda #O_RDONLY
        jsr SYS_OPEN
        bcs fail_e
        sta fd
        lda #8
        sta t
@ev:    lda #<rbuf
        sta r0
        lda #>rbuf
        sta r0+1
        lda #0
        sta r1
        lda #1
        sta r1+1
        lda fd
        jsr SYS_READ
        bcs fail_e
        lda r1
        ora r1+1
        beq @eve
        dec t
        bne @ev
@eve:   lda fd
        jsr SYS_CLOSE
        bcs fail_e
        ; ---- 6 cache off, note io_nread, open for reading
        lda #12
        sta step
        jsr cstat
        bcs fail_e
        ldx #0
        lda cbuf            ; 2: attached and on
        cmp #2
        bne @noc
        lda #1
        jsr SYS_CACHE
        bcs fail_e
        ldx #1
@noc:   stx was_on          ; 1 if the cache was on (we turned it off)
        lda #6
        sta step
        jsr setpth
        lda #O_RDONLY
        jsr SYS_OPEN
        bcc :+
        jmp fail_c
:
        sta fd
        ldy #0              ; io_nread after the open: the path lookup's reads do not count
        lda (nr),y
        sta nr0
        iny
        lda (nr),y
        sta nr0+1
        ; ---- 7 read to EOF (at most 300 bytes asked for)
        lda #7
        sta step
        lda #0
        sta tot
        sta tot+1
@rd:    clc
        lda #<rbuf
        adc tot
        sta r0
        lda #>rbuf
        adc tot+1
        sta r0+1
        sec
        lda #<300
        sbc tot
        sta r1
        lda #>300
        sbc tot+1
        sta r1+1
        ora r1
        beq @rde            ; buffer full: stop, the length check fails
        lda fd
        jsr SYS_READ
        bcc :+
        jmp fail_c
:
        lda r1
        ora r1+1
        beq @rde
        clc
        lda tot
        adc r1
        sta tot
        lda tot+1
        adc r1+1
        sta tot+1
        jmp @rd
@rde:   lda #8
        sta step
        lda fd
        jsr SYS_CLOSE
        bcc :+
        jmp fail_c
:
        jsr con             ; cache back on
        bcc :+
        jmp fail_x
:
        ; ---- 9 length
        lda #9
        sta step
        lda tot+1
        bne @bl
        lda tot
        cmp #254
        beq @cmp
@bl:    lda tot
        sta got
        lda #254
        sta want
        lda #0
        jmp fail
        ; ---- 10 compare
@cmp:   lda #10
        sta step
        ldx #0
@c:     lda rbuf,x
        cmp wbuf,x
        bne @mis
        inx
        cpx #254
        bne @c
        ; ---- 11 the read-back reached the bus
        ldy #0
        lda (nr),y
        cmp nr0
        bne @ok
        iny
        lda (nr),y
        cmp nr0+1
        bne @ok
        inc nobus
        bne @ok
        inc nobus+1
@ok:    inc ok
        bne :+
        inc ok+1
:       lda k               ; progress every 50 cycles (screen only)
        sta t
        lda k+1
@m50:   ldx t               ; (k mod 50) == 0 ?
        cmp #0
        bne @sub
        cpx #50
        bcc @rem
@sub:   tay
        txa
        sec
        sbc #50
        sta t
        tya
        sbc #0
        jmp @m50
@rem:   cpx #0
        bne @nx
        lda #<s_prog
        ldx #>s_prog
        jsr print
        lda k
        ldx k+1
        jsr print_dec
        jsr newline
@nx:    jmp cycle
@mis:   stx idx
        sta got
        lda wbuf,x
        sta want
        inc mis
        bne :+
        inc mis+1
:       lda #0
        sta errno
        jmp report

; a failure with the cache possibly off: put it back first (its own error is not reported)
fail_c: sta errno
        jsr con
        lda errno
        jmp fail
fail_x: lda #12
        sta step
        lda errno
fail:   sta errno
        inc err
        bne report
        inc err+1
report: lda #<s_fail
        ldx #>s_fail
        jsr print
        lda k
        ldx k+1
        jsr print_dec
        lda #<s_s
        ldx #>s_s
        jsr print
        lda step
        jsr pdec8
        lda #<s_e
        ldx #>s_e
        jsr print
        lda errno
        jsr pdec8
        lda #<s_i
        ldx #>s_i
        jsr print
        lda idx
        jsr pdec8
        lda #<s_g
        ldx #>s_g
        jsr print
        lda got
        jsr pdec8
        lda #<s_w
        ldx #>s_w
        jsr print
        lda want
        jsr pdec8
        jsr newline
        jmp summary

finish: lda #13
        sta step
        jsr setpth
        jsr SYS_UNLINK
        bcc summary
        jmp fail
summary:
        lda #<s_end
        ldx #>s_end
        jsr print
        lda n
        ldx n+1
        jsr print_dec
        lda #<s_ok
        ldx #>s_ok
        jsr print
        lda ok
        ldx ok+1
        jsr print_dec
        lda #<s_mis
        ldx #>s_mis
        jsr print
        lda mis
        ldx mis+1
        jsr print_dec
        lda #<s_err
        ldx #>s_err
        jsr print
        lda err
        ldx err+1
        jsr print_dec
        lda #<s_nb
        ldx #>s_nb
        jsr print
        lda nobus
        ldx nobus+1
        jsr print_dec
        jsr newline
        lda mis
        ora mis+1
        ora err
        ora err+1
        beq :+
        lda #1
:       jmp SYS_EXIT

pdec8:  ldx #0
        jmp print_dec

setpth: lda pth
        sta r0
        lda pth+1
        sta r0+1
        rts

cstat:  lda #<cbuf
        sta r0
        lda #>cbuf
        sta r0+1
        lda #0
        jmp SYS_CACHE

; the cache back on if this cycle turned it off; carry set and A = errno on failure
con:    lda was_on
        beq @r
        lda #0
        sta was_on
        lda #2
        jmp SYS_CACHE
@r:     clc
        rts

.segment "RODATA"
usage:  .byte "usage: wv N PATH EVICT NREAD", 10, 0
s_prog: .byte "wv c=", 0
s_fail: .byte "wv fail c=", 0
s_s:    .byte " s=", 0
s_e:    .byte " e=", 0
s_i:    .byte " i=", 0
s_g:    .byte " g=", 0
s_w:    .byte " w=", 0
s_end:  .byte "wv end n=", 0
s_ok:   .byte " ok=", 0
s_mis:  .byte " mis=", 0
s_err:  .byte " err=", 0
s_nb:   .byte " nobus=", 0

.segment "BSS"
n:      .res 2
nr0:    .res 2
cnt:
ok:     .res 2
mis:    .res 2
err:    .res 2
nobus:  .res 2
step:   .res 1
errno:  .res 1
idx:    .res 1
got:    .res 1
want:   .res 1
was_on: .res 1
cnt_end:
cbuf:   .res 8
wbuf:   .res 256
rbuf:   .res 300
