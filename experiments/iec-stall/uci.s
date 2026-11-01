; uci: a script interpreter for measuring the Ultimate Command Interface (UCI) from the C64, with real timing.
; Python (uci.py) writes a list of operations at $4000, runs this at $C000 (SYS 49152 / by DMA), and reads the log at
; $8000 back. Standalone: no Breadbin, no KERNAL calls. Register map and DOS commands from the Ultimate documentation
; (uci/core_uci_architecture.rst, uci/ultimate_dos_target.rst); everything is polled.
;
; Operations (first byte of each; the list ends with 0):
;   1 CMD   len b0 b1 ...             send the command bytes; keep the first response and status bytes in the log
;   2 RDLOOP target chunk(2) total(2) READ DATA ($04) in chunks until total bytes arrive or the file ends; the data
;                                     is stored into a sink the way a driver would (timing includes consuming it)
;   3 CTRL  value                     write the control register; log $DF1C and $DF1D read straight after
;   4 WRFILL target chunk(2) total(2) pattern   WRITE DATA ($05) total bytes in chunks; pattern byte, or $FF = index
;   5 RDTIGHT / 6 RDBLIND: like RDLOOP, but the byte loop is a tight loop straight to a page ($4000 window, 8 KB wrapped);
;     5 still tests DATA_AV on every byte, 6 reads 512 bytes per chunk blind (use a total that is a multiple of 512)
; Log entry (64 bytes): +0 op number, +1 last $DF1C, +2..5 elapsed us (32 bits), +6..7 response bytes, +8 status bytes,
; +9 result (0 ok, 1 timeout), +10 last $DF1D, +11 commands issued, +12..35 first 24 response bytes, +36..63 first 28 status.
UCI_CTL  = $DF1C
UCI_CMD  = $DF1D
UCI_RESP = $DF1E
UCI_STAT = $DF1F

script = $4000
sink   = $5000              ; 8 KB, wrapped
logbase = $8000

sp     = $FB                ; script pointer
dp     = $F7                ; sink pointer
lp     = $F9                ; log entry pointer
wp     = $F5                ; work pointer into the log fields

ts     = $C700              ; start time, 4 bytes
te     = $C704              ; end time
tmp    = $C708              ; 4 bytes for now32
rlen   = $C710              ; response bytes, 16 bits
slen   = $C712
result = $C713
ncmd   = $C714
cmdlen = $C715
mode   = $C716              ; 0 = log the first bytes, 1 = sink
lastst = $C717
idsnap = $C724              ; $DF1D as it read the moment the data was ready (before the queues are drained)
tot    = $C718              ; 16 bits
chunk  = $C71A              ; 16 bits
target = $C71C
pat    = $C71D
opn    = $C71E
tcnt   = $C720              ; 3 byte timeout counter
done   = $C7F0
nops   = $C7F1

        .segment "CODE"
start:  lda #$FF            ; the 32-bit microsecond clock: CIA2 timer A (phi2) cascaded into timer B
        sta $DD04
        sta $DD05
        sta $DD06
        sta $DD07
        lda #$01
        sta $DD0E
        lda #$41
        sta $DD0F
        lda #0
        sta done
        sta nops
        lda #<script
        sta sp
        lda #>script
        sta sp+1
        lda #<logbase
        sta lp
        lda #>logbase
        sta lp+1
        lda #<sink
        sta dp
        lda #>sink
        sta dp+1
        lda #$04            ; abort whatever was running, then clear the error flag
        sta UCI_CTL
        jsr wait_idle
@op:    ldy #0
        lda (sp),y
        beq @end
        sta opn
        jsr log_begin
        lda opn
        cmp #1
        bne @n2
        jsr op_cmd
        jmp @next
@n2:    cmp #2
        bne @n3
        jsr op_rdloop
        jmp @next
@n3:    cmp #3
        bne @n4
        jsr op_ctrl
        jmp @next
@n4:    cmp #4
        bne @n5
        jsr op_wrfill
        jmp @next
@n5:    cmp #5
        beq @rl
        cmp #6
        bne @end
@rl:    jsr op_rdloop
@next:  jsr log_end
        inc nops
        lda lp              ; next log entry (64 bytes)
        clc
        adc #64
        sta lp
        bcc @l
        inc lp+1
@l:     jmp @op
@end:   lda #1
        sta done
        rts

; ---- the clock ------------------------------------------------------------------
now32:  lda $DD07           ; read the four counters; retry if timer B moved while we read
        sta tmp+3
        lda $DD06
        sta tmp+2
        lda $DD05
        sta tmp+1
        lda $DD04
        sta tmp
        lda $DD07
        cmp tmp+3
        bne now32
        lda $DD06
        cmp tmp+2
        bne now32
        rts

stamp_s: jsr now32
        ldx #3
@c:     lda tmp,x
        sta ts,x
        dex
        bpl @c
        rts

stamp_e: jsr now32
        ldx #3
@c:     lda tmp,x
        sta te,x
        dex
        bpl @c
        rts

; ---- the log --------------------------------------------------------------------
log_begin: ldy #63
        lda #0
@z:     sta (lp),y
        dey
        bpl @z
        lda opn
        ldy #0
        sta (lp),y
        lda #0
        sta rlen
        sta rlen+1
        sta slen
        sta result
        sta ncmd
        rts

log_end: sec                ; elapsed = start - end (the counters count down)
        lda ts
        sbc te
        ldy #2
        sta (lp),y
        lda ts+1
        sbc te+1
        iny
        sta (lp),y
        lda ts+2
        sbc te+2
        iny
        sta (lp),y
        lda ts+3
        sbc te+3
        iny
        sta (lp),y
        ldy #1
        lda lastst
        sta (lp),y
        ldy #6
        lda rlen
        sta (lp),y
        iny
        lda rlen+1
        sta (lp),y
        iny
        lda slen
        sta (lp),y
        iny
        lda result
        sta (lp),y
        iny
        lda idsnap
        sta (lp),y
        iny
        lda ncmd
        sta (lp),y
        rts

; ---- waiting --------------------------------------------------------------------
settimeout: lda #$FF
        sta tcnt
        sta tcnt+1
        lda #$20
        sta tcnt+2
        rts

tick:   dec tcnt            ; carry set when the timeout has run out
        bne @ok
        dec tcnt+1
        bne @ok
        dec tcnt+2
        bne @ok
        sec
        rts
@ok:    clc
        rts

wait_idle: jsr settimeout   ; STATE = 00; clear a stuck error flag on the way
@w:     lda UCI_CTL
        and #$08
        beq @e
        lda #$08
        sta UCI_CTL
@e:     lda UCI_CTL
        and #$30
        beq @r
        jsr tick
        bcc @w
        lda #1
        sta result
@r:     rts

; ---- one command: bytes already queued with push; read everything and accept ------
; mode 0: keep the first bytes in the log; mode 1: put the data into the sink
finish: jsr settimeout
@w:     lda UCI_CTL         ; wait for Data Last ($20) or Data More ($30)
        and #$30
        cmp #$20
        bcs @got
        jsr tick
        bcc @w
        lda #1
        sta result
        lda #$04            ; give up on this command
        sta UCI_CTL
        rts
@got:   sta lastst
        lda UCI_CMD
        sta idsnap
        lda mode
        cmp #2
        bcc @rd
        cmp #3
        beq @blind
        lda #>sink          ; mode 2: a tight loop that still checks DATA_AV on every byte
        sta @tst+2
        ldy #0
@tl:    lda UCI_CTL
        bpl @tdone
        lda UCI_RESP
@tst:   sta sink,y
        iny
        bne @tl
        inc rlen+1
        inc @tst+2
        lda @tst+2
        cmp #>sink+$20
        bcc @tl
        lda #>sink
        sta @tst+2
        jmp @tl
@tdone: tya
        clc
        adc rlen
        sta rlen
        bcc @st2
        inc rlen+1
        jmp @st2
@blind: lda #>sink          ; mode 3: no status check at all, 512 bytes (two pages) per chunk
        sta @bst+2
        ldx #2
        ldy #0
@bl:    lda UCI_RESP
@bst:   sta sink,y
        iny
        bne @bl
        inc @bst+2
        inc rlen+1
        dex
        bne @bl
        jmp @st2
@rd:    lda UCI_CTL
        bpl @st
        lda UCI_RESP
        jsr rstore
        jmp @rd
@st2:
@st:    lda UCI_CTL
        and #$40
        beq @acc
        lda UCI_STAT
        jsr sstore
        jmp @st
@acc:   lda #$02            ; DATA_ACC
        sta UCI_CTL
        lda lastst
        cmp #$30
        bne @fin
        jmp finish          ; Data More: the next chunk follows
@fin:   rts

rstore: ldx mode
        bne @sink
        ldx rlen+1          ; only the first 24 bytes go to the log
        bne @cnt
        ldx rlen
        cpx #24
        bcs @cnt
        pha
        txa
        clc
        adc #12
        tay
        pla
        sta (lp),y
        jmp @cnt
@sink:  ldy #0
        sta (dp),y
        inc dp
        bne @cnt
        inc dp+1
        ldy dp+1
        cpy #>sink+$20
        bcc @cnt
        ldy #>sink
        sty dp+1
@cnt:   inc rlen
        bne @r
        inc rlen+1
@r:     rts

sstore: ldx slen            ; the first 28 status bytes of the last command (they replace the earlier ones)
        cpx #28
        bcs @c
        pha
        txa
        clc
        adc #36
        tay
        pla
        sta (lp),y
@c:     inc slen
        rts

; ---- operations -----------------------------------------------------------------
op_cmd: jsr wait_idle
        ldy #1
        lda (sp),y
        sta cmdlen
        lda #0
        sta mode
        sta slen            ; the status of the last command only
        jsr stamp_s
        ldx cmdlen
        ldy #2
@s:     lda (sp),y
        sta UCI_CMD
        iny
        dex
        bne @s
        lda #$01
        sta UCI_CTL
        inc ncmd
        jsr finish
        jsr stamp_e
        lda cmdlen          ; advance the script pointer past this op
        clc
        adc #2
        jmp adv

op_ctrl: ldy #1
        lda (sp),y
        jsr stamp_s
        sta UCI_CTL
        lda UCI_CTL
        sta lastst
        lda UCI_CMD
        sta idsnap
        jsr stamp_e
        lda #2
        jmp adv

; READ DATA in chunks of chunk bytes until tot bytes have arrived or a command returns nothing
op_rdloop: ldy #1
        lda (sp),y
        sta target
        iny
        lda (sp),y
        sta chunk
        iny
        lda (sp),y
        sta chunk+1
        iny
        lda (sp),y
        sta tot
        iny
        lda (sp),y
        sta tot+1
        lda opn             ; op 2: mode 1 (sink with checks), op 5: mode 2 (tight, checked), op 6: mode 3 (tight, blind)
        cmp #2
        bne @m
        lda #1
        jmp @sm
@m:     sec
        sbc #3
@sm:    sta mode
        jsr wait_idle
        jsr stamp_s
@lp:    lda tot             ; remaining = tot - rlen
        sec
        sbc rlen
        sta tmp
        lda tot+1
        sbc rlen+1
        sta tmp+1
        bcc @d              ; (cannot happen) rlen > tot
        ora tmp
        beq @d              ; nothing left
        lda tmp+1           ; n = min(chunk, remaining)
        cmp chunk+1
        bcc @rem
        bne @ch
        lda tmp
        cmp chunk
        bcc @rem
@ch:    lda chunk
        sta tmp
        lda chunk+1
        sta tmp+1
@rem:   jsr wait_idle
        lda target
        sta UCI_CMD
        lda #$04
        sta UCI_CMD
        lda tmp
        sta UCI_CMD
        lda tmp+1
        sta UCI_CMD
        lda #$01
        sta UCI_CTL
        inc ncmd
        lda rlen
        pha
        lda rlen+1
        pha
        jsr finish
        pla
        cmp rlen+1
        bne @more
        pla
        cmp rlen
        bne @more2
        jmp @d              ; the command returned nothing: end of file (or an error: the status says)
@more:  pla
@more2: lda result
        bne @d
        jmp @lp
@d:     jsr stamp_e
        lda #6
        jmp adv

op_wrfill: ldy #1
        lda (sp),y
        sta target
        iny
        lda (sp),y
        sta chunk
        iny
        lda (sp),y
        sta chunk+1
        iny
        lda (sp),y
        sta tot
        iny
        lda (sp),y
        sta tot+1
        iny
        lda (sp),y
        sta pat
        lda #0
        sta mode
        jsr wait_idle
        jsr stamp_s
        lda #0
        sta tcnt            ; sent so far, 16 bits in rlen
@lp:    lda tot
        sec
        sbc rlen
        sta tmp
        lda tot+1
        sbc rlen+1
        sta tmp+1
        bcs :+
        jmp @d
:       ora tmp
        bne :+
        jmp @d
:
        lda tmp+1
        cmp chunk+1
        bcc @rem
        bne @ch
        lda tmp
        cmp chunk
        bcc @rem
@ch:    lda chunk
        sta tmp
        lda chunk+1
        sta tmp+1
@rem:   jsr wait_idle
        lda target
        sta UCI_CMD
        lda #$05
        sta UCI_CMD
        lda #0
        sta UCI_CMD
        sta UCI_CMD
        lda tmp             ; n bytes of pattern, n = tmp (16 bits)
        sta tcnt
        lda tmp+1
        sta tcnt+1
        ldx #0
@b:     lda tcnt
        ora tcnt+1
        beq @push
        lda pat
        cmp #$FF
        bne @w
        txa
@w:     sta UCI_CMD
        inx
        lda tcnt
        bne @dc
        dec tcnt+1
@dc:    dec tcnt
        jmp @b
@push:  lda #$01
        sta UCI_CTL
        inc ncmd
        jsr finish
        lda result
        bne @d
        clc                 ; account for the bytes written (not read back)
        lda rlen
        adc tmp
        sta rlen
        lda rlen+1
        adc tmp+1
        sta rlen+1
        jmp @lp
@d:     jsr stamp_e
        lda #7
        jmp adv

adv:    clc                 ; sp += A
        adc sp
        sta sp
        bcc @r
        inc sp+1
@r:     rts
