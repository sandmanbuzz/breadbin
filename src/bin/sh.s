; sh: the Breadbin shell
;
;   cmd args...            run /bin/cmd (or a path containing '/')
;   a | b | c              pipelines
;   < file  > file  >> file
;   cmd &                  background job
;   a ; b                  sequence
;   "quoted words", # comments
; Built-ins: cd, exit, kill (also /bin/kill), jobs. `sh file` runs a script.
; Words with * or ? are expanded against the directory they name.
; On the console, lines are edited in raw mode: DEL, CTRL-D, and CTRL-I (TAB)
; completes a command or file name (see readline).
.include "../../include/breadbin.inc"
.import print, eprint, putc, newline, print_dec, perr, argn, strlen, exit, parse_dec, dec_str
.importzp lp1, lp2

MAXTOK  = 32
MAXARG  = 16
LINEMAX = 127
HISTN   = 4                 ; lines of history kept on the console

zp1 = $23
zp2 = $25

T_WORD  = 0
T_AND   = $80
T_OR    = $81
T_DOLLAR = $82

.segment "BSS"
in_fd:   .res 1
interactive: .res 1
ipos:    .res 1
ilen:    .res 1
ibuf:    .res 256
line:    .res LINEMAX+1
lnlen:   .res 1
tbuf:    .res 256
tlo:     .res MAXTOK
thi:     .res MAXTOK
ttype:   .res MAXTOK
ntok:    .res 1
av:      .res 2*(MAXARG+1)
nargs:   .res 1
cmdpath: .res 64
pids:    .res 8
npids:   .res 1
cmd_end: .res 1
cur_tok: .res 1
st_start: .res 1
first:   .res 1
last:    .res 1
bg:      .res 1
prev_in: .res 1
pin:     .res 1
pout:    .res 1
pr:      .res 1
inf_lo:  .res 1
inf_hi:  .res 1
outf_lo: .res 1
outf_hi: .res 1
outapp:  .res 1
cwd:     .res 64
tmpb:    .res 1
qch:     .res 1
bk_sig:  .res 1
bk_i:    .res 1
bk_p:    .res 2
pinfo:   .res 16
g_tok:   .res 1
g_word:  .res 2
g_d:     .res 1
g_dir:   .res 48
g_fd:    .res 1
g_n:     .res 1
g_ent:   .res 16
g_p:     .res 1
g_s:     .res 1
g_star:  .res 1
g_ss:    .res 1
gpos:    .res 2
gbuf:    .res 256
tpos:    .res 1
tty:     .res 1         ; interactive on the console: edit lines in raw mode
kbuf:    .res 1
tsave:   .res 1
xsave:   .res 1
tlen:    .res 1
; history ring (console only): HISTN slots of LINEMAX+1 bytes
hist:    .res HISTN*(LINEMAX+1)
hlen:    .res HISTN
hhead:   .res 1             ; slot the next line goes into
hcount:  .res 1             ; lines held, up to HISTN
hpos:    .res 1             ; 0 = the line being typed, n = n lines back
hsn:     .res 1             ; slot index for hslot
hctr:    .res 1             ; print counter (putc may clobber X and Y)
; exit status of last command ($?)
last_status: .res 1

.segment "CODE"
start:
        lda #0
        sta in_fd
        sta ipos
        sta ilen
        sta hhead
        sta hcount
        lda #1
        sta interactive
        lda #0
        sta tty
        lda #0
        jsr SYS_ISATTY      ; carry clear: fd 0 is the console
        bcs @nt
        inc tty
@nt:    lda argc
        cmp #2
        bcc main
        lda #1
        jsr argn
        sta r0
        stx r0+1
        lda #O_RDONLY
        jsr SYS_OPEN
        bcc @ok
        sta tmpb
        lda #1
        jsr argn
        pha
        txa
        tay
        pla
        tax
        lda tmpb
        jsr perr
        lda #1
        jmp exit
@ok:    sta in_fd
        lda #0
        sta interactive
        sta tty

main:   lda interactive
        beq @noprompt
        jsr reap
        jsr prompt
@noprompt:
        jsr getline
        bcc @have
        lda #0
        jmp exit
@have:  jsr tokenize
        bcs main
        jsr run_line
        jmp main

; ---- prompt and job reaping ----
prompt:
        lda #<cwd
        sta r0
        lda #>cwd
        sta r0+1
        lda #64
        jsr SYS_GETCWD
        lda #<cwd
        ldx #>cwd
        jsr print
        lda #<s_prompt
        ldx #>s_prompt
        jmp print

reap:   lda #$ff
        ldx #W_NOHANG
        jsr SYS_WAIT
        bcs @r
        cmp #0
        beq @r
        pha
        lda #'['
        jsr putc
        pla
        ldx #0
        jsr print_dec
        lda #<s_done
        ldx #>s_done
        jsr print
        jmp reap
@r:     rts

; ---- input ----
; getline: next line from in_fd into `line` (NUL-terminated, no newline)
; carry set on EOF with nothing read
getline:
        lda tty
        beq @buf
        jmp readline
@buf:   lda #0
        sta lnlen
@loop:  lda ipos
        cmp ilen
        bne @ch
        lda #<ibuf
        sta r0
        lda #>ibuf
        sta r0+1
        lda #255
        sta r1
        lda #0
        sta r1+1
        lda in_fd
        jsr SYS_READ
        lda #0
        sta ipos
        bcs @eof
        lda r1
        sta ilen
        bne @ch
@eof:   lda #0
        sta ilen
        lda lnlen
        bne @end
        sec
        rts
@ch:    ldx ipos
        inc ipos
        lda ibuf,x
        cmp #10
        beq @end
        ldx lnlen
        cpx #LINEMAX
        bcs @loop
        sta line,x
        inc lnlen
        jmp @loop
@end:   ldx lnlen
        lda #0
        sta line,x
        clc
        rts

; ---- readline (raw console input), TAB completion ----
; TAB completion of command and file names (complete, is_sep, addch) is
; adapted from upstream commit 4abb291 "feat: CTRL-I (TAB) in the shell
; completes command and file names", Konstantinos Patronas, 2026,
; https://github.com/kpatr1981/breadbin (MIT: Copyright (c) 2026 Konstantinos
; Patronas; the repo's LICENSE at that commit). Adapted to this tree's glob;
; the readline around it is our own, without history.
;
; readline: a line from the console, edited in raw mode: DEL, CTRL-I (TAB)
; completes, CTRL-D (or a read error) on an empty line is EOF (carry set)
readline:
        lda #1
        jsr SYS_CONMODE
        lda #0
        sta lnlen
        sta hpos
@key:   jsr rawkey
        bcs @eof
        cmp #K_RET
        beq @ret
        cmp #K_DEL
        beq @del
        cmp #4              ; CTRL-D
        beq @d
        cmp #K_TAB
        beq @tab
        cmp #K_UP
        beq @up
        cmp #K_DOWN
        beq @down
        cmp #$20
        bcc @key
        cmp #$7f
        bcs @key
        jsr addch
        jmp @key
@tab:   jsr complete
        jmp @key
@up:    lda hpos
        cmp hcount
        bcs @key            ; the oldest line is showing
        inc hpos
        jsr hshow
        jmp @key
@down:  lda hpos
        beq @key            ; the line being typed is showing
        dec hpos
        jsr hshow
        jmp @key
@del:   lda lnlen
        beq @key
        dec lnlen
        lda #K_DEL
        jsr putc
        jmp @key
@d:     lda lnlen
        bne @key
@eof:   lda #0
        jsr SYS_CONMODE
        sec
        rts
@ret:   jsr newline
        lda lnlen
        beq @nh
        jsr hsave
@nh:    lda #0
        jsr SYS_CONMODE
        ldx lnlen
        lda #0
        sta line,x
        clc
        rts

; history: hsave puts the line just read into the next slot.
hsave:  lda hhead
        jsr hslot
        ldy #0
@c:     cpy lnlen
        beq @d
        lda line,y
        sta (zp1),y
        iny
        jmp @c
@d:     ldx hhead
        lda lnlen
        sta hlen,x
        inc hhead
        lda hhead
        cmp #HISTN
        bcc @n
        lda #0
        sta hhead
@n:     lda hcount
        cmp #HISTN
        bcs @r
        inc hcount
@r:     lda #0
        sta hpos
        rts

; hslot: zp1 = the slot in A (hist + A * (LINEMAX+1))
hslot:  sta hsn
        lda #0
        sta zp1
        lda hsn
        lsr                 ; A = slot / 2, carry = slot odd
        ror zp1             ; zp1 = 128 when the slot is odd
        pha
        lda zp1
        clc
        adc #<hist
        sta zp1
        pla
        adc #>hist
        sta zp1+1
        rts

; hshow: erase the line on screen and show the one hpos lines back (0: empty)
hshow:  lda lnlen
        beq @e
        lda #K_DEL
        jsr putc
        dec lnlen
        jmp hshow
@e:     lda hpos
        bne @go
        rts
@go:    lda hhead           ; slot = hhead - hpos, wrapped into 0..HISTN-1
        sec
        sbc hpos
        bpl @p
        clc
        adc #HISTN
@p:     jsr hslot
        ldx hsn
        lda hlen,x
        sta lnlen
        ldy #0
@cp:    cpy lnlen
        beq @pr
        lda (zp1),y
        sta line,y
        iny
        jmp @cp
@pr:    lda #0
        sta hctr
@pl:    ldx hctr
        cpx lnlen
        beq @end
        lda line,x
        jsr putc
        inc hctr
        jmp @pl
@end:   rts

; rawkey -> A = next key; carry set on EOF or error
rawkey: lda #<kbuf
        sta r0
        lda #>kbuf
        sta r0+1
        lda #1
        sta r1
        lda #0
        sta r1+1
        lda in_fd
        jsr SYS_READ
        bcs @e
        lda r1
        beq @e
        lda kbuf
        clc
        rts
@e:     sec
        rts

; addch: A goes on the end of the line being edited (dropped when it's full)
addch:  ldx lnlen
        cpx #LINEMAX
        bcs @r
        sta line,x
        inc lnlen
        jmp putc
@r:     rts

; complete: the word before the cursor, plus '*', is expanded like a glob
; (in /bin for a command name). What all the matches share is typed in, then
; '/' or ' ' if there is only one; with nothing to add, they are listed.
; More matches than the glob buffer holds: nothing happens.
complete:
        ldx lnlen
@ws:    txa                 ; tsave = the word's start
        beq @wd
        lda line-1,x
        jsr is_sep
        beq @wd
        dex
        jmp @ws
@wd:    stx tsave
@cp:    dex                 ; a command name: nothing but spaces back to
        bmi @cmd            ; the start or to | ; &
        lda line,x
        jsr is_sep
        bne @arg
        tya
        beq @cp
        cmp #4              ; < or >: a file name
        bcs @arg
@cmd:   ldx tsave           ; ... without a '/'
@sl:    cpx lnlen
        beq @bin
        lda line,x
        inx
        cmp #'/'
        bne @sl
@arg:   ldy #0
        beq @cpy
@bin:   ldy #4
@bc:    lda s_bin,y
        sta tbuf,y
        dey
        bpl @bc
        ldy #5
@cpy:   ldx tsave           ; tbuf = ["/bin/"] word '*'
@c:     cpx lnlen
        beq @star
        lda line,x
        cmp #'*'            ; a pattern already: its length is not an offset
        beq @nope           ; into a name, so do nothing
        cmp #'?'
        beq @nope
        sta tbuf,y
        inx
        iny
        bne @c
@star:  cpy #45             ; glob's buffer holds the directory part of every
        bcs @nope           ; match: keep it short
        sty xsave           ; xsave = the typed part's length
        lda #'*'
        sta tbuf,y
        lda #0
        sta tbuf+1,y
        sta nargs
        sta gpos
        sta gpos+1
        sta g_n
        lda #<tbuf
        sta zp1
        lda #>tbuf
        sta zp1+1
        jsr glob
        lda g_n
        beq @x
        lda nargs
        cmp #MAXARG
        bcs @x
        lda gpos
        cmp #256-64
        bcc @go
@nope:
@x:     rts
@go:    lda av              ; tlen = what the matches share
        sta zp1
        lda av+1
        sta zp1+1
        ldy #$ff
@len:   iny
        lda (zp1),y
        bne @len
        sty tlen
        lda nargs
        asl a
        sta g_p
        ldx #2
@nx:    cpx g_p
        bcs @cd
        lda av,x
        sta zp2
        lda av+1,x
        sta zp2+1
        ldy #0
@cm:    cpy tlen
        bcs @nn
        lda (zp1),y
        cmp (zp2),y
        bne @sh
        iny
        bne @cm
@sh:    sty tlen
@nn:    inx
        inx
        bne @nx
@cd:    ldy xsave
        cpy tlen
        bcc @ad
        lda nargs
        cmp #2
        bcs @list
@ad:    cpy tlen
        bcs @one
        lda (zp1),y
        sty g_ss
        jsr addch
        ldy g_ss
        iny
        bne @ad
@one:   lda nargs
        cmp #2
        bcs @r
        lda zp1             ; one match: '/' after a directory
        sta r0
        lda zp1+1
        sta r0+1
        lda #<g_ent
        sta r1
        lda #>g_ent
        sta r1+1
        jsr SYS_STAT
        lda #' '
        bcs @sp
        ldx g_ent
        cpx #T_DIR
        bne @sp
        lda #'/'
@sp:    jmp addch
@r:     rts
@list:  jsr newline
        ldx #0
@li:    stx g_star
        lda av,x
        clc
        adc g_d
        pha
        lda av+1,x
        adc #0
        tax
        pla
        jsr print
        lda #' '
        jsr putc
        ldx g_star
        inx
        inx
        cpx g_p
        bcc @li
        jsr newline
        jsr prompt
        ldx lnlen
        lda #0
        sta line,x
        lda #<line
        ldx #>line
        jmp print

; is_sep: A one of " |;&<>"? -> Z set, Y = its index
is_sep: ldy #5
@l:     cmp seps,y
        beq @r
        dey
        bpl @l
@r:     rts

; ---- tokenizer ----
; tokenize `line` into tbuf/tlo/thi/ttype; carry set on error/empty
tokenize:
        lda #0
        sta ntok
        sta tpos
        ldy #0
@skip:  lda line,y
        cmp #' '
        beq @sp
        cmp #9
        bne @nsp
@sp:    iny
        bne @skip
@nsp:   cmp #0
        beq @jdone
        cmp #'#'
        bne @ntc
@jdone: jmp @done
@ntc:   ldx ntok
        cpx #MAXTOK
        bcc @tok
        jmp @toomany
@tok:
        cmp #'|'
        beq @pipe
        cmp #'&'
        beq @amp
        cmp #';'
        beq @op
        cmp #'<'
        beq @op
        cmp #'>'
        bne @word
        lda line+1,y
        cmp #'>'
        bne @gt
        lda #'A'
        iny
        jmp @op
@g:    lda #'>'
@gt:   sta ttype,x
        inc ntok
        iny
        jmp @skip
@op:    sta ttype,x
        inc ntok
        iny
        jmp @skip
@pipe: lda line+1,y
        cmp #'|'
        beq @or
        lda #'|'
        jmp @op
@or:   lda #T_OR
        sta ttype,x
        inc ntok
        iny
        iny
        jmp @skip
@amp:  lda line+1,y
        cmp #'&'
        beq @and
        lda #'&'
        jmp @op
@and:  lda #T_AND
        sta ttype,x
        inc ntok
        iny
        iny
        jmp @skip
@word:  ; check for $? - if current char is $ and next is ?, emit T_DOLLAR
        lda line,y
        cmp #'$'
        bne @word_start
        lda line+1,y
        cmp #'?'
        bne @word_start
        ; it's $? - emit T_DOLLAR and skip both chars
        lda #T_DOLLAR
        sta ttype,x
        inc ntok
        iny
        iny
        jmp @skip
@word_start:
        lda #T_WORD
        sta ttype,x
        lda tpos
        clc
        adc #<tbuf
        sta tlo,x
        lda #>tbuf
        adc #0
        sta thi,x
        inc ntok
        ldx tpos
@wc:    lda line,y
        beq @we
        cmp #' '
        beq @we
        cmp #9
        beq @we
        cmp #'|'
        beq @we
        cmp #'&'
        beq @we
        cmp #';'
        beq @we
        cmp #'<'
        beq @we
        cmp #'>'
        beq @we
        cmp #'"'
        beq @quote
        cmp #$27            ; single quote
        beq @quote
        sta tbuf,x
        inx
        iny
        jmp @wc
@quote: sta qch
        iny
@ql:    lda line,y
        beq @we
        iny
        cmp qch
        beq @wc
        sta tbuf,x
        inx
        jmp @ql
@we:    lda #0
        sta tbuf,x
        inx
        stx tpos
        jmp @skip
@done:  lda ntok
        beq @empty
        clc
        rts
@empty: sec
        rts
@toomany:
        lda #<s_toolong
        ldx #>s_toolong
        jsr eprint
        sec
        rts

; ---- execution ----
run_line:
        lda #0
        sta gpos
        sta gpos+1
        sta cur_tok
@cmd_loop:
        lda cur_tok
        cmp ntok
        bcc @cmd_body
        jmp @cmd_exit
@cmd_body:
        ; find end of this command (';' or end)
        tax
@f:     cpx ntok
        beq @fe
        lda ttype,x
        cmp #';'
        beq @fe
        cmp #T_AND
        beq @fe
        cmp #T_OR
        beq @fe
        inx
        jmp @f
@fe:    stx cmd_end
        jsr run_cmd
        ; check what's at cmd_end (the operator we stopped at)
        ldx cmd_end
        cpx ntok
        beq @cmd_done
        lda ttype,x
        cmp #';'
        beq @cmd_semi
        cmp #'&'            ; a background job's '&' ends it like ';' (run_cmd left cmd_end on it)
        beq @cmd_semi
        cmp #T_AND
        beq @and_check
        cmp #T_OR
        beq @or_check_target
@skip_or:
        ; unknown token, just continue
        jmp @cmd_loop
@or_check_target:
        jmp @or_check
@cmd_semi:
        ; ';' at cmd_end: skip past it
        inx
        stx cur_tok
        jmp @cmd_loop
@cmd_done:
        ldx ntok
        stx cur_tok
        jmp @cmd_loop
@and_check:
        ; &&: only continue if last_status == 0
        lda last_status
        bne @and_fail
        ; condition met, skip operator and continue
        inx
        stx cur_tok
        jmp @cmd_loop
@and_fail:
        ; condition not met, skip operator and next command
        inx
        stx cur_tok
        ; find next ';' or end, skipping ||
@skip_and:
        lda cur_tok
        cmp ntok
        bne @skip_and_body
        jmp @cmd_loop
@skip_and_body:
        ldx cur_tok
        lda ttype,x
        cmp #T_AND
        beq @skip_and_body_delim
        cmp #T_OR
        beq @skip_and_body_delim
        cmp #';'
        beq @skip_and_body_delim
        ; not a delimiter, just skip
        inc cur_tok
        jmp @skip_and
@skip_and_body_delim:
        jmp @cmd_loop
@skip_next:
        ; skip past this operator
        inc cur_tok
        lda cur_tok
        cmp ntok
        bne @skip_next_body
        jmp @cmd_loop
@skip_next_body:
        ldx cur_tok
        lda ttype,x
        cmp #T_AND
        beq @skip_delim
        cmp #T_OR
        beq @skip_delim
        cmp #T_WORD
        beq @skip_word
        cmp #T_DOLLAR
        beq @skip_word
        ; not a delimiter or word, just skip
        inc cur_tok
        jmp @skip_and
@skip_delim:
        jmp @cmd_loop
@skip_word:
        ; skip the word
        inc cur_tok
        jmp @skip_and
@or_check:
        ; ||: only continue if last_status != 0
        lda last_status
        bne @or_cont
        ; condition not met, skip operator and next command
        inx
        stx cur_tok
        jmp @skip_and
@or_cont:
        ; condition met, skip operator and continue
        inx
        stx cur_tok
        jmp @cmd_loop
@cmd_exit:
        jmp @r
@r:     rts

; run_cmd: tokens cur_tok .. cmd_end-1
run_cmd:
        lda cur_tok
        cmp cmd_end
        bne @ne
        rts
@ne:    lda #0
        sta bg
        sta npids
        sta prev_in
        ldx cmd_end
        dex
        lda ttype,x
        cmp #'&'
        bne @nbg
        stx cmd_end
        inc bg
        cpx cur_tok
        bne @nbg
        jmp syntax
@nbg:   lda #1
        sta first
        lda cur_tok
        sta st_start

stage:  lda #0
        sta nargs
        sta inf_hi
        sta outf_hi
        sta outapp
        ldx st_start
@t:     cpx ntok
        beq @tend_near
        cpx cmd_end
        bne @t1
@tend_near:
        jmp @tend
@jtend: jmp @tend
@t1:    lda ttype,x
        cmp #'|'
        beq @jtend
        cmp #T_AND
        beq @jtend
        cmp #T_OR
        beq @jtend
        cmp #T_WORD
        bne @op
        ldy nargs
        cpy #MAXARG
        bcc @aok
        jmp syntax
@aok:   lda tlo,x
        sta zp1
        lda thi,x
        sta zp1+1
        stx g_tok
        jsr is_glob
        bcs @lit
        jsr glob
        ldx g_tok
        inx
        jmp @t
@lit:   jsr add_arg
        ldx g_tok
        inx
        jmp @t
@op:    cmp #T_DOLLAR
        beq @dollar_exp
        cmp #'&'
        bne @op2
        jmp syntax
@dollar_exp:
        ; save current token index (T_DOLLAR position)
        stx g_tok
        ; expand $? to decimal string of last_status
        lda last_status
        ldx #0
        jsr dec_str
        ; A/X = pointer to first digit, Y = length
        ; store as argument: zp1 = pointer to string
        sta zp1
        stx zp1+1
        jsr add_arg
        ldx g_tok
        inx
        jmp @t
@op2:   pha
        inx
        cpx cmd_end
        beq @syn
        lda ttype,x
        bne @syn
        pla
        cmp #'<'
        bne @out
        lda tlo,x
        sta inf_lo
        lda thi,x
        sta inf_hi
        inx
        jmp @t
@out:   ldy #0
        cmp #'A'
        bne @o2
        iny
@o2:    sty outapp
        lda tlo,x
        sta outf_lo
        lda thi,x
        sta outf_hi
        inx
        jmp @t
@syn:   pla
        jmp syntax
@tend:  cpx ntok
        stx tmpb
        lda #0
        sta last
        cpx cmd_end
        bne @nl
        inc last
@nl:    lda nargs
        bne @hasargs
        jmp syntax
@hasargs:
        asl a
        tay
        lda #0
        sta av,y
        sta av+1,y
        ; built-ins for a single simple command
        lda first
        and last
        beq @ext
        jsr builtin
        bcc @ext
        rts
@ext:   ; stdin
        lda prev_in
        sta pin
        lda inf_hi
        beq @noin
        lda inf_lo
        sta r0
        lda inf_hi
        sta r0+1
        lda #O_RDONLY
        jsr SYS_OPEN
        bcc @inok
        ldx inf_lo
        ldy inf_hi
        jsr perr
        jmp abort
@inok:  pha
        jsr close_pin
        pla
        sta pin
@noin:  ; stdout
        lda #0
        sta pr
        lda #1
        sta pout
        lda last
        bne @nopipe
        jsr SYS_PIPE
        bcc @pok
        ldx #0
        ldy #0
        jsr perr
        jmp abort
@pok:   sta pr
        stx pout
@nopipe:
        lda outf_hi
        beq @noout
        lda outf_lo
        sta r0
        lda outf_hi
        sta r0+1
        lda #(O_WRONLY | O_CREAT | O_TRUNC)
        ldx outapp
        beq @tr
        lda #(O_WRONLY | O_CREAT | O_APPEND)
@tr:    jsr SYS_OPEN
        bcc @ook
        ldx outf_lo
        ldy outf_hi
        jsr perr
        jsr close_pout
        jmp abort
@ook:   pha
        jsr close_pout
        pla
        sta pout
@noout: jsr make_path
        lda #<cmdpath
        sta r0
        lda #>cmdpath
        sta r0+1
        lda #<av
        sta r1
        lda #>av
        sta r1+1
        ldy #0
        lda bg
        beq @fg
        ldy #SP_BG
@fg:    lda pin
        ldx pout
        jsr SYS_SPAWN
        bcc @spok
        ; SYS_SPAWN failed: set nonzero status
        ldy #1
        sty last_status     ; (A is the errno, perr's argument)
        ldx av
        ldy av+1
        jsr perr
        jmp @cl
@spok:  ldx npids
        sta pids,x
        inc npids
@cl:    jsr close_pin
        jsr close_pout
        lda pr
        sta prev_in
        lda last
        bne @wait
        ; last == 0: not final stage, continue to next pipeline stage
        lda #0
        sta first
        ldx tmpb
        inx
        stx st_start
        jmp stage
@wait:  lda npids
        beq @r
        lda bg
        beq @wl
        lda #'['
        jsr putc
        ldx npids
        lda pids-1,x
        ldx #0
        jsr print_dec
        lda #']'
        jsr putc
        jmp newline
@wl:    ldx #0
@w:     stx tmpb
        lda pids,x
        ldx #0
        jsr SYS_WAIT
        stx last_status
        ldx tmpb
        inx
        cpx npids
        bne @w
@r:     rts

; add_arg: av[nargs++] = zp1 (silently ignored when full)
add_arg:
        lda nargs
        cmp #MAXARG
        bcs @r
        asl a
        tay
        lda zp1
        sta av,y
        lda zp1+1
        sta av+1,y
        inc nargs
@r:     rts

; is_glob: carry clear if the word at zp1 contains * or ?
is_glob:
        ldy #0
@l:     lda (zp1),y
        beq @no
        cmp #'*'
        beq @y
        cmp #'?'
        beq @y
        iny
        bne @l
@no:    sec
        rts
@y:     clc
        rts

; glob: expand the pattern word at zp1 into av (literal if nothing matches)
glob:   lda zp1
        sta g_word
        lda zp1+1
        sta g_word+1
        ; d = index after the last '/'
        ldy #0
        sty g_d
@s:     lda (zp1),y
        beq @se
        iny
        cmp #'/'
        bne @s
        sty g_d
        jmp @s
@se:    ; directory to read
        ldy g_d
        bne @dir
        lda #'.'
        sta g_dir
        lda #0
        sta g_dir+1
        jmp @open
@dir:   lda g_d
        cmp #48             ; g_dir holds 47 characters: a longer prefix stays literal
        bcc @dn
        jmp @lit
@dn:    ldy #0
@dc:    cpy g_d
        beq @dz
        lda (zp1),y
        sta g_dir,y
        iny
        cpy #47
        bcc @dc
@dz:    cpy #1
        beq @root
        dey                 ; drop the trailing '/'
@root:  lda #0
        sta g_dir,y
@open:  lda #<g_dir
        sta r0
        lda #>g_dir
        sta r0+1
        lda #O_RDONLY
        jsr SYS_OPEN
        bcs @lit
        sta g_fd
        lda #0
        sta g_n
@rd:    lda #<g_ent
        sta r0
        lda #>g_ent
        sta r0+1
        lda #16
        sta r1
        lda #0
        sta r1+1
        lda g_fd
        jsr SYS_READ
        bcs @done
        lda r1
        cmp #16
        bne @done
        lda g_ent
        beq @rd
        ; hidden names only match a pattern that starts with '.'
        lda g_ent+1
        cmp #'.'
        bne @m
        lda g_word
        clc
        adc g_d
        sta zp2
        lda g_word+1
        adc #0
        sta zp2+1
        ldy #0
        lda (zp2),y
        cmp #'.'
        bne @rd
@m:     jsr match
        bcs @rd
        jsr g_store
        bcs @done
        inc g_n
        jmp @rd
@done:  lda g_fd
        jsr SYS_CLOSE
        lda g_n
        bne @r
@lit:   lda g_word
        sta zp1
        lda g_word+1
        sta zp1+1
        jmp add_arg
@r:     rts

; g_store: append word[0..d) + name to the glob buffer and add it to av
g_store:
        lda gpos+1
        bne @full
        lda gpos            ; the record is d + 15 name bytes + NUL: gpos+d+16 <= 256
        clc
        adc g_d
        bcs @full
        adc #15
        bcs @full
        lda #<gbuf
        clc
        adc gpos
        sta zp1
        lda #>gbuf
        adc gpos+1
        sta zp1+1
        lda g_word
        sta zp2
        lda g_word+1
        sta zp2+1
        ldy #0
@p:     cpy g_d
        beq @pd
        lda (zp2),y
        sta (zp1),y
        iny
        bne @p
@pd:    ldx #0
@n:     lda g_ent+1,x
        sta (zp1),y
        beq @e
        iny
        inx
        cpx #15
        bcc @n
        lda #0
        sta (zp1),y
@e:     iny
        tya
        clc
        adc gpos
        sta gpos
        bcc @a
        inc gpos+1
@a:     jsr add_arg
        clc
        rts
@full:  sec
        rts

; match: pattern (word + d) against the name g_ent+1 -> carry clear if it matches
match:  lda #0
        sta g_p
        sta g_s
        lda #$ff
        sta g_star
        lda g_word
        clc
        adc g_d
        sta zp2
        lda g_word+1
        adc #0
        sta zp2+1
@loop:  ldx g_s
        lda g_ent+1,x
        beq @tail
        ldy g_p
        lda (zp2),y
        cmp #'?'
        beq @adv
        cmp g_ent+1,x
        beq @adv
        cmp #'*'
        bne @back
        sty g_star
        inc g_p
        stx g_ss
        jmp @loop
@adv:   inc g_p
        inc g_s
        jmp @loop
@back:  lda g_star
        cmp #$ff
        beq @no
        tay
        iny
        sty g_p
        inc g_ss
        lda g_ss
        sta g_s
        jmp @loop
@tail:  ldy g_p
@t:     lda (zp2),y
        cmp #'*'
        bne @end
        iny
        bne @t
@end:   cmp #0
        bne @no
        clc
        rts
@no:    sec
        rts

close_pin:
        lda pin
        beq @r
        jsr SYS_CLOSE
        lda #0
        sta pin
@r:     rts

close_pout:
        lda pout
        cmp #1
        beq @r
        jsr SYS_CLOSE
        lda #1
        sta pout
@r:     rts

; abort a pipeline after an error: close what is open, wait for started stages
abort:  jsr close_pin
        jsr close_pout
        lda pr
        beq @w
        jsr SYS_CLOSE
@w:     lda #0
        sta bg
        lda #1
        sta last
        lda #1
        sta last_status
        ldx #0
        cpx npids
        beq @r
@l:     stx tmpb
        lda pids,x
        ldx #0
        jsr SYS_WAIT
        ldx tmpb
        inx
        cpx npids
        bne @l
@r:     rts

syntax: lda prev_in
        beq @n
        jsr SYS_CLOSE
@n:     lda #<s_syntax
        ldx #>s_syntax
        jmp eprint

; make_path: av[0] -> cmdpath ("/bin/" + name unless it contains '/')
make_path:
        lda av
        sta zp1
        lda av+1
        sta zp1+1
        ldy #0
@s:     lda (zp1),y
        beq @nos
        cmp #'/'
        beq @lit
        iny
        bne @s
@nos:   ldx #4
@p:     lda s_bin,x
        sta cmdpath,x
        dex
        bpl @p
        ldx #5
        jmp @cp
@lit:   ldx #0
@cp:    ldy #0
@c:     lda (zp1),y
        sta cmdpath,x
        beq @r
        inx
        iny
        cpx #63
        bcc @c
        lda #0
        sta cmdpath,x
@r:     rts

; builtin: carry set if av[0] was a built-in (and it ran)
builtin:
        lda av
        sta lp1
        lda av+1
        sta lp1+1
        lda #<s_cd
        sta lp2
        lda #>s_cd
        sta lp2+1
        jsr strcmp_
        bne @nocd
        lda nargs
        cmp #2
        bcs @arg
        lda #<s_root
        sta r0
        lda #>s_root
        sta r0+1
        jmp @cd
@arg:   lda av+2
        sta r0
        lda av+3
        sta r0+1
@cd:    jsr SYS_CHDIR
        bcc @ok
        ldx r0
        ldy r0+1
        jsr perr
        lda #1
        sta last_status
        sec
        rts
@ok:    lda #0
        sta last_status
        sec
        rts
@nocd:  lda #<s_kill
        sta lp2
        lda #>s_kill
        sta lp2+1
        jsr strcmp_
        bne @nokill
        jmp bi_kill
@nokill:
        lda #<s_jobs
        sta lp2
        lda #>s_jobs
        sta lp2+1
        jsr strcmp_
        bne @nojobs
        jmp bi_jobs
@nojobs:
        lda #<s_exit
        sta lp2
        lda #>s_exit
        sta lp2+1
        jsr strcmp_
        bne @no
        lda #0
        jmp exit
@no:    clc
        rts

; kill [-signal] pid... as a built-in, so a full process table can be
; cleared (the shell needs no new process to send a signal)
bi_kill:
        lda #SIGTERM
        sta bk_sig
        lda #1
        sta bk_i
        lda nargs
        cmp #2
        bcc @done
        lda av+2
        sta zp1
        lda av+3
        sta zp1+1
        ldy #0
        lda (zp1),y
        cmp #'-'
        bne @l
        lda zp1
        clc
        adc #1
        ldx zp1+1
        bcc @p
        inx
@p:     jsr parse_dec
        bcs @done
        sta bk_sig
        inc bk_i
@l:     lda bk_i
        cmp nargs
        bcs @done
        asl a
        tay
        lda av,y
        ldx av+1,y
        sta bk_p
        stx bk_p+1
        jsr parse_dec
        bcs @bad
        ldx bk_sig
        jsr SYS_KILL
        bcc @n
@bad:   ldx bk_p
        ldy bk_p+1
        jsr perr
@n:     inc bk_i
        jmp @l
@done:  lda #0
        sta last_status
        sec
        rts

; jobs: background children of this shell (from the process table)
bi_jobs:
        jsr SYS_GETPID
        sta bk_sig          ; my pid
        lda #0
        sta bk_i
@l:     lda #<pinfo
        sta r0
        lda #>pinfo
        sta r0+1
        lda bk_i
        jsr SYS_PROCINFO
        bcs @n
        lda pinfo+1
        cmp bk_sig
        bne @n
        lda pinfo+2
        cmp #3              ; zombie: finished, reaped at the next prompt
        beq @n
        lda #'['
        jsr putc
        lda pinfo
        ldx #0
        jsr print_dec
        lda #<s_run
        ldx #>s_run
        jsr print
        lda #<(pinfo+5)
        ldx #>(pinfo+5)
        jsr print
        jsr newline
@n:     inc bk_i
        lda bk_i
        cmp #16
        bne @l
        lda #0
        sta last_status
        sec
        rts

strcmp_:
        ldy #0
@l:     lda (lp1),y
        cmp (lp2),y
        bne @r
        cmp #0
        beq @r
        iny
        bne @l
@r:     rts

.segment "RODATA"
s_prompt:  .byte " $ ", 0
s_done:    .byte "] done", 10, 0
s_syntax:  .byte "sh: syntax error", 10, 0
s_toolong: .byte "sh: line too long", 10, 0
s_bin:     .byte "/bin/"
seps:      .byte " |;&<>"
s_cd:      .byte "cd", 0
s_exit:    .byte "exit", 0
s_kill:    .byte "kill", 0
s_jobs:    .byte "jobs", 0
s_run:     .byte "] running  ", 0
s_root:    .byte "/", 0
