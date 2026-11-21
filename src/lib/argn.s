; Breadbin user library: argument access
.include "../../include/breadbin.inc"
.export argn

.segment "CODE"
; argn: A = index -> A/X = argv[index]; carry set if index >= argc
argn:
        cmp argc
        bcs @r
        asl a
        tay
        lda (argv),y
        pha
        iny
        lda (argv),y
        tax
        pla
        clc
@r:     rts
