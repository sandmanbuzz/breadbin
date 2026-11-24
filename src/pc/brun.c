/* brun: run a compiled BASIC file (bas's BUILD, docs/design/basic.md 6.1): brun FILE.
   The file is "BX", 1, rtid, the code's length, the variables' size, the code and a line table.
   The code is read into the arena (from the bottom, the variables at the top, cleared), its
   addresses made real again (reloc) and it is called as bas calls a RUN. It names the runtime by
   offsets, so rtid (the sizes of the two blocks they are in) must be the same as in the bas that
   built it: both include inc/rt.c and inc/rt.s first. After an error the file is read again for
   the line table (the dead code's room is the buffer). */

/* xops */
#include "inc/rt.c"
/* fstack 416 */

extern int c_grow(int n);       /* brun-rt.s and rt.s: pages for the arena, the pages granted */
extern int c_err();
extern int c_curip();
extern int c_arg(int n);        /* argv[n] as an address, 0 past the end */

char *mem;

int lineof(int a, int n) {      /* the line of the code at offset a: the last table entry before it, or -1 */
    int fd = open(nul + c_arg(1), 0);
    int ln = -1;
    int k;
    char h[4];
    if (fd < 0) return -1;
    n = n + 9;
    while (n > 0) {             /* skip the header and the code */
        k = 256;
        if (n < k) k = n;
        k = read(fd, mem, k);
        if (k < 1) return -1;
        n = n - k;
    }
    while (read(fd, h, 4) == 4 && getw(h) < a) ln = getw(h + 2);
    close(fd);
    return ln;
}

int bad() {
    write(2, "brun: not a file of this bas\n", 29);
    exit(1);
    return 0;
}

int main() {
    char h[9];
    int fd;
    int n;
    int v;
    int msz;
    int i;
    int e;
    fd = open(nul + c_arg(1), 0);
    if (fd < 0 || read(fd, h, 9) != 9 || h[0] != 'B' || h[1] != 'X' || h[2] != 1 || getw(h + 3) != rtid()) {
        bad();
    }
    n = getw(h + 5);
    v = getw(h + 7);
    msz = c_grow(120) * 256;
    if (msz < n + v) {
        write(2, "brun: out of memory\n", 20);
        exit(1);
    }
    i = 0;
    while (i < n) {
        e = read(fd, mem + i, n - i);
        if (e < 1) bad();
        i = i + e;
    }
    close(fd);
    for (i = msz - v; i < msz; i = i + 1) mem[i] = 0;
    reloc(mem - nul, n, mem - nul + msz - v, 0);
    icall(mem);
    e = c_err();
    if (e) {
        i = c_curip() - (mem - nul);
        v = -1;
        if (i > 0 && i <= n) v = lineof(i, n);
        report(e, v);
    }
    return e != 0;
}
