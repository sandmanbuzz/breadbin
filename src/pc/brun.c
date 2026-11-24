/* brun: run a compiled BASIC file (bas's BUILD, docs/design/basic.md 6.1): brun FILE.
   The file is "BX", 1, the code's length, the variables' size, then the code. It is read into the
   arena (the code from the bottom, the variables at the top, cleared), its addresses made real
   again (reloc) and it is called as bas calls a RUN. It needs the natives in inc/rt.s at the
   same offsets as the bas that built it: both include inc/rt.c and inc/rt.s first. */

/* xops */
#include "inc/rt.c"
/* fstack 416 */

extern int c_grow(int n);       /* brun-rt.s and rt.s: pages for the arena, the pages granted */
extern int c_err();
extern int c_arg(int n);        /* argv[n] as an address, 0 past the end */

char *mem;

int main() {
    char h[7];
    int fd;
    int n;
    int v;
    int msz;
    int i;
    int e;
    fd = open(nul + c_arg(1), 0);
    if (fd < 0 || read(fd, h, 7) != 7 || h[0] != 'B' || h[1] != 'X' || h[2] != 1) {
        write(2, "brun: no compiled file\n", 23);
        exit(1);
    }
    n = getw(h + 3);
    v = getw(h + 5);
    msz = c_grow(120) * 256;
    if (msz < n + v) {
        write(2, "brun: out of memory\n", 20);
        exit(1);
    }
    i = 0;
    while (i < n) i = i + read(fd, mem + i, n - i);
    close(fd);
    for (i = msz - v; i < msz; i = i + 1) mem[i] = 0;
    reloc(mem - nul, n, mem - nul + msz - v, 0);
    icall(mem);
    e = c_err();
    if (e) report(e, -1);
    return e != 0;
}
