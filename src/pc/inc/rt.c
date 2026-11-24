/* inc/rt.c - what bas (bas.c) and the runner for its compiled files (brun.c) have in common: the
   output, the error messages and the runtime functions a compiled program calls (rt_prs to
   rt_next, which must stay together: a .bx file names them by their offsets from rt_prs, and the
   natives in rt.s by offsets from rt_mark; docs/design/basic.md 6.1). Included first in each,
   which keeps those offsets the same; tools/test_bas.py checks that they are. */

extern int c_ldv(char *p); /* xop 240 void */      /* bas-rt.s, for the mini C: one result each */
extern int c_stv(char *p); /* xop 246 void */
extern int c_add(); /* void */
extern int c_mul(); /* void */
extern int c_div(); /* void */
extern int c_int(); /* void */
extern int c_toi();
extern int c_fromi(int i); /* void */
extern int c_cmp();
extern int c_fmt(char *buf);
extern int c_throw(int e);

int err;                /* the error numbers are emsg's */
char emsg[] = "SYNTAX|OUT OF MEMORY|LINE TOO LONG|OVERFLOW|DIVISION BY ZERO|ILLEGAL QUANTITY|RETURN WITHOUT GOSUB|NEXT WITHOUT FOR|BREAK|UNDEF'D STATEMENT|FORMULA TOO COMPLEX|";
char ctl[193];          /* GOSUB and FOR entries, each with its tag last: G (3 bytes) the return
                           address; F (13) the variable, the body, the limit and the step */
int csp;
char pb[4];             /* scratch: the byte outc writes, and the number rt_pow keeps */
int col;                /* the output column */
char *nul;              /* 0: an address minus nul is the address as an int */

int outc(int c) {       /* a write each: the kernel buffers the console, and obuf was 66 bytes */
    pb[0] = c;
    write(1, pb, 1);
    col = col + 1;
    if (c == '\n') col = 0;
    return 0;
}

int fresh() {           /* to the start of a line, as MS before READY. and an error */
    if (col) outc('\n');
    return 0;
}

int outs(char *s) {
    int i = 0;
    while (s[i]) {
        outc(s[i]);
        i = i + 1;
    }
    return 0;
}

int outu(int u) {       /* u as an unsigned decimal: line numbers go to 63999 */
    int q = ((u >> 1) & 32767) / 5;
    if (q) outu(q);
    outc('0' + u - q * 10);
    return 0;
}

int getw(char *p) {
    return p[0] + (p[1] << 8);
}

int putw(char *p, int w) {
    p[0] = w;
    p[1] = w >> 8;
    return 0;
}

int outn(char *t, int n) {      /* entry n (from 0) of the |-ended list t */
    int k = 0;
    while (n > 0) {
        if (t[k] == '|') n = n - 1;
        k = k + 1;
    }
    while (t[k] != '|') {
        outc(t[k]);
        k = k + 1;
    }
    return 0;
}

int outb(char *b, int n) {       /* n bytes */
    int i;
    for (i = 0; i < n; i = i + 1) outc(b[i]);
    return 0;
}

int rt_prs(char *s) {   /* a CS string: length, then the text */
    return outb(s + 1, s[0]);
}

int rt_prn() {          /* PRINT a number: a sign or a space before it, a space after */
    char b[12];
    outb(b, c_fmt(b));
    outc(' ');
    return 0;
}

int rt_nl() {
    outc('\n');
    return 0;
}

int rt_tab() {          /* PRINT's comma: to the next column of 10 */
    outc(' ');
    while (col % 10) outc(' ');
    return 0;
}

int rt_pow() {          /* the number under the top to the power on top, by squaring; the power
                           must be a whole number (-32768 to 32767) */
    int e;
    int neg;
    c_stv(pb);
    c_ldv(pb);
    c_int();
    c_ldv(pb);
    if (c_cmp()) c_throw(6);
    c_ldv(pb);
    e = c_toi();
    neg = e < 0;
    if (neg) e = 0 - e;
    c_stv(pb);
    c_fromi(1);
    while (e) {
        if (e & 1) {
            c_ldv(pb);
            c_mul();
        }
        e = (e >> 1) & 32767;
        if (e) {
            c_ldv(pb);
            c_ldv(pb);
            c_mul();
            c_stv(pb);
        }
    }
    if (neg) {
        c_stv(pb);
        c_fromi(1);
        c_ldv(pb);
        c_div();
    }
    return 0;
}

int rt_gosub(int r) {
    if (csp > 192 - 3) c_throw(2);
    putw(ctl + csp, r);
    ctl[csp + 2] = 'G';
    csp = csp + 3;
    return 0;
}

int rt_return() {       /* the address after the last GOSUB, dropping the loops inside it */
    while (csp && ctl[csp - 1] == 'F') csp = csp - 13;
    if (!csp) c_throw(7);
    csp = csp - 3;
    return getw(ctl + csp);
}

int rt_for(int body, int v) {   /* the limit and the step are on the number stack, the step on
                                   top; a loop on v already running ends, with those inside it */
    int p = csp;
    while (p && ctl[p - 1] == 'F') {
        p = p - 13;
        if (getw(ctl + p) == v) csp = p;
    }
    if (csp > 192 - 13) c_throw(2);
    putw(ctl + csp, v);
    putw(ctl + csp + 2, body);
    c_stv(ctl + csp + 8);
    c_stv(ctl + csp + 4);
    ctl[csp + 12] = 'F';
    csp = csp + 13;
    return 0;
}

int rt_next(int v) {    /* step the loop on v (0: the innermost): the body's address to go on,
                           or 0 when it is done */
    int e;
    int r;
    char *x;
    while (1) {
        if (!csp || ctl[csp - 1] != 'F') c_throw(8);
        e = csp - 13;
        if (!v || getw(ctl + e) == v) break;
        csp = e;
    }
    x = nul + getw(ctl + e);
    c_ldv(x);
    c_ldv(ctl + e + 8);
    c_add();
    c_stv(x);
    c_ldv(x);
    c_ldv(ctl + e + 4);
    r = c_cmp();
    if (ctl[e + 11] & 128) r = 0 - r;   /* a negative step counts down */
    if (r > 0) {
        csp = e;
        return 0;
    }
    return getw(ctl + e + 2);
}

int report(int e, int line) {   /* error e as MS prints it; line -1 for none */
    fresh();
    if (e != 9) outc('?');     /* BREAK is a message and no error */
    outn(emsg, e - 1);
    if (e != 9) outs(" ERROR");
    if (line != -1) {
        outs(" IN ");
        outu(line);
    }
    outc('\n');
    err = 0;
    return 0;
}
