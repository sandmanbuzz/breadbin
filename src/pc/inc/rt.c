/* inc/rt.c - what bas (bas.c) and the runner for its compiled files (brun.c) have in common: the
   output, the error messages and the runtime functions a compiled program calls (rt_prs to
   rt_next, which must stay together: a .bx file names them by their offsets from rt_prs, and the
   natives in rt.s by offsets from rt_mark; docs/design/basic.md 6.1). Included first in each,
   which keeps those offsets the same; tools/test_bas.py checks that they are. */

/* valued getw outb rt_prs rt_prn rt_nl rt_tab rt_pow rt_gosub rt_return rt_for rt_next */   /* tools/cc_pcode.py: a
   program that never reads one of these (brun) would make it void, and the offsets would differ from bas's */

extern int rt_mark();   /* rt.s, for the compiled code: these take their arguments from the */
extern int rt_go();     /* eval stack and the number stack as the comments there say; the */
extern int rt_ln();     /* compiler only takes their addresses */
extern int rt_end();    /* the end of rt.s: only its address */
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

int reloc(int c, int n, int vb, int un) {  /* the n bytes of code at address c, in place: their addresses
                           to offsets (un) or back, the format of a compiled file (basic.md 6.1). A code
                           address is an offset from c, a variable's one from vb with bit 15 set, a NCAL's
                           from rt_mark (the natives) and a CALL's from rt_prs (the rest of the runtime) */
    char *p = nul + c;
    int i = 0;
    int k;
    int b;
    int f;
    int w;
    int op;
    while (i < n) {
        op = p[i];
        k = 1;
        b = 0;
        f = 0;
        w = getw(p + i + 1);
        if (op == 38 /* PO_LA */ && w) {
            b = c;
            if (un) {
                if (w - c >= n) {
                    b = vb;
                    f = 1 << 15;
                }
            } else if (w < 0) {
                b = vb;
                f = 1 << 15;
            }
        }
        if (op == 106 /* PO_LAW */ || op == 122 /* PO_SAW */ || op == 200 /* x LDV */ || op == 202 /* x STV */) {
            b = vb;
            f = 1 << 15;
        }
        if (op == 82 /* PO_NCAL */) b = &rt_mark - nul;
        if (op == 84 /* PO_CALL */) b = &rt_prs - nul;
        if (op == 196 /* PO_JUMP */) b = c;
        if (b || op == 38 /* PO_LA */ || op == 44 /* PO_CW */) k = 3;
        else if (op == 42 /* PO_CB */ || op == 76 /* PO_BRFLS */ || op == 78 /* PO_BRTRU */ || op == 80 /* PO_BRNCH */) k = 2;
        else if (op == 46 /* PO_CS */) k = p[i + 1] + 2;
        if (un) b = 0 - b;
        if (b) putw(p + i + 1, w + b + f);
        i = i + k;
    }
    return 0;
}

int rtid() {            /* what a compiled file must agree with: the sizes of the two runtime blocks its
                           offsets are in (rt.s's natives and the bytecode from rt_prs to report) */
    return (&rt_end - nul - (&rt_mark - nul)) * 3 + (&report - nul - (&rt_prs - nul));
}
