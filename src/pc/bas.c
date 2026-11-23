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
/* fstack 416 */   /* the VM frame stack: a measured size (tools/test_bas.py, the nesting sweep), with the nesting limit in climb */

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
extern int c_const(char *buf);
extern int c_fmt(char *buf);
extern int c_throw(int e);
extern int c_err();
extern int c_curip();
extern int c_crunch(char *buf, char *kwt);
extern int c_find(char *mem, int top, int n);
extern int c_sp(); /* xop 232 */      /* bas-rt.s: the scanner and the code emitter, on these globals */
extern int c_digit(); /* xop 242 */
extern int c_letter();
extern int c_tok(int t); /* xop 234 */
extern int c_ult(int a, int b);
extern int c_emit(int b); /* xop 236 */
extern int c_room(int n); /* xop 248 */
extern int c_op1(int b); /* xop 238 */
extern int c_opw(int b, int w); /* xop 250 */
extern int c_ncall(char *f); /* xop 244 */
extern int c_xop(int b); /* xop 254 */
extern int c_xopw(int b, int w);
extern int c_fail(int e); /* xop 252 */   /* err = e, unless one came first */
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
char lbuf[126];         /* the line being read or compiled, NUL-ended */
char *src;
int si;                 /* the parse position in src */
int cur;                /* the line being compiled; -1 in immediate mode */
int nd;                 /* the compiled code's depth on the number stack */
int ed;                 /* and on the eval stack */
int vint;               /* the last variable parsed is an integer (A%) */
int ifs[8];             /* this line's IFs: where their branch offsets go */
int nif;
int *inul;              /* 0, for fx */
int *fx;                /* forward GOTOs, in ctl while compiling (a run starts with it empty): where
                           the address goes (fx[0-31]), the target (fx[32-63]), the line (fx[64-95]) */
int nfix;
char ctl[193];          /* GOSUB and FOR entries, each with its tag last: G (3 bytes) the return
                           address; F (13) the variable, the body, the limit and the step */
int csp;
char pb[4];             /* scratch: the byte outc writes, and the number rt_pow keeps */
int col;                /* the output column */
char *nul;              /* 0: an address minus nul is the address as an int */

/* ---- output ---- */

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

/* ---- input ---- */

int getline() {         /* the next line of stdin into lbuf: its length, -1 at the end, -2 too long */
    int n = 0;
    int over = 0;
    int c;
    while (1) {
        if (read(0, pb, 1) <= 0) {      /* a byte a call: no read-ahead to keep, and no buffer */
            if (n == 0 && !over) return -1;
            break;
        }
        c = pb[0];
        if (c == '\n' || c == '\r') break;
        if (n < 124) {
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


int number() {          /* a line number at si (0 to 63999, unsigned), spaces among its digits
                           and after it skipped, as MS; none or too big is a syntax error */
    int n = 0;
    if (!c_digit()) c_fail(1);
    while (c_digit()) {
        if (n > 6399) c_fail(1);
        n = n * 10 + src[si] - '0';
        si = si + 1;
        c_sp();
    }
    if (c_ult(63999, n)) c_fail(1);
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
        c_fail(2);
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

int list(int a, int b) {
    int p = 0;
    int n;
    int i;
    int c;
    int q;              /* 1 in a string, 2 in a REM: no tokens there */
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
                    outn(kwt, c - 128);
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

int pcall(char *f) {    /* CALL f, a bytecode function (c_ncall is for the natives) */
    c_opw(84 /* PO_CALL */, f - nul);
    straight = 0;
    return 0;
}

int ecall(char *f) {    /* CALL f, DROP its result */
    pcall(f);
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

int finish() {
    c_room(2);
    c_emit(0 /* PO_CN 0 */);
    c_emit(92 /* PO_RET */);
    return 0;
}

int prologue() {        /* the entry of a run: an error comes back here (rt_mark then gives 1),
                           and the run returns */
    c_ncall(&rt_mark);
    c_opw(76 /* PO_BRFLS */, 4);  /* to the body, past the CN 0 and RET */
    return finish();
}

/* ---- the runtime the compiled code calls ---- */

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

/* ---- expressions: a kind, 1 for a number (on the number stack), 2 for an int (eval) ---- */

int npush(int d) {
    nd = nd + d;
    if (nd > 14) c_fail(11);      /* bas-rt.s holds 16; rt_pow and rt_next use 2 */
    return 1;
}

int epush(int d) {
    ed = ed + d;
    if (ed > 6) c_fail(11);
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
    } else if (src[si] == '$') c_fail(1);       /* strings come with L3d */
    while (p < msz) {
        if (mem[p] == c1 && mem[p + 1] == c2) return addr(p + 2);
        p = p + 6 - (mem[p + 1] & 128) / 64;
    }
    size = 6 - vint * 2;
    if (vbot - size < cend) {
        c_fail(2);
        return 0;
    }
    vbot = vbot - size;
    mem[vbot] = c1;
    mem[vbot + 1] = c2;
    for (p = 2; p < size; p = p + 1) mem[vbot + p] = 0;
    return addr(vbot + 2);
}

int constant() {        /* a number at si: digits, a point, digits (spaces among them skipped,
                           as MS); past 4 decimals it is rounded. c_const reads it: a whole number
                           under 32768 comes back, anything else is -2 and its 4 bytes are in pb */
    int ip = c_const(pb);
    int i;
    if (ip >= 0) {
        pushint(ip);
        c_xop(226 /* x FROMI */);
        return npush(1);
    }
    c_room(5);
    c_emit(204 /* x LDK */);
    for (i = 0; i < 4; i = i + 1) c_emit(pb[i]);
    straight = 0;       /* the VM renormalises IP past the operand */
    return npush(1);
}

int deep;
int fn(int f) {       /* a function of one number: f(...) */
    if (c_sp() != '(') {
        c_fail(1);
        return 1;
    }
    deep = deep + 2;       /* fn and primary's frames, over the climb the '(' enters */
    tonum(primary());
    deep = deep - 2;
    c_xop(f);
    return 1;
}

int need(int t) {       /* the token t after spaces, or a syntax error */
    c_sp();
    if (c_tok(t)) return 1;
    c_fail(1);
    return 0;
}

int primary() {
    int k;
    int c = c_sp();
    if (c_tok('(')) {
        k = climb(1);
        need(')');
        return k;
    }
    if (c_digit() || c == '.') return constant();
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
    c_fail(1);
    return 1;
}

int relop(int m) {      /* the VM's compare of n_cmp's -1, 0 or 1 with 0: -1 when true */
    if (m == 1) return c_op1(70 /* PO_ISLT */);
    if (m == 2) return c_op1(64 /* PO_ISEQ */);
    if (m == 3) { c_op1(68 /* PO_ISGT */); return c_op1(146 /* PO_COMP */); }   /* no ISLE/ISGE: */
    if (m == 4) return c_op1(68 /* PO_ISGT */);
    if (m == 5) return c_op1(66 /* PO_ISNE */);
    c_op1(70 /* PO_ISLT */);    /* the other compare, then COMP */
    return c_op1(146 /* PO_COMP */);
}

int operand() {         /* a primary, or - + NOT and theirs. Each ( and unary op nests through
                           here (climb counts the frames: see there) */
    int k = 1;
    int c = c_sp();
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

int cmpops(int c) {     /* the relation's characters from si: < = > as bits 1, 2, 4 */
    int m = 0;
    int b;
    while (1) {
        b = 0;
        if (c == '<') b = 1;
        if (c == '=') b = 2;
        if (c == '>') b = 4;
        if (!b) break;
        if (m & b) c_fail(1);
        m = m | b;
        si = si + 1;
        c = c_sp();
    }
    if (m == 7) c_fail(1);
    return m;
}

int climb(int min) {    /* the operators of precedence min and up, each left to right (as MS:
                           2^3^2 is 64). Returns the result's kind: 1 a number, 2 an int.
                           Relations (= < > <= >= <>, and =< => >< as MS) give -1 or 0; the
                           exponent of ^ is a whole number, which may be negative */
    int k = 1;
    int c;
    int p;
    deep = deep + 2;    /* every nesting goes through here, a chain of up to 6 per level: its frames
                           (and operand's and primary's under it) are all the frame stack holds */
    if (deep + nif > 24) c_fail(11);
    else k = operand();
    while (!err) {
        c = c_sp();
        p = binop(c);
        if (p < min) break;         /* none is 0 */
        if (p == 6) {
            p = cmpops(c);   /* the relation's bits: p is not needed again here */
            tonum(k);
            tonum(climb(7));
            c_xop(218 /* x CMP */);
            npush(-2);
            epush(1);
            c_op1(0 /* PO_CN 0 */);
            epush(1);
            relop(p);
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
    deep = deep - 2;
    return k;
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
        c_fail(1);
        return 0;
    }
    a = var();
    i = vint;
    if (!need('=')) return 0;
    return assign(a, i, climb(1));
}

int prints() {          /* PRINT: strings and numbers; ; between them, or after the last for no
                           newline; , to the next column of 10 */
    int nl = 1;
    int i;
    int n;
    int c;
    while (!err) {
        c = c_sp();
        if (c == 0 || c == ':') break;
        nl = 0;
        if (c_tok(';')) continue;
        if (c_tok(',')) {
            ecall(&rt_tab);
            continue;
        }
        nl = 1;
        if (!c_tok('"')) {
            tonum(climb(1));
            ecall(&rt_prn);
            npush(-1);
            continue;
        }
        i = si;
        while (src[si] && src[si] != '"') si = si + 1;
        n = si - i;
        c_tok('"');                 /* an unclosed string ends at the end of the line, as MS */
        if (n) {
            c_room(2);
            c_emit(46 /* PO_CS */);
            c_emit(n);
            for (c = 0; c < n; c = c + 1) c_emit(src[i + c]);
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
            c_fail(2);
            return 0;
        }
        fx[nfix] = cend;
        fx[32 + nfix] = t;
        fx[64 + nfix] = cur;
        nfix = nfix + 1;
        c_emit(0);
        return c_emit(0);
    }
    p = find(t);
    if (p == ptop || lineno(p) != t || (cur == -1 && !pend)) {
        c_fail(10);
        return 0;
    }
    p = addr(getw(mem + p + 3));
    c_emit(p);
    return c_emit(p >> 8);
}

int gotol() {
    c_sp();
    if (!c_digit()) {
        c_fail(1);
        return 0;
    }
    return jump(number());
}

int ifs_() {            /* IF e THEN n | statements, IF e GOTO n: false goes to the next line */
    int k = climb(1);
    if (k == 1) {
        c_xop(230 /* x TST */);
        npush(-1);
        epush(1);
    }
    if (nif == 8) {
        c_fail(11);
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
        c_fail(1);
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
        c_fail(1);
        return 0;
    }
    a = var();
    if (vint) c_fail(1);  /* as MS: the variable is a number */
    if (!need('=')) return 0;
    assign(a, 0, climb(1));
    if (!need(153 /* tk TO */)) return 0;
    tonum(climb(1));
    c_sp();
    if (c_tok(149 /* tk STEP */)) tonum(climb(1));
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
            if (vint) c_fail(1);
        }
        c_opw(44 /* PO_CW */, a);
        pcall(&rt_next);
        c_ncall(&rt_go);
        c_sp();
        if (!c_tok(',')) return 0;
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
        if (need(153 /* tk TO */)) return gotol();
        return 0;
    }
    if (c_tok(146 /* tk RETURN */)) {
        pcall(&rt_return);
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
    c_fail(1);
    return 0;
}

int stmts() {           /* the statements of src from si, : between them */
    while (!err) {
        if (!c_sp()) return 0;
        if (c_tok(':')) continue;
        stmt();
        if (err) return 0;
        if (c_sp() && !c_tok(':')) c_fail(1);
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
        if (fx[32 + i] == n) putw(mem + fx[i], addr(cend));
        else if (c_ult(fx[32 + i], n)) {
            c_fail(10);
            eline = fx[64 + i];
            return 0;
        } else {
            i = i + 1;
            continue;
        }
        nfix = nfix - 1;
        fx[i] = fx[nfix];
        fx[32 + i] = fx[32 + nfix];
        fx[64 + i] = fx[64 + nfix];
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
        c_fail(10);
        eline = fx[64];
    }
    if (!err) pend = cend;
    return 0;
}

/* ---- commands ---- */

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

int ended() {           /* nothing after a command but spaces, and no error so far: else reported */
    if (c_sp()) c_fail(1);
    if (!err) return 1;
    report(err, -1);
    return 0;
}

int body() {            /* an immediate line's code, from cend: its statements, and the end of the run */
    cur = -1;
    nd = 0;
    ed = 0;
    nif = 0;
    prologue();
    c_xop(206 /* x LN */);
    stmts();
    endline();
    return finish();
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
    body();
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
        if (c_tok('-')) {
            c_sp();
            b = -1;
            if (c_digit()) b = number();
        }
        if (!ended()) return 0;
        return list(a, b);
    }
    if (c_tok(140 /* tk NEW */)) {
        if (!ended()) return 0;
        ptop = 0;
        return clearv();
    }
    if (c_tok(147 /* tk RUN */)) {
        c_sp();
        if (c_digit()) {
            a = number();
            b = 1;
        }
        if (!ended()) return 0;
        return run(a, b == 1);
    }
    if (c_tok(130 /* tk BYE */) || c_tok(151 /* tk SYSTEM */)) {
        if (!ended()) return 0;
        exit(0);
    }
    at = immediate();
    if (err == 2 && pend) {     /* no room after the program: drop its code, as RUN recompiles */
        err = 0;
        pend = 0;
        cend = ptop;
        si = 0;
        at = ptop;
        body();
    }
    if (err) return report(err, -1);
    return go(at);
}

int main() {
    int tty = isatty(0);
    fx = inul + ((ctl + 1 - nul) >> 1);   /* ctl, or its next byte if the address is odd: a word view */
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
    return 0;
}
