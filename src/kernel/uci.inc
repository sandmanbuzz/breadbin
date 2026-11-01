; UCI v1 (THROWAWAY, see src/kernel/uci.s): the device number and the type byte.
; Kept out of k.inc on purpose: dev 5 lives in arrays sized NDEV+1 (blk.s), NDEV itself
; (the drives 9-11 range checks in cbm.s) is unchanged.
DEV_UCI = NDEV          ; 5: the Ultimate's file storage, mounted with `mount uci DIR`
FS_UCI  = $80           ; dev_type: c64fs 0, CBM DOS 1, UCI $80 (sites test with bmi)
NUV     = 16          ; uci.km: the resident jmp stubs (src/kernel/uci.s) it points at itself
