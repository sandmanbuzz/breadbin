; Breadbin: the resident part of UCI v1 (the Ultimate's file storage, docs/design/next/uci-v1.md)
;
; The code is the kernel module /lib/km/uci (src/mod/uci.s). What stays here: sixteen `jmp`
; stubs, the names the bmi sites in file.s/fs.s/exec.s/cbm.s call, which point at cbm_none
; (A = ENODEV, carry set) until the module's init points them at its routines; uci_load, which
; sys_mount calls for `mount uci`; uci_drop, which unloads the module when no UCI mount is left
; (after umount, or after a mount that failed: the probe on a machine without a Command
; Interface). A machine that never asks for `mount uci` never loads the module and never
; touches $DF1B-$DF1F.
;
; uci_sl: 0 = not loaded, slot + 1 = loaded in that module slot, $FF while the kernel itself
; is loading or unloading it. The module's init and fini refuse unless it is $FF, so a root
; `mod load /lib/km/uci` or `mod unload N` cannot get the stubs out of step with the mount.
.include "k.inc"
.include "uci.inc"

.import mod_load, mod_unload, cbm_none

.export uci_namei, uci_iget, uci_read, uci_xread, uci_write, uci_open, uci_create
.export uci_release, uci_hw, uci_attach, uci_umount, uci_fsinfo, uci_mkdir
.export uci_rmdir, uci_unlink, uci_rename
.export ucv, uci_sl, uci_load, uci_drop

.segment "BSS"
uci_sl:  .res 1

; The stubs: written by the module (init, fini), so they live in DATA. Same order as uvtab in
; src/mod/uci.s.
.segment "DATA"
ucv:
uci_namei:      jmp cbm_none
uci_iget:       jmp cbm_none
uci_read:       jmp cbm_none
uci_xread:      jmp cbm_none
uci_write:      jmp cbm_none
uci_open:       jmp cbm_none
uci_create:     jmp cbm_none
uci_release:    jmp cbm_none    ; (file.s: keeps X; cbm_none does)
uci_hw:         jmp cbm_none
uci_attach:     jmp cbm_none
uci_umount:     jmp cbm_none
uci_fsinfo:     jmp cbm_none
uci_mkdir:      jmp cbm_none
uci_rmdir:      jmp cbm_none
uci_unlink:     jmp cbm_none
uci_rename:     jmp cbm_none
.assert * - ucv = NUV*3, error, "the stubs and uvtab in src/mod/uci.s differ in length"

.segment "RODATA"
s_ukm:  .byte "/lib/km/uci", 0

.segment "CODEHI"               ; cold: once per mount and umount
; uci_load: load the module unless it is loaded (r0 is kept). Carry set, A = errno on failure.
uci_load:
        lda uci_sl
        bne @ok
        lda r0+1
        pha
        lda r0
        pha
        lda #<s_ukm
        sta r0
        lda #>s_ukm
        sta r0+1
        dec uci_sl              ; $FF: init may run
        jsr mod_load            ; -> A = slot
        tay
        pla
        sta r0
        pla
        sta r0+1
        inc uci_sl              ; 0 again (carry untouched)
        tya
        bcs @r
        sta uci_sl
        inc uci_sl              ; slot + 1
@ok:    clc
@r:     rts

; uci_drop: unload the module unless a UCI mount is using it. Keeps A and the flags.
uci_drop:
        php
        pha
        lda dev_present+DEV_UCI
        bne @r
        ldx uci_sl
        beq @r
        dex
        txa
        ldx #$ff
        stx uci_sl              ; fini may run
        jsr mod_unload
        lda #0
        sta uci_sl
@r:     pla
        plp
        rts
