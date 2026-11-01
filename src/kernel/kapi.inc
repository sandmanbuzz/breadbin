; Kernel entry points a loadable module may call. A module is linked against the kernel's
; absolute addresses; mod_load refuses a module whose header hash differs from the sum of
; these words (the module was built against another kernel). Append only; the module build
; (tools/kexports.py, build/kexp.s) lists the same names in the same order.
kapi_tab:
        .word con_puts_ax, page_alloc, page_free
kapi_end:
KAPI_N = (kapi_end - kapi_tab) / 2
