; The kernel API hash that modules must carry (docs/design/next/modules-v1.md). The value is
; generated from the linked kernel by tools/kexports.py (mk/modules.mk): build/khash.inc.
.export kapi_hash
.segment "RODATA"
kapi_hash:
.include "../../build/khash.inc"
