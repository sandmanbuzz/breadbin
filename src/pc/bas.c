/* bas: Breadbin's compiled BASIC (docs/design/basic.md), slice L3c: the line store, LIST, NEW,
   RUN [n], PRINT, LET, numbers (fixed point, x 10^4) and A% integers, expressions, IF/THEN,
   GOTO, GOSUB/RETURN, FOR/NEXT/STEP, END and STOP, with runtime errors by line. It is /bin/bas
   until it replaces /bin/basic (L3e).

   The program is kept as text, sorted by line number. RUN compiles all of it to p-code and
   calls that (icall); a line typed without a number is compiled after the program's code and
   run the same way. The compiled code calls the native routines in bas-rt.s (numbers, errors,
   jumps) and the rt_ functions below, by address.

   Memory is one arena, mem[] (msz bytes, as many as the machine has free): the program text from the bottom, the compiled code after it, and
   the variables from the top down. Editing the program or RUN clears the variables, as in MS.

   Mini C (tools/cc.py --pcode); built by mk/pvm.mk with src/pc/bas-rt.s; tested by
   tools/test_bas.py and tools/test_bas_rt.py (py65) and tests/test_pvm_machine.py (VICE). An
   opcode is written as its number with its name in a comment, which tools/test_bas.py checks
   against src/pvm/pvm.inc. */

/* xops */
/* fstack 768 */   /* the VM's frame stack: 256 bytes under the 1024 default, for memory (cc_pcode) */

extern int rt_mark();   /* bas-rt.s, for the compiled code: these take their arguments from the */
extern int rt_go();     /* eval stack and the number stack as the comments there say; the */
extern int rt_ln();     /* compiler only takes their addresses */
extern int c_ldv(char *p); /* xop 240 */      /* bas-rt.s, for the mini C: one result each */
extern int c_stv(char *p); /* xop 246 */
extern int c_add();
extern int c_mul();
extern int c_div();
extern int c_int();
extern int c_toi();
extern int c_fromi(int i);
extern int c_cmp();
extern int c_mac(int d);
extern int c_fmt(char *buf);
extern int c_throw(int e);
extern int c_err();
extern int c_curip();
extern int c_nclr();
extern int c_crunch(char *buf, char *kwt);
extern int c_find(char *mem, int top, int n);
extern int c_sp(); /* xop 232 */      /* bas-rt.s: the scanner and the code emitter, on these globals */
extern int c_digit(); /* xop 242 */
extern int c_letter(); /* xop 252 */
extern int c_tok(int t); /* xop 234 */
extern int c_ult(int a, int b); /* xop 254 */
extern int c_emit(int b); /* xop 236 */
extern int c_room(int n); /* xop 248 */
extern int c_op1(int b); /* xop 238 */
extern int c_opw(int b, int w); /* xop 250 */
extern int c_ncall(char *f); /* xop 244 */
extern int c_xop(int b);
extern int c_xopw(int b, int w);
extern int c_grow(int n);       /* up to n pages from the kernel for mem (bas-rt.s); the pages granted */

char *mem;              /* MEM: the arena, msz bytes of pages the kernel grants at start (c_grow) */
int msz;
int ptop;               /* the program text: [0, ptop); per line its number (low, high), length,
                           the offset of its code (low, high), then the text */
int pend;               /* the program's code: [ptop, pend); 0 when out of date */
int cend;               /* the end of the code */
int vbot;               /* the variables: [vbot, MEM) */
int straight;           /* bytes since the VM last reset Y: pvm.s addresses code as base + Y */
int err;                /* the error numbers are emsg's */
int eline;              /* the line a compile error is in */
char emsg[] = "SYNTAX|OUT OF MEMORY|LINE TOO LONG|OVERFLOW|DIVISION BY ZERO|ILLEGAL QUANTITY|RETURN WITHOUT GOSUB|NEXT WITHOUT FOR|BREAK|UNDEF'D STATEMENT|FORMULA TOO COMPLEX|";
char kwt[] = "ABS|AND|BYE|END|FOR|GOSUB|GOTO|GO|IF|INT|LET|LIST|NEW|NEXT|NOT|OR|PRINT|REM|RETURN|RUN|SGN|STEP|STOP|SYSTEM|THEN|TO|";
                        /* the keywords: the program holds each as a token, 128 + its place
                           here, written as the number with "tk NAME" in a comment (test_bas checks the
                           numbers; bas-rt.s has PRINT's and REM's); a keyword before its prefixes, as
                           the first that matches wins (so TOTAL is TO TAL, as MS) */
char lbuf[162];         /* the line being read or compiled, NUL-ended */
char *src;
int si;                 /* the parse position in src */
int cur;                /* the line being compiled; -1 in immediate mode */
int nd;                 /* the compiled code's depth on the number stack */
int ed;                 /* and on the eval stack */
int vint;               /* the last variable parsed is an integer (A%) */
int ifs[8];             /* this line's IFs: where their branch offsets go */
int nif;
int fpos[32];           /* forward GOTOs: where the address goes, the target, the line */
int ftgt[32];
int fln[32];
int nfix;
char ctl[192];          /* GOSUB and FOR entries, each with its tag last: G (3 bytes) the return
                           address; F (13) the variable, the body, the limit and the step */
int csp;
char kbuf[4];
char ibuf[64];         /* standard input */
int ipos;
int ilen;
char obuf[64];         /* standard output, flushed at each newline and before each read */
int olen;
int col;                /* the output column */
char *nul;              /* 0: an address minus nul is the address as an int */

/* ---- output ---- */

int flush() {
    if (olen) write(1, obuf, olen);
    olen = 0;
    return 0;
}

int outc(int c) {
    if (olen == 64) flush();
    obuf[olen] = c;
    olen = olen + 1;
    col = col + 1;
    if (c == '\n') {
        col = 0;
        flush();
    }
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

/* ---- input ---- */

int getline() {         /* the next line of stdin into lbuf: its length, -1 at the end, -2 too long */
    int n = 0;
    int over = 0;
    int c;
    while (1) {
        if (ipos == ilen) {
            flush();
            ilen = read(0, ibuf, 64);
            ipos = 0;
            if (ilen <= 0) {
                ilen = 0;
                if (n == 0 && !over) return -1;
                break;
            }
        }
        c = ibuf[ipos];
        ipos = ipos + 1;
        if (c == '\n' || c == '\r') break;
        if (n < 160) {
            lbuf[n] = c;
            n = n + 1;
        } else over = 1;
    }
    lbuf[n] = 0;
    if (over) return -2;
    return n;
}

int normal() {          /* lbuf in place (c_crunch): keywords to tokens and the rest upper case,
                           outside quotes; tabs to spaces and runs of them to one, none leading
                           or trailing (but inside an unclosed string); a REM's text as typed.
                           Returns the length, or -1 for a byte above 127 outside quotes */
    return c_crunch(lbuf, kwt);
}

/* ---- parsing: c_sp, c_digit, c_letter and c_tok (bas-rt.s) read src[si] ---- */

int fail(int e) {       /* error e, unless one came first */
    if (!err) err = e;
    return 0;
}

int number() {          /* a line number at si (0 to 63999, unsigned), spaces among its digits
                           and after it skipped, as MS; none or too big is a syntax error */
    int n = 0;
    if (!c_digit()) fail(1);
    while (c_digit()) {
        if (n > 6399) fail(1);
        n = n * 10 + src[si] - '0';
        si = si + 1;
        c_sp();
    }
    if (c_ult(63999, n)) fail(1);
    return n;
}

int getw(char *p) {
    return p[0] + (p[1] << 8);
}

int putw(char *p, int w) {
    p[0] = w;
    p[1] = w >> 8;
    return 0;
}

int addr(int i) {       /* mem[i] as an address */
    return mem - nul + i;
}

/* ---- the line store ----
   mem from 0 to ptop holds the lines in order, each: its number (2 bytes), the length of its
   text, the offset of its code (2 bytes, set when it is compiled), the text, a 0. The compiled
   code follows from ptop to pend (0 when out of date), then free space, then the variables
   from vbot to the top. */

int lineno(int p) {
    return getw(mem + p);
}

int next(int p) {
    return p + 6 + mem[p + 2];
}

int find(int n) {       /* the first line numbered n or above */
    return c_find(mem, ptop, n);
}

int move(char *d, char *s, int n) {
    int i = 0;
    if (d - s > 0) {
        while (n > 0) {
            n = n - 1;
            d[n] = s[n];
        }
    } else {
        while (i < n) {
            d[i] = s[i];
            i = i + 1;
        }
    }
    return 0;
}

int clearv() {          /* no variables, and the compiled program is out of date */
    vbot = msz;
    pend = 0;
    return 0;
}

int store(int n, int t, int len) {  /* line n is lbuf from t, len bytes; none deletes it */
    int p = find(n);
    int old = 0;
    int add = 0;
    if (p < ptop && lineno(p) == n) old = next(p) - p;
    if (len) add = len + 6;
    if (ptop - old + add > msz) {
        fail(2);
        return 0;
    }
    move(mem + p + add, mem + p + old, ptop - p - old);
    ptop = ptop - old + add;
    if (len) {
        putw(mem + p, n);
        mem[p + 2] = len;
        move(mem + p + 5, lbuf + t, len);
        mem[p + 5 + len] = 0;   /* the compiler reads the text in place */
    }
    return clearv();    /* as MS: an edit clears the variables */
}

int list(int a, int b) {
    int p = 0;
    int n;
    int i;
    int c;
    int q;              /* 1 in a string, 2 in a REM: no tokens there */
    int k;
    int t;
    while (p < ptop) {
        n = lineno(p);
        if (!c_ult(n, a) && !c_ult(b, n)) {
            outu(n);
            outc(' ');
            q = 0;
            for (i = p + 5; mem[i]; i = i + 1) {
                c = mem[i];
                if (c == '"' && q < 2) q = 1 - q;
                if (c < 128 || q) outc(c);
                else {          /* a token: its keyword */
                    k = 0;
                    for (t = 128; t < c; t = t + 1) {
                        while (kwt[k] != '|') k = k + 1;
                        k = k + 1;
                    }
                    while (kwt[k] != '|') {
                        outc(kwt[k]);
                        k = k + 1;
                    }
                    if (c == 145 /* tk REM */) q = 2;
                }
            }
            outc('\n');
        }
        p = next(p);
    }
    return 0;
}

/* ---- the code generator ----
   c_emit, c_room, c_op1, c_opw and c_ncall (bas-rt.s) write the code at cend. Past 240 bytes
   since the VM last reset Y, c_room puts a branch to the next instruction, which resets it (as
   cc_pcode's op()). No line reaches it today: each starts with CALL rt_ln and 160 characters
   compile to under 240 bytes between calls; it is kept so that a new statement cannot break Y. */

int ecall(char *f) {    /* CALL f, DROP its result */
    c_ncall(f);
    return c_op1(48 /* PO_DROP */);
}

int pushint(int v) {    /* the int v (0 to 32767) on the eval stack */
    if (v < 16) return c_op1(v * 2);      /* CN */
    if (v < 256) {
        c_room(2);
        c_emit(42 /* PO_CB */);
        return c_emit(v);
    }
    return c_opw(44 /* PO_CW */, v);
}

int begin() {           /* a bytecode function's header: JSR pvm_interp, as main's */
    char *m = &main;
    c_emit(m[0]);
    c_emit(m[1]);
    c_emit(m[2]);
    straight = 0;
    return 0;
}

int prologue() {        /* the entry of a run: an error comes back here (rt_mark then gives 1),
                           and the run returns */
    begin();
    c_ncall(&rt_mark);
    c_opw(76 /* PO_BRFLS */, 4);  /* to the body, past the CN 0 and RET */
    c_emit(0 /* PO_CN 0 */);
    c_emit(92 /* PO_RET */);
    return 0;
}

int finish() {
    c_room(2);
    c_emit(0 /* PO_CN 0 */);
    c_emit(92 /* PO_RET */);
    return 0;
}

/* ---- the runtime the compiled code calls ---- */

int rt_prs(char *s) {   /* a CS string: length, then the text */
    int i;
    for (i = 1; i <= s[0]; i = i + 1) outc(s[i]);
    return 0;
}

int rt_prn() {          /* PRINT a number: a sign or a space before it, a space after */
    char b[12];
    int n = c_fmt(b);
    int i;
    for (i = 0; i < n; i = i + 1) outc(b[i]);
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

char pb[4];
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

/* ---- expressions: a kind, 1 for a number (on the number stack), 2 for an int (eval) ---- */

int npush(int d) {
    nd = nd + d;
    if (nd > 14) fail(11);      /* bas-rt.s holds 16; rt_pow and rt_next use 2 */
    return 1;
}

int epush(int d) {
    ed = ed + d;
    if (ed > 6) fail(11);
    return 2;
}

int tonum(int k) {
    if (k == 2) {
        c_xop(226 /* x FROMI */);
        epush(-1);
        npush(1);
    }
    return 1;
}

int toint(int k) {
    if (k == 1) {
        c_xop(228 /* x TOI */);
        npush(-1);
        epush(1);
    }
    return 2;
}

int var() {             /* the variable at si (a letter): its value's address, made 0 if new;
                           vint says whether it is an integer. Two characters count, as MS */
    int c1 = src[si];
    int c2 = 0;
    int p = vbot;
    int size;
    si = si + 1;
    while (c_letter() || c_digit()) {   /* a keyword is a token: it ends the name */
        if (!c2) c2 = src[si];
        si = si + 1;
    }
    vint = 0;
    if (src[si] == '%') {
        si = si + 1;
        vint = 1;
        c2 = c2 | 128;
    } else if (src[si] == '$') fail(1);       /* strings come with L3d */
    while (p < msz) {
        if (mem[p] == c1 && mem[p + 1] == c2) return addr(p + 2);
        p = p + 6 - (mem[p + 1] & 128) / 64;
    }
    size = 6 - vint * 2;
    if (vbot - size < cend) {
        fail(2);
        return 0;
    }
    vbot = vbot - size;
    mem[vbot] = c1;
    mem[vbot + 1] = c2;
    for (p = 2; p < size; p = p + 1) mem[vbot + p] = 0;
    return addr(vbot + 2);
}

int constant() {        /* a number at si: digits, a point, digits (spaces among them skipped,
                           as MS); past 4 decimals it is rounded */
    int o = 0;
    int ip = 0;
    int big = 0;
    int fd = 0;
    int f[4];
    int r = 0;
    int any = 0;
    int d;
    int i;
    for (i = 0; i < 4; i = i + 1) {
        kbuf[i] = 0;
        f[i] = 0;
    }
    c_nclr();
    c_ldv(kbuf);
    while (c_digit()) {
        d = src[si] - '0';
        o = o | c_mac(d);
        if (ip > 3276 || (ip == 3276 && d > 7)) big = 1;
        else ip = ip * 10 + d;
        si = si + 1;
        c_sp();
        any = 1;
    }
    if (src[si] == '.') {
        si = si + 1;
        c_sp();
        while (c_digit()) {
            d = src[si] - '0';
            if (fd < 4) f[fd] = d;
            else if (fd == 4) r = d >= 5;
            if (fd < 5) fd = fd + 1;
            si = si + 1;
            c_sp();
            any = 1;
        }
    }
    if (!any) fail(1);
    for (i = 0; i < 3; i = i + 1) o = o | c_mac(f[i]);
    o = o | c_mac(f[3] + r);
    c_stv(kbuf);
    if (o) fail(4);
    if (!big && !(f[0] | f[1] | f[2] | f[3] | r)) {
        pushint(ip);
        c_xop(226 /* x FROMI */);
        return npush(1);
    }
    c_room(5);
    c_emit(204 /* x LDK */);
    for (i = 0; i < 4; i = i + 1) c_emit(kbuf[i]);
    straight = 0;       /* the VM renormalises IP past the operand */
    return npush(1);
}

int deep;
int fn(int f) {       /* a function of one number: f(...) */
    c_sp();
    if (src[si] != '(') {
        fail(1);
        return 1;
    }
    deep = deep + 1;       /* a function's frames count as a second level of nesting */
    if (deep > 15) fail(11);
    else tonum(primary());
    deep = deep - 1;
    c_xop(f);
    return 1;
}

int primary() {
    int k;
    c_sp();
    if (src[si] == '(') {
        si = si + 1;
        k = expr();
        c_sp();
        if (src[si] == ')') si = si + 1;
        else fail(1);
        return k;
    }
    if (c_digit() || src[si] == '.') return constant();
    if (c_tok(128 /* tk ABS */)) return fn(222 /* x ABS */);
    if (c_tok(137 /* tk INT */)) return fn(220 /* x INT */);
    if (c_tok(148 /* tk SGN */)) return fn(224 /* x SGN */);
    if (c_letter()) {
        k = var();
        if (vint) {
            c_opw(106 /* PO_LAW */, k);
            return epush(1);
        }
        c_xopw(200 /* x LDV */, k);
        return npush(1);
    }
    fail(1);
    return 1;
}

int relop(int m) {      /* the VM's compare of n_cmp's -1, 0 or 1 with 0: -1 when true */
    if (m == 1) return c_op1(70 /* PO_ISLT */);
    if (m == 2) return c_op1(64 /* PO_ISEQ */);
    if (m == 3) return c_op1(74 /* PO_ISLE */);
    if (m == 4) return c_op1(68 /* PO_ISGT */);
    if (m == 5) return c_op1(66 /* PO_ISNE */);
    return c_op1(72 /* PO_ISGE */);
}

int operand() {         /* a primary, or - + NOT and theirs. Each ( and unary op nests through
                           here: past 15 the compiler's own frames would run out (the frame
                           stack is 768 bytes) */
    int k = 1;
    int c;
    deep = deep + 1;
    if (deep > 15) fail(11);
    else {
        c = c_sp();
        if (c == '-') {         /* binds looser than ^, as MS: -2^2 is -4 */
            si = si + 1;
            tonum(climb(10));
            c_xop(216 /* x NEG */);
        } else if (c == '+') {
            si = si + 1;
            k = climb(10);
        } else if (c == 142 /* tk NOT */) {    /* of the relation after it, as MS */
            si = si + 1;
            toint(climb(6));
            c_op1(146 /* PO_COMP */);
            k = 2;
        } else k = primary();
    }
    deep = deep - 1;
    return k;
}

int binop(int c) {      /* the precedence of the binary operator c; 0 for none */
    if (c == '^') return 10;
    if (c == '*' || c == '/') return 8;
    if (c == '+' || c == '-') return 7;
    if (c == '<' || c == '=' || c == '>') return 6;
    if (c == 129 /* tk AND */) return 4;
    if (c == 143 /* tk OR */) return 3;
    return 0;
}

int climb(int min) {    /* the operators of precedence min and up, each left to right (as MS:
                           2^3^2 is 64). Returns the result's kind: 1 a number, 2 an int.
                           Relations (= < > <= >= <>, and =< => >< as MS) give -1 or 0; the
                           exponent of ^ is a whole number, which may be negative */
    int k = operand();
    int c;
    int p;
    int m;
    int b;
    while (!err) {
        c = c_sp();
        p = binop(c);
        if (p < min) return k;      /* none is 0 */
        if (p == 6) {
            m = 0;
            while (1) {
                b = 0;
                if (c == '<') b = 1;
                if (c == '=') b = 2;
                if (c == '>') b = 4;
                if (!b) break;
                if (m & b) fail(1);
                m = m | b;
                si = si + 1;
                c = c_sp();
            }
            if (m == 7) fail(1);
            tonum(k);
            tonum(climb(7));
            c_xop(218 /* x CMP */);
            npush(-2);
            epush(1);
            c_op1(0 /* PO_CN 0 */);
            epush(1);
            relop(m);
            k = epush(-1);
            continue;
        }
        si = si + 1;
        if (p <= 4) {
            toint(k);
            toint(climb(p + 1));
            if (p == 4) c_op1(148 /* PO_BAND */);
            else c_op1(150 /* PO_IOR */);
            k = epush(-1);
            continue;
        }
        tonum(k);
        tonum(climb(p + 1));
        if (c == '^') ecall(&rt_pow);
        else if (c == '*') c_xop(212 /* x MUL */);
        else if (c == '/') c_xop(214 /* x DIV */);
        else if (c == '+') c_xop(208 /* x ADD */);
        else c_xop(210 /* x SUB */);
        k = npush(-1);
    }
    return k;
}

int expr() {
    return climb(1);
}

/* ---- statements ---- */

int assign(int a, int isint, int k) {
    if (isint) {
        toint(k);
        c_opw(122 /* PO_SAW */, a);
        epush(-1);
        return 0;
    }
    tonum(k);
    c_xopw(202 /* x STV */, a);
    npush(-1);
    return 0;
}

int let() {             /* [LET] v = expression */
    int a;
    int i;
    c_sp();
    if (!c_letter()) {
        fail(1);
        return 0;
    }
    a = var();
    i = vint;
    c_sp();
    if (src[si] != '=') {
        fail(1);
        return 0;
    }
    si = si + 1;
    return assign(a, i, expr());
}

int prints() {          /* PRINT: strings and numbers; ; between them, or after the last for no
                           newline; , to the next column of 10 */
    int nl = 1;
    int i;
    int n;
    while (!err) {
        c_sp();
        if (src[si] == 0 || src[si] == ':') break;
        if (src[si] == ';') {
            si = si + 1;
            nl = 0;
            continue;
        }
        if (src[si] == ',') {
            si = si + 1;
            ecall(&rt_tab);
            nl = 0;
            continue;
        }
        nl = 1;
        if (src[si] != '"') {
            tonum(expr());
            ecall(&rt_prn);
            npush(-1);
            continue;
        }
        si = si + 1;
        i = si;
        while (src[si] && src[si] != '"') si = si + 1;
        n = si - i;
        if (src[si]) si = si + 1;   /* an unclosed string ends at the end of the line, as MS */
        if (n) {
            c_room(2);
            c_emit(46 /* PO_CS */);
            c_emit(n);
            while (i < si && src[i] != '"') {
                c_emit(src[i]);
                i = i + 1;
            }
            straight = n + 1;       /* CS moves the base to the string: the next op is past it */
            ecall(&rt_prs);
        }
    }
    if (nl) ecall(&rt_nl);
    return 0;
}

int jump(int t) {       /* JUMP to line t: a line not compiled yet is fixed up when it is */
    int p;
    c_room(3);
    c_emit(196 /* PO_JUMP */);
    straight = 0;
    if (cur != -1 && c_ult(cur, t)) {
        if (nfix == 32) {
            fail(2);
            return 0;
        }
        fpos[nfix] = cend;
        ftgt[nfix] = t;
        fln[nfix] = cur;
        nfix = nfix + 1;
        c_emit(0);
        return c_emit(0);
    }
    p = find(t);
    if (p == ptop || lineno(p) != t || (cur == -1 && !pend)) {
        fail(10);
        return 0;
    }
    p = addr(getw(mem + p + 3));
    c_emit(p);
    return c_emit(p >> 8);
}

int gotol() {
    c_sp();
    if (!c_digit()) {
        fail(1);
        return 0;
    }
    return jump(number());
}

int ifs_() {            /* IF e THEN n | statements, IF e GOTO n: false goes to the next line */
    int k = expr();
    if (k == 1) {
        c_xop(230 /* x TST */);
        npush(-1);
        epush(1);
    }
    if (nif == 8) {
        fail(11);
        return 0;
    }
    c_room(3);
    c_emit(76 /* PO_BRFLS */);
    ifs[nif] = cend;
    nif = nif + 1;
    c_emit(0);
    c_emit(0);
    epush(-1);
    c_sp();
    if (c_tok(134 /* tk GOTO */)) return gotol();
    if (!c_tok(152 /* tk THEN */)) {
        fail(1);
        return 0;
    }
    c_sp();
    if (c_digit()) return gotol();
    return stmt();
}

int fors() {            /* FOR v = a TO b [STEP c] */
    int a;
    c_sp();
    if (!c_letter()) {
        fail(1);
        return 0;
    }
    a = var();
    if (vint) fail(1);  /* as MS: the variable is a number */
    c_sp();
    if (src[si] != '=') {
        fail(1);
        return 0;
    }
    si = si + 1;
    assign(a, 0, expr());
    c_sp();
    if (!c_tok(153 /* tk TO */)) {
        fail(1);
        return 0;
    }
    tonum(expr());
    c_sp();
    if (c_tok(149 /* tk STEP */)) tonum(expr());
    else {
        c_op1(2 /* PO_CN 1 */);
        c_xop(226 /* x FROMI */);
        npush(1);
    }
    c_room(9);            /* so that the body is 10 bytes on */
    c_opw(44 /* PO_CW */, addr(cend + 10));
    c_opw(44 /* PO_CW */, a);
    ecall(&rt_for);
    c_ncall(&rt_ln);      /* the body starts here */
    npush(-2);
    return 0;
}

int nexts() {           /* NEXT [v [, w ...]] */
    int a;
    while (!err) {
        c_sp();
        a = 0;
        if (c_letter()) {
            a = var();
            if (vint) fail(1);
        }
        c_opw(44 /* PO_CW */, a);
        c_ncall(&rt_next);
        c_ncall(&rt_go);
        c_sp();
        if (src[si] != ',') return 0;
        si = si + 1;
    }
    return 0;
}

int stmt() {
    c_sp();
    if (c_tok(144 /* tk PRINT */)) return prints();
    if (c_tok(145 /* tk REM */)) {
        while (src[si]) si = si + 1;
        return 0;
    }
    if (c_tok(138 /* tk LET */)) return let();
    if (c_tok(136 /* tk IF */)) return ifs_();
    if (c_tok(133 /* tk GOSUB */)) {
        c_room(6);        /* the return address is 10 bytes on */
        c_opw(44 /* PO_CW */, addr(cend + 10));
        ecall(&rt_gosub);
        gotol();
        c_ncall(&rt_ln);  /* the return address: the line is current again */
        return 0;
    }
    if (c_tok(134 /* tk GOTO */)) return gotol();
    if (c_tok(135 /* tk GO */)) {     /* GO TO */
        c_sp();
        if (c_tok(153 /* tk TO */)) return gotol();
        fail(1);
        return 0;
    }
    if (c_tok(146 /* tk RETURN */)) {
        c_ncall(&rt_return);
        return c_ncall(&rt_go);
    }
    if (c_tok(132 /* tk FOR */)) return fors();
    if (c_tok(141 /* tk NEXT */)) return nexts();
    if (c_tok(131 /* tk END */)) {
        c_op1(0 /* PO_CN 0 */);
        return c_op1(92 /* PO_RET */);
    }
    if (c_tok(150 /* tk STOP */)) {
        c_op1(18 /* PO_CN 9 */);
        return c_ncall(&c_throw);
    }
    if (c_letter()) return let();
    fail(1);
    return 0;
}

int stmts() {           /* the statements of src from si, : between them */
    while (!err) {
        c_sp();
        if (src[si] == 0) return 0;
        if (src[si] == ':') {
            si = si + 1;
            continue;
        }
        stmt();
        if (err) return 0;
        c_sp();
        if (src[si] == ':') si = si + 1;
        else if (src[si]) fail(1);
    }
    return 0;
}

int endline() {         /* the IFs' false branches come here */
    int i;
    for (i = 0; i < nif; i = i + 1) putw(mem + ifs[i], cend - ifs[i]);
    nif = 0;
    return 0;
}

int cline(int p) {      /* compile the line at p */
    int n = lineno(p);
    int i = 0;
    putw(mem + p + 3, cend);
    while (i < nfix) {  /* the GOTOs waiting for this line, or for one that is not there */
        if (ftgt[i] == n) putw(mem + fpos[i], addr(cend));
        else if (c_ult(ftgt[i], n)) {
            fail(10);
            eline = fln[i];
            return 0;
        } else {
            i = i + 1;
            continue;
        }
        nfix = nfix - 1;
        fpos[i] = fpos[nfix];
        ftgt[i] = ftgt[nfix];
        fln[i] = fln[nfix];
    }
    cur = n;
    c_xop(206 /* x LN */);
    src = mem + p + 5;
    si = 0;
    nd = 0;
    ed = 0;
    stmts();
    endline();
    if (err) eline = n;
    return 0;
}

int compile() {         /* the program into code from ptop: pend, or err and eline */
    int p = 0;
    nfix = 0;
    nif = 0;
    eline = -1;
    pend = 0;
    cend = ptop;
    prologue();
    while (p < ptop && !err) {
        cline(p);
        p = next(p);
    }
    finish();
    if (nfix && !err) {
        fail(10);
        eline = fln[0];
    }
    if (!err) pend = cend;
    return 0;
}

/* ---- commands ---- */

int report(int e, int line) {   /* error e as MS prints it; line -1 for none */
    int i = 0;
    fresh();
    if (e == 9) outs("BREAK");
    else {
        outc('?');
        while (e > 1) {
            if (emsg[i] == '|') e = e - 1;
            i = i + 1;
        }
        while (emsg[i] != '|') {
            outc(emsg[i]);
            i = i + 1;
        }
        outs(" ERROR");
    }
    if (line != -1) {
        outs(" IN ");
        outu(line);
    }
    outc('\n');
    err = 0;
    return 0;
}

int go(int at) {        /* run the code at mem[at]; then report an error, with its line */
    int e;
    int a;
    int p;
    int ln = -1;
    csp = 0;
    icall(mem + at);
    e = c_err();
    if (!e) return 0;
    a = c_curip() - (mem - nul);
    if (pend && a > ptop && a <= pend)
        for (p = 0; p < ptop; p = next(p)) if (getw(mem + p + 3) < a) ln = lineno(p);
    return report(e, ln);
}

int run(int t, int has) {       /* RUN [t] */
    clearv();
    compile();
    if (err) return report(err, eline);
    if (!has) return go(ptop);
    cend = pend;
    cur = -1;
    prologue();
    jump(t);
    if (err) return report(err, -1);
    return go(pend);
}

int ended() {           /* nothing after a command but spaces, and no error so far */
    c_sp();
    if (src[si]) fail(1);
    return !err;
}

int immediate() {       /* compile the line after the program's code (compiling the program
                           first, for GOTO, if it is out of date) */
    int at;
    if (!pend && ptop) {
        compile();
        err = 0;
        src = lbuf;     /* compile() read the program's lines */
        si = 0;
    }
    cend = pend;
    if (!cend) cend = ptop;
    at = cend;
    cur = -1;
    nd = 0;
    ed = 0;
    nif = 0;
    prologue();
    c_xop(206 /* x LN */);
    stmts();
    endline();
    finish();
    return at;
}

int command() {         /* a line without a number */
    int a = 0;
    int b = -1;
    int at;
    if (c_tok(139 /* tk LIST */)) {
        c_sp();
        if (c_digit()) {
            a = number();
            b = a;
        }
        c_sp();
        if (src[si] == '-') {
            si = si + 1;
            c_sp();
            b = -1;
            if (c_digit()) b = number();
        }
        if (!ended()) return report(err, -1);
        return list(a, b);
    }
    if (c_tok(140 /* tk NEW */)) {
        if (!ended()) return report(err, -1);
        ptop = 0;
        return clearv();
    }
    if (c_tok(147 /* tk RUN */)) {
        c_sp();
        if (c_digit()) {
            a = number();
            b = 1;
        }
        if (!ended()) return report(err, -1);
        return run(a, b == 1);
    }
    if (c_tok(130 /* tk BYE */) || c_tok(151 /* tk SYSTEM */)) {
        if (!ended()) return report(err, -1);
        flush();
        exit(0);
    }
    at = immediate();
    if (err == 2 && pend) {     /* no room after the program: drop its code, as RUN recompiles */
        err = 0;
        pend = 0;
        cend = ptop;
        si = 0;
        at = ptop;
        prologue();
        c_xop(206 /* x LN */);
        stmts();
        endline();
        finish();
    }
    if (err) return report(err, -1);
    return go(at);
}

int main() {
    int tty = isatty(0);
    int n;
    int t;
    msz = c_grow(120) * 256;    /* as many pages as are free, to 30,720 bytes: ints stay positive */
    if (msz < 4096) {
        write(2, "bas: out of memory\n", 19);
        exit(1);
    }
    clearv();
    if (tty) {
        outu(vbot - ptop);
        outs(" BYTES FREE\nREADY.\n");
    }
    while (1) {
        n = getline();
        if (n == -1) break;
        if (n == -2) {
            report(3, -1);
            if (tty) {
                fresh();
                outs("READY.\n");
            }
            continue;
        }
        n = normal();
        if (n == 0) continue;
        if (n == -1) {
            report(1, -1);
            if (tty) {
                fresh();
                outs("READY.\n");
            }
            continue;
        }
        src = lbuf;
        si = 0;
        if (c_digit()) {  /* a numbered line: store it (no READY, as MS) */
            t = number();
            if (!err) store(t, si, n - si);
            if (!err) continue;
            report(err, -1);
        } else command();
        if (tty) {
            fresh();
            outs("READY.\n");
        }
    }
    flush();
    return 0;
}
