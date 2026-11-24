/* inc/rt.c - what bas (bas.c) and the runner for its compiled files (brun.c) have in common: the
   output, the error messages and the runtime functions a compiled program calls (rt_prs to
   rt_next, which must stay together: a .bx file names them by their offsets from rt_prs, and the
   natives in rt.s by offsets from rt_mark; docs/design/basic.md 6.1). Included first in each,
   which keeps those offsets the same; tools/test_bas.py checks that they are. */

/* valued getw outb rt_prs rt_prn rt_nl rt_tab rt_pow rt_gosub rt_return rt_for rt_next rt_sres rt_scat rt_sset rt_scmp rt_len rt_asc rt_chr rt_left rt_right rt_mid rt_str rt_val rt_inp rt_ifld rt_sub rt_sw */   /* tools/cc_pcode.py: a
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
extern int c_throw(int e); /* void */
extern int c_mcpy(int d, int s, int n); /* void */  /* an ascending byte copy */

int err;                /* the error numbers are emsg's */
char emsg[] = "SYNTAX|OUT OF MEMORY|LINE TOO LONG|OVERFLOW|DIVISION BY ZERO|ILLEGAL QUANTITY|RETURN WITHOUT GOSUB|NEXT WITHOUT FOR|BREAK|UNDEF'D STATEMENT|FORMULA TOO COMPLEX|STRING TOO LONG|TYPE MISMATCH|BAD SUBSCRIPT|REDIM'D ARRAY|";
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


/* ---- strings: a heap of blocks, [back-pointer (2), length, text]. A string is the address of its
   length byte, as a CS literal is (the literal is no block), and 0 is "". The back-pointer is the
   address of the variable that holds the block, -1 for a temporary (made in this statement, not yet
   assigned) and 0 once it is dead. Only rt_sres, at the start of a statement that uses strings, moves
   blocks (sgc), so no address on the stacks goes stale; a block it finds with -1 is an error's leftover. ---- */

int hlo;                /* the heap: [hlo, htop) is in use, up to hhi (the variables below) */
int htop;
int hhi;

int inheap(int s) {
    return s && s - hlo > 0 && s - htop < 0;
}

int sfree(int s) {      /* a temporary used up */
    if (inheap(s) && getw(nul + s - 2) == -1) rt_sw(s - 2, 0);
    return 0;
}

int salloc(int n) {     /* a temporary of n bytes, 1 to 255: its address */
    int s = htop + 2;
    if (hhi - htop < n + 3) c_throw(2);
    rt_sw(htop, -1);
    nul[s] = n;
    htop = htop + n + 3;
    return s;
}

int sgc() {             /* the live blocks down over the dead ones, each variable following its block */
    int q = hlo;
    int d = hlo;
    int b;
    int n;
    while (q - htop < 0) {
        b = getw(nul + q);
        n = nul[q + 2] + 3;
        if (b && b != -1) {
            c_mcpy(d, q, n);
            rt_sw(b, d + 2);
            d = d + n;
        }
        q = q + n;
    }
    htop = d;
    return 0;
}

int rt_prs(int s) {     /* a string: length, then the text */
    if (s) {
        outb(nul + s + 1, nul[s]);
        sfree(s);
    }
    return 0;
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

int rt_sres(int n) {    /* room for n temporaries of any length, before a statement that makes them */
    n = n * 258;
    if (hhi - htop < n) {
        sgc();
        if (hhi - htop < n) c_throw(2);
    }
    return 0;
}

int rt_scat(int a, int b) {
    int la = slen(a);
    int lb = slen(b);
    int r;
    if (la + lb > 255) c_throw(12);
    if (!la) return b;
    if (!lb) return a;
    r = salloc(la + lb);
    c_mcpy(r + 1, a + 1, la);
    c_mcpy(r + 1 + la, b + 1, lb);
    sfree(a);
    sfree(b);
    return r;
}

int rt_sset(int c, int s) {     /* the variable at c := the string s: a temporary becomes its block; any
                                   other (a variable's, or a literal, which an immediate line's code
                                   overwrites) is copied */
    int o = getw(nul + c);
    int n;
    if (s == o) return 0;
    if (s) {
        if (!inheap(s) || getw(nul + s - 2) != -1) {
            n = salloc(nul[s]);
            c_mcpy(n + 1, s + 1, nul[s]);
            s = n;
        }
        rt_sw(s - 2, c);
    }
    rt_sw(c, s);
    if (inheap(o)) rt_sw(o - 2, 0);
    return 0;
}

int rt_scmp(int a, int b) {     /* -1, 0 or 1 */
    int la = slen(a);
    int lb = slen(b);
    int i = 0;
    int r = 0;
    int m;
    m = la;
    if (lb < la) m = lb;
    while (i < m && !r) {
        r = nul[a + 1 + i] - nul[b + 1 + i];
        i = i + 1;
    }
    if (!r) r = la - lb;
    sfree(a);
    sfree(b);
    if (r > 0) return 1;
    if (r < 0) return -1;
    return 0;
}

int rt_len(int s) {
    int n = slen(s);
    sfree(s);
    return n;
}

int rt_asc(int s) {
    int n;
    if (!s) c_throw(6);
    n = nul[s + 1];
    sfree(s);
    return n;
}

int rt_chr(int n) {
    int r;
    if (n < 0 || n > 255) c_throw(6);
    r = salloc(1);
    nul[r + 1] = n;
    return r;
}

int rt_mid(int s, int i, int n) {       /* n characters from the i-th (1 is the first): the string itself when that is all of it */
    int l = slen(s);
    int r;
    if (i < 1 || n < 0) c_throw(6);
    if (i > l) n = 0;
    else if (n > l - i + 1) n = l - i + 1;
    if (!n) {
        sfree(s);
        return 0;
    }
    if (n == l) return s;
    r = salloc(n);
    c_mcpy(r + 1, s + i, n);
    sfree(s);
    return r;
}

int rt_left(int s, int n) {
    return rt_mid(s, 1, n);
}

int rt_right(int s, int n) {
    int l = slen(s);
    if (n < 0) c_throw(6);
    if (n > l) n = l;
    return rt_mid(s, l - n + 1, n);
}

int rt_str() {          /* STR$ of the number on top of the number stack: as PRINT writes it, without the space after */
    char b[12];
    int n = c_fmt(b);
    int r = salloc(n);
    c_mcpy(r + 1, b - nul, n);
    return r;
}

int rt_val(int s) {     /* VAL: the number at the start of s (spaces, a sign, digits, a point, to 4 decimals: the rest is
                           dropped, not rounded), on the number stack; 0 if there is none */
    char *p = nul + s;
    int l = slen(s);
    int i = 1;
    int neg = 0;
    int d;
    int f = 0;
    int k = 0;
    int pw = 1000;
    c_fromi(0);
    while (i <= l && p[i] == ' ') i = i + 1;
    if (i <= l && (p[i] == '-' || p[i] == '+')) {
        neg = p[i] == '-';
        i = i + 1;
    }
    while (i <= l) {
        d = p[i] - '0';
        if (d < 0 || d > 9) {
            if (d != -2 || k) break;        /* the point, once */
            k = 1;
        } else if (k) {
            f = f + d * pw;
            pw = pw / 10;
        } else {
            c_fromi(10);
            c_mul();
            c_fromi(d);
            c_add();
        }
        i = i + 1;
    }
    if (f) {
        c_fromi(f);
        c_fromi(10000);
        c_div();
        c_add();
    }
    if (neg) {
        c_fromi(-1);
        c_mul();
    }
    sfree(s);
    return 0;
}

char ib[126];           /* INPUT's line, and where we are in it; bas's command line too (idle while a program runs) */
int il;
int ii;
int fs;                 /* the field ifield found: from fs, fl bytes */
int fl;

int iov;                /* iread cut a line: it was too long */

int iread() {           /* a line of stdin appended to ib (bas's command lines too): 0 at the end of the input */
    int n = il;
    int c;
    while (1) {
        if (read(0, pb, 1) <= 0) {      /* a byte a call: no read-ahead to keep, and no buffer */
            if (n == il) return 0;
            break;
        }
        c = pb[0];
        if (c == '\n' || c == '\r') break;
        if (n < 124) {
            ib[n] = c;
            n = n + 1;
        } else iov = 1;
    }
    ib[n] = 0;
    il = n;
    return 1;
}

int iline() {           /* INPUT's next line, or BREAK at the end of the input */
    if (!iread()) c_throw(9);
    col = 0;                /* the console echoed the return */
    return 0;
}

int ic() {              /* the byte of ib at ii */
    return ib[ii];
}

int iskip(int c) {      /* ii on to the byte c or the end */
    while (ic() && ic() != c) ii = ii + 1;
    return 0;
}

int ifield() {          /* the next field of ib from ii, as MS: leading spaces dropped, "quoted" as it is,
                           else up to the comma without the trailing spaces. 0 when ii is past the end */
    int e;
    int q;
    if (ii > il) return 0;
    while (ic() == ' ') ii = ii + 1;
    q = ic() == '"';
    ii = ii + q;            /* past the quote */
    fs = ii;
    if (q) {
        iskip('"');
        fl = ii - fs;
        if (ic()) ii = ii + 1;
    }
    iskip(',');
    if (!q) {
        e = ii;
        while (e > fs && ib[e - 1] == ' ') e = e - 1;
        fl = e - fs;
    }
    ii = ii + 1;
    return 1;
}

int inum(int s, int n) {        /* ib[s, s+n) is a number as rt_val reads it (or empty, which is 0): a sign,
                                   then digits and one point */
    int e = s + n;
    int d = 0;
    int p = 0;
    int c;
    if (n && (ib[s] == '+' || ib[s] == '-')) s = s + 1;
    while (s < e) {
        c = ib[s];
        if (c == '.' && !p) p = 1;
        else if (c >= '0' && c <= '9') d = 1;
        else return 0;
        s = s + 1;
    }
    return d || !n;
}

int rt_inp(int s, int m) {      /* INPUT: the prompt s (0: none), then n = m / 128 variables, m & 127 bit k set
                                   for a number. Reads lines until each field fits its variable, as MS:
                                   ?? for more, ?REDO FROM START for a bad number, ?EXTRA IGNORED */
    int n = m / 128;
    int k;
    int ok;
    rt_prs(s);
    while (1) {
        outs("? ");
        il = 0;
        iline();
        while (1) {
            ii = 0;
            k = 0;
            while (ifield()) k = k + 1;
            if (k >= n) break;
            outs("??");
            ib[il] = ',';
            il = il + 1;
            iline();
        }
        ii = 0;
        ok = 1;
        for (k = 0; k < n; k = k + 1) {
            ifield();
            if (((m >> k) & 1) && !inum(fs, fl)) ok = 0;
        }
        if (ok) break;
        outs("?REDO FROM START\n");
    }
    if (ii <= il) outs("?EXTRA IGNORED\n");
    ii = 0;
    return 0;
}

int rt_ifld() {         /* the next field of the line rt_inp read, as a temporary */
    int t = 0;
    ifield();
    if (fl) {
        t = salloc(fl);
        c_mcpy(t + 1, ib + fs - nul, fl);
    }
    return t;
}

int rt_sub(int i, int n) {      /* a subscript i of 0 to n: itself, else BAD SUBSCRIPT */
    if (i < 0 || i > n) c_throw(14);
    return i;
}

int rt_sw(int a, int v) {       /* the word v at a (an array element's address) */
    putw(nul + a, v);
    return 0;
}

int slen(int s) {       /* a string's length; "" (0) has none. Here, after the runtime the compiled
                           code calls (rt_prs to rt_sw), its address marks that block's end (rtid) */
    if (s) return nul[s];
    return 0;
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
            if (un) f = w - c >= n;
            else f = w < 0;
        }
        if (op == 106 /* PO_LAW */ || op == 122 /* PO_SAW */ || op == 200 /* x LDV */ || op == 202 /* x STV */) f = 1;
        if (f) {
            b = vb;
            f = 1 << 15;
        }
        if (op == 82 /* PO_NCAL */) b = &rt_mark - nul;
        if (op == 84 /* PO_CALL */) b = &rt_prs - nul;
        if (op == 196 /* PO_JUMP */) b = c;
        if (b || op == 38 /* PO_LA */ || op == 44 /* PO_CW */) k = 3;
        else if (op == 42 /* PO_CB */ || (op > 75 && op < 81) /* BRFLS, BRTRU, BRNCH */) k = 2;
        else if (op == 46 /* PO_CS */) k = p[i + 1] + 2;
        else if (op == 204 /* x LDK */) k = 5;      /* 4 bytes of constant, not code */
        if (un) b = 0 - b;
        if (b) putw(p + i + 1, w + b + f);
        i = i + k;
    }
    return 0;
}

int rtid() {            /* what a compiled file must agree with: the sizes of the two runtime blocks its
                           offsets are in (rt.s's natives and the bytecode from rt_prs to slen) */
    return (&rt_end - nul - (&rt_mark - nul)) * 3 + (&slen - nul - (&rt_prs - nul));
}
