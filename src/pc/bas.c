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
   against src/pvm/pvm.inc.

   SIZE (2026-11-24): bas is 9,209 B with BSS, 36 pages, 7 B under the boundary. Any addition must
   be paid for first, with aggressive and unconventional squish (docs/design/basic.md, the
   optimization notes); do not just add code. */

/* xops */
#include "inc/rt.c"
/* fstack 416 */   /* the VM frame stack: a measured size (tools/test_bas.py, the nesting sweep), with the nesting limit in climb */

extern int c_const(char *buf);
extern int c_err();
extern int c_curip();
extern int c_crunch(char *buf, char *kwt);
extern int c_find(char *mem, int top, int n);
extern int c_sp(); /* xop 232 */      /* bas-rt.s: the scanner and the code emitter, on these globals */
extern int c_digit(); /* xop 242 */
extern int c_letter();
extern int c_tok(int t); /* xop 234 */
extern int c_ult(int a, int b);
extern int c_emit(int b); /* xop 236 void */
extern int c_room(int n); /* xop 248 void */
extern int c_op1(int b); /* xop 238 void */
extern int c_opw(int b, int w); /* xop 250 void */
extern int c_ncall(char *f); /* xop 244 void */
extern int c_xop(int b); /* xop 254 void */
extern int c_xopw(int b, int w); /* void */
extern int c_fail(int e); /* xop 252 void */   /* err = e, unless one came first */
extern int c_grow(int n);       /* up to n pages from the kernel for mem (bas-rt.s); the pages granted */

char *mem;              /* MEM: the arena, msz bytes of pages the kernel grants at start (c_grow) */
int msz;
int ptop;               /* the program text: [0, ptop); per line its number (low, high), length,
                           the offset of its code (low, high), then the text */
int pend;               /* the program's code: [ptop, pend); 0 when out of date */
int cend;               /* the end of the code */
int vbot;               /* the variables: [vbot, MEM) */
int clim;               /* where the code must stop: vbot, or the string heap once there is one */
int straight;           /* bytes since the VM last reset Y: pvm.s addresses code as base + Y */
int eline;              /* the line a compile error is in */
char kwt[] = "ABS|AND|BYE|END|FOR|GOSUB|GOTO|GO|IF|INT|LET|LIST|NEW|NEXT|NOT|OR|PRINT|REM|RETURN|RUN|SGN|STEP|STOP|SYSTEM|THEN|TO|BUILD|LEFT$|RIGHT$|MID$|LEN|CHR$|ASC|STR$|VAL|INPUT|DIM|";
                        /* the keywords: the program holds each as a token, 128 + its place
                           here, written as the number with "tk NAME" in a comment (test_bas checks the
                           numbers; bas-rt.s has PRINT's and REM's); a keyword before its prefixes, as
                           the first that matches wins (so TOTAL is TO TAL, as MS) */
char *src;
int si;                 /* the parse position in src */
int cur;                /* the line being compiled; -1 in immediate mode */
int nd;                 /* the compiled code's depth on the number stack */
int ed;                 /* and on the eval stack */
int vint;               /* the last variable parsed is an integer (A%) */
int ifh;                /* this line's IFs: where the newest one's JUMP address goes; each holds the
                           place of the one before (a chain through the code), nif of them */
int nif;
int *inul;              /* 0, for fx */
int *fx;                /* forward GOTOs, in ctl while compiling (a run starts with it empty): where
                           the address goes (fx[0-31]), the target (fx[32-63]), the line (fx[64-95]) */
int nfix;

/* ---- output ---- */

/* ---- input ---- */

int getline() {         /* the next line of stdin into ib: its length, -1 at the end, -2 too long */
    il = 0;
    iov = 0;
    if (!iread()) return -1;
    if (iov) return -2;
    return il;
}

int normal() {          /* ib in place (c_crunch): keywords to tokens and the rest upper case,
                           outside quotes; tabs to spaces and runs of them to one, none leading
                           or trailing (but inside an unclosed string); a REM's text as typed.
                           Returns the length, or -1 for a byte above 127 outside quotes */
    return c_crunch(ib, kwt);
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

int addr(int i) {       /* mem[i] as an address */
    return mem - nul + i;
}

/* ---- the line store ----
   mem from 0 to ptop holds the lines in order, each: its number (2 bytes), the length of its
   text, the offset of its code (2 bytes, set when it is compiled), the text, a 0. The compiled
   code follows from ptop to pend (0 when out of date), then free space, then the variables
   from vbot to the top. */

int mw(int p) {          /* the word at mem[p]: a line's number, an array's dimension */
    return getw(mem + p);
}

int next(int p) {
    return p + 6 + mem[p + 2];
}

int find(int n) {       /* the first line numbered n or above */
    return c_find(mem, ptop, n);
}

int move(char *d, char *s, int n) {
    if (d - s > 0) {
        while (n > 0) {
            n = n - 1;
            d[n] = s[n];
        }
    } else {
        c_mcpy(d - nul, s - nul, n);
    }
    return 0;
}

int clearv() {          /* no variables or strings, and the compiled program is out of date */
    vbot = msz;
    clim = msz;
    hhi = addr(msz);
    hlo = 0;
    pend = 0;
    return 0;
}

int heapinit() {        /* the string heap, once the program's code is final: after the room an immediate
                           line's code needs (tools/test_bas.py pins the longest line under it) */
    int b = ptop;
    if (pend) b = pend;
    b = b + 768;
    if (b > vbot) b = vbot;
    hlo = addr(b);
    htop = hlo;
    clim = b;
    return 0;
}

int store(int n, int t, int len) {  /* line n is ib from t, len bytes; none deletes it */
    int p = find(n);
    int old = 0;
    int add = 0;
    if (p < ptop && mw(p) == n) old = next(p) - p;
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
        move(mem + p + 5, ib + t, len);
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
    while (p < ptop) {
        n = mw(p);
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
    c_room(2);
    c_emit(76 /* PO_BRFLS */);
    c_emit(3);            /* to the body, past the CN 0 and RET */
    return finish();
}

/* ---- the runtime the compiled code calls ---- */

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
    if (k > 2) c_fail(13);
    if (k == 2) {
        c_xop(226 /* x FROMI */);
        epush(-1);
        npush(1);
    }
    return 1;
}

int toint(int k) {
    if (k > 2) c_fail(13);
    if (k == 1) {
        c_xop(228 /* x TOI */);
        npush(-1);
        epush(1);
    }
    return 2;
}

int nc1;                /* the name name() parsed: its two characters, flagged for the type */
int nc2;

int name() {            /* the variable name at si (a letter): two characters count, as MS; vint says its type */
    nc1 = src[si];
    nc2 = 0;
    si = si + 1;
    while (c_letter() || c_digit()) {   /* a keyword is a token: it ends the name */
        if (!nc2) nc2 = src[si];
        si = si + 1;
    }
    vint = 0;
    if (src[si] == '%') {
        si = si + 1;
        vint = 1;
        nc2 = nc2 | 128;
    } else if (src[si] == '$') {
        si = si + 1;
        vint = 2;
        nc1 = nc1 | 128;
        nc2 = nc2 | 128;
    }
    return 0;
}

int vsz(int c2) {      /* the bytes of a value, by the name's second character: a number's 4, an int's or a string's 2 */
    return 4 - (c2 & 128) / 64;
}

int esz(int p) {        /* the size of the table entry at p: a variable's 6 or 4 bytes, or an array's header (name, the
                           counts of its two dimensions: the second 0 for one) and its elements, 4 bytes or 2 */
    int n = 1;
    if (!(mem[p] & 32)) return 2 + vsz(mem[p + 1]);
    if (mw(p + 4)) n = mw(p + 4);
    return 6 + n * mw(p + 2) * vsz(mem[p + 1]);
}

int slot(int c1, int c2) {      /* the table entry named so, or -1 */
    int p = vbot;
    while (p < msz) {
        if (mem[p] == c1 && mem[p + 1] == c2) return p;
        p = p + esz(p);
    }
    return -1;
}

int grab(int size) {    /* a new table entry of size bytes, zeroed, at vbot: its offset (OUT OF MEMORY, 0, if it does not fit) */
    int p = cend;
    if (hlo) p = htop - addr(0);
    if (vbot - size < p) {
        c_fail(2);
        return 0;
    }
    vbot = vbot - size;
    hhi = addr(vbot);
    if (!hlo) clim = vbot;
    mem[vbot] = 0;
    c_mcpy(addr(vbot) + 1, addr(vbot), size - 1);
    return vbot;
}

int var() {             /* the variable at si (a letter): its value's address, made 0 if new;
                           vint says whether it is an integer. An element of an array: its address is
                           pushed instead, and the value returned is 0 (as after an error) */
    int p;
    name();
    if (src[si] == '(') return elem();
    p = slot(nc1, nc2);
    if (p >= 0) return addr(p + 2);
    p = grab(2 + vsz(nc2));
    if (err) return 0;
    mem[p] = nc1;
    mem[p + 1] = nc2;
    return addr(p + 2);
}

int array(int n1, int n2) {     /* the array nc1, nc2 of n1 elements (n2 by n1 for two dimensions, else 0), made if it is
                                   not there: its offset. An explicit DIM that disagrees with it is a REDIM'D ARRAY */
    int p = slot(nc1 | 32, nc2);
    int q;
    if (p >= 0) {
        if (n1 && (mw(p + 2) != n1 || mw(p + 4) != n2)) c_fail(15);
        return p;
    }
    if (!n1) {
        n1 = 11;                /* not DIMed: 0 to 10, as MS */
        if (n2) n2 = 11;
    }
    q = n1;
    if (n2) q = 15360 / n2;
    if (n1 > q || n1 > 15360) {
        c_fail(2);
        return 0;
    }
    q = n1;
    if (n2) q = n1 * n2;
    p = grab(6 + q * vsz(nc2));
    if (err) return 0;
    mem[p] = nc1 | 32;
    mem[p + 1] = nc2;
    putw(mem + p + 2, n1);
    putw(mem + p + 4, n2);
    return p;
}

int more() {            /* does the parenthesis at si hold a comma of its own: a second subscript */
    int i = si;
    int d = 0;
    while (src[i]) {
        if (src[i] == '(') d = d + 1;
        if (src[i] == ')') {
            d = d - 1;
            if (!d) return 0;
        }
        if (src[i] == ',' && d == 1) return 1;
        i = i + 1;
    }
    return 0;
}

int pushi(int v) {      /* pushint, counted on the eval stack */
    pushint(v);
    return epush(1);
}

int iop(int op) {       /* a VM op on the eval stack's top two ints */
    c_op1(op);
    return epush(-1);
}

int isub(int m) {       /* the subscript on top checked for 0 to m */
    pushi(m);
    pcall(&rt_sub);
    return epush(-1);
}

int elem() {            /* A(i) or A(i, j): the element's address on the eval stack, after a check of each subscript */
    int n2 = more();
    int p = array(0, n2);
    int m1;
    int m2;
    int sz = vsz(nc2);      /* the subscripts' own variables change nc2 and vint: keep them */
    int ty = vint;
    if (err) return 0;
    m1 = mw(p + 2);
    m2 = mw(p + 4);
    if (!m2 != !n2) c_fail(14);     /* a different number of subscripts */
    need('(');
    deep = deep + 2;
    c_opw(38 /* PO_LA */, addr(p + 6));
    epush(1);
    toint(climb(1));
    isub(m1 - 1);
    if (m2) {
        need(',');
        pushi(m2);
        iop(134 /* PO_MUL */);
        toint(climb(1));
        isub(m2 - 1);
        iop(130 /* PO_ADD */);
    }
    pushi(sz);
    iop(134 /* PO_MUL */);
    iop(130 /* PO_ADD */);
    need(')');
    deep = deep - 2;
    vint = ty;
    return 0;
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

int strlit() {          /* a string literal after its quote: a CS, whose address is the string; "" is 0 */
    int i = si;
    int n;
    int c;
    while (src[si] && src[si] != '"') si = si + 1;
    n = si - i;
    c_tok('"');                 /* an unclosed string ends at the end of the line, as MS */
    if (n) {
        c_room(2);
        c_emit(46 /* PO_CS */);
        c_emit(n);
        for (c = 0; c < n; c = c + 1) c_emit(src[i + c]);
        straight = n + 1;       /* CS moves the base to the string: the next op is past it */
    } else c_op1(0 /* PO_CN 0 */);
    return epush(1) + 1;
}

int val() {             /* VAL of the string on the eval stack, to the number stack */
    ecall(&rt_val);
    epush(-1);
    return npush(1);
}

int sfn(int t) {        /* a string function, after its keyword (token 155 LEFT$, 156 RIGHT$, 157 MID$, 158 LEN,
                           159 CHR$, 160 ASC, 161 STR$, 162 VAL): its kind */
    int k = 3;
    need('(');
    deep = deep + 2;
    if (t == 161) {
        tonum(climb(1));
        pcall(&rt_str);
        npush(-1);
        epush(1);
    } else if (t == 159) {
        toint(climb(1));
        pcall(&rt_chr);
    } else {
        if (climb(1) != 3) c_fail(13);
        if (t == 158) {
            pcall(&rt_len);
            k = 2;
        } else if (t == 160) {
            pcall(&rt_asc);
            k = 2;
        } else if (t == 162) k = val(); else {
            need(',');
            toint(climb(1));
            if (t == 157) {
                if (c_sp() == ',') {
                    need(',');
                    toint(climb(1));
                } else pushint(255);
                pcall(&rt_mid);
                epush(-1);
            } else if (t == 155) pcall(&rt_left);
            else pcall(&rt_right);
            epush(-1);
        }
    }
    need(')');
    deep = deep - 2;
    return k;
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
    if (c_tok('"')) return strlit();
    if (c > 154 && c < 163 && c_tok(c)) return sfn(c);
    if (c_letter()) {
        k = var();
        if (!k) {                       /* an element: its address is on the stack, load by the type */
            if (vint) {
                c_op1(98 /* PO_LW */);
                return vint + 1;
            }
            c_xop(240 /* c_ldv */);
            epush(-1);
            return npush(1);
        }
        if (vint) {
            c_opw(106 /* PO_LAW */, k);
            epush(1);
            return vint + 1;
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
            if (k == 3) {
                if (climb(7) != 3) c_fail(13);
                pcall(&rt_scmp);
                epush(-1);
            } else {
                tonum(k);
                tonum(climb(7));
                c_xop(218 /* x CMP */);
                npush(-2);
                epush(1);
            }
            pushi(0);
            relop(p);
            k = epush(-1);
            continue;
        }
        si = si + 1;
        if (p <= 4) {
            toint(k);
            toint(climb(p + 1));
            if (p == 4) k = iop(148 /* PO_BAND */);
            else k = iop(150 /* PO_IOR */);
            continue;
        }
        if (k == 3) {           /* a string: + joins */
            if (c != '+' || climb(p + 1) != 3) c_fail(13);
            pcall(&rt_scat);
            epush(-1);
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

int assign(int a, int t, int k) {       /* the value of kind k to the variable of type t at a (var's), or for
                                           a = 0 to the array element whose address is under the value */
    if (t == 2) {               /* the address of the variable was pushed before the expression */
        if (k != 3) c_fail(13);
        ecall(&rt_sset);
        return epush(-2);
    }
    if (t) {
        toint(k);
        if (a) {
            c_opw(122 /* PO_SAW */, a);
            return epush(-1);
        }
        ecall(&rt_sw);
        return epush(-2);
    }
    tonum(k);
    if (a) {
        c_xopw(202 /* x STV */, a);
        return npush(-1);
    }
    c_xop(246 /* c_stv */);
    npush(-1);
    return epush(-1);
}

int sla(int a, int t) {        /* a string variable's address, for rt_sset: an element's is pushed already */
    if (t == 2 && a) {
        c_opw(38 /* PO_LA */, a);
        epush(1);
    }
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
    sla(a, i);
    return assign(a, i, climb(1));
}

int prints() {          /* PRINT: strings and numbers; ; between them, or after the last for no
                           newline; , to the next column of 10 */
    int nl = 1;
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
        c = climb(1);
        if (c == 3) {
            ecall(&rt_prs);
            epush(-1);
        } else {
            tonum(c);
            ecall(&rt_prn);
            npush(-1);
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
    if (p == ptop || mw(p) != t || (cur == -1 && !pend)) {
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
    if (k > 2) c_fail(13);
    if (k == 1) {
        c_xop(230 /* x TST */);
        npush(-1);
        epush(1);
    }
    c_room(5);            /* false: over a JUMP to the line's end (a branch reaches 127 bytes, a line may not) */
    c_emit(78 /* PO_BRTRU */);
    c_emit(4);
    c_emit(196 /* PO_JUMP */);
    straight = 0;
    nif = nif + 1;
    c_emit(ifh);
    c_emit(ifh >> 8);
    ifh = cend - 2;
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
    if (vint || !a) c_fail(1);  /* as MS: the variable is a number */
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
    c_opw(38 /* PO_LA */, addr(cend + 10));
    c_opw(38 /* PO_LA */, a);
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
            if (vint || !a) c_fail(1);
        }
        c_opw(38 /* PO_LA */, a);
        pcall(&rt_next);
        c_ncall(&rt_go);
        c_sp();
        if (!c_tok(',')) return 0;
    }
    return 0;
}

int sres() {            /* before a statement with strings in it, room for the temporaries it can make: one for
                           each $, string function and +, to 6 (rt_sres). A GC moves blocks, so it runs only
                           here, where nothing is on the stacks */
    int i = si;
    int q = 0;
    int s = 0;
    int n = 0;
    int c;
    while (src[i] && (src[i] != ':' || q)) {
        c = src[i];
        if (c == '"') q = 1 - q;
        if (!q) {
            if (c == '$' || c > 154) s = s + 1;
            if (c == '+') n = n + 1;
        }
        i = i + 1;
    }
    if (!s || src[si] == 145 /* tk REM */ || src[si] == 164 /* tk DIM */) return 0;
    n = n + s;
    if (n > 6) n = 6;
    pushint(n);
    return ecall(&rt_sres);
}

int inputs() {          /* INPUT ["prompt";] v [, v ...]: rt_inp reads and checks the line (the kinds go to it as a
                           mask, found by a look ahead), then each variable takes its field (rt_ifld) */
    int m = 0;
    int n = 0;
    int i;
    int p = 0;
    int c;
    int a;
    int k;
    int t;
    int d = 0;
    if (c_sp() == '"') {
        c_tok('"');
        strlit();
        need(';');
    } else {
        pushi(0);
    }
    c_sp();
    i = si;
    while (!err) {
        c = src[i];
        if (c == '(') d = d + 1;
        if (c == ')') d = d - 1;
        if (c == 0 || c == ':' || (c == ',' && !d)) {
            if (p != '$') m = m + (1 << n);
            n = n + 1;
            p = 0;
            if (c != ',') break;
        } else if (c != ' ' && !d && c != ')') p = c;
        i = i + 1;
    }
    if (n > 7) c_fail(11);
    pushi(n * 128 + m);
    ecall(&rt_inp);
    epush(-2);
    for (k = 0; k < n && !err; k = k + 1) {
        if (k) need(',');
        if (!c_sp() || !c_letter()) {
            c_fail(1);
            return 0;
        }
        a = var();
        t = vint;
        sla(a, t);
        pcall(&rt_ifld);
        epush(1);
        c = 3;
        if (t != 2) c = val();
        assign(a, t, c);
    }
    return 0;
}

int dims() {            /* DIM v(n [, m]) [, ...]: the sizes are numbers, and the arrays are made here, as the program is
                           compiled (MS makes one when its DIM runs: predim has found them all first) */
    int n1;
    int n2;
    while (!err) {
        c_sp();
        if (!c_letter()) {
            c_fail(1);
            return 0;
        }
        name();
        if (!need('(')) return 0;
        c_sp();
        n1 = number();
        n2 = 0;
        if (n1 < 0 || n1 > 15359) c_fail(2);
        if (c_sp() == ',') {
            c_tok(',');
            c_sp();
            n2 = number() + 1;
            if (n2 < 1 || n2 > 15360) c_fail(2);
        }
        if (!need(')') || err) return 0;
        array(n1 + 1, n2);
        if (c_sp() != ',') return 0;
        c_tok(',');
    }
    return 0;
}

int predim() {          /* every DIM of the program, before a line is compiled: a subroutine at the end may DIM what the lines
                           before it use */
    int p = 0;
    int q;
    int c;
    while (p < ptop && !err) {
        src = mem + p + 5;
        si = 0;
        q = 0;
        c = src[0];
        while (c && c != 145 /* tk REM */ && !err) {
            if (c == '"') q = 1 - q;
            si = si + 1;
            if (c == 164 /* tk DIM */ && !q) {
                nd = 0;
                ed = 0;
                dims();
                if (err) eline = mw(p);
            }
            c = src[si];
        }
        p = next(p);
    }
    return 0;
}

int stmt() {
    c_sp();
    sres();
    if (c_tok(144 /* tk PRINT */)) return prints();
    if (c_tok(145 /* tk REM */)) {
        while (src[si]) si = si + 1;
        return 0;
    }
    if (c_tok(163 /* tk INPUT */)) return inputs();
    if (c_tok(164 /* tk DIM */)) return dims();
    if (c_tok(138 /* tk LET */)) return let();
    if (c_tok(136 /* tk IF */)) return ifs_();
    if (c_tok(133 /* tk GOSUB */)) {
        c_room(6);        /* the return address is 10 bytes on */
        c_opw(38 /* PO_LA */, addr(cend + 10));
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
    for (; nif && !err; nif = nif - 1) {   /* an error may have left the newest link unwritten */
        char *p;
        p = mem + ifh;
        ifh = getw(p);
        putw(p, addr(cend));
    }
    return 0;
}

int cline(int p) {      /* compile the line at p */
    int n = mw(p);
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
    predim();
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

/* ---- the compiled file (BUILD; docs/design/basic.md 6.1, option B) ----
   The code in the arena holds addresses. A file holds none: the walk below turns each word
   operand into an offset, by what the opcode says it is: a place in the code (LA of a return
   or loop address, JUMP: the offset from the code's start), a variable (LAW SAW LDV STV, an LA
   of a variable: the offset from the variables' start, with bit 15 set), or the runtime (CALL
   and NCAL: the offset from the first routine of its kind). The runner turns them back, so it need not share bas's layout. */

int build() {           /* BUILD: the program as a file on the output: "BX", 1, rtid, the code's length, the
                           variables' size, the code, then the line table: per line the offset of its code
                           and its number. The code in the arena is spent */
    int p;
    int w;
    clearv();
    compile();
    if (err) return report(err, eline);
    reloc(addr(ptop), pend - ptop, addr(vbot), 1);
    ib[0] = 'B';
    ib[1] = 'X';
    ib[2] = 1;
    putw(ib + 3, rtid());
    putw(ib + 5, pend - ptop);
    putw(ib + 7, msz - vbot);
    w = write(1, ib, 9) != 9;
    w = w | (write(1, mem + ptop, pend - ptop) != pend - ptop);
    for (p = 0; p < ptop; p = next(p)) {
        putw(ib, getw(mem + p + 3) - ptop);
        putw(ib + 2, mw(p));
        w = w | (write(1, ib, 4) != 4);
    }
    if (w) {
        write(2, "bas: write failed\n", 18);
        exit(1);
    }
    pend = 0;
    return 0;
}

/* ---- commands ---- */

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
        for (p = 0; p < ptop; p = next(p)) if (getw(mem + p + 3) < a) ln = mw(p);
    return report(e, ln);
}

int run(int t, int has) {       /* RUN [t] */
    clearv();
    compile();
    if (err) return report(err, eline);
    heapinit();
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
        src = ib;     /* compile() read the program's lines */
        si = 0;
    }
    cend = pend;
    if (!cend) cend = ptop;
    if (!hlo) heapinit();
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
    if (c_tok(154 /* tk BUILD */)) {
        if (!ended()) return 0;
        return build();
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
        if (n == -2) report(3, -1);
        else {
            n = normal();
            if (n == 0) continue;
            src = ib;
            si = 0;
            if (n == -1) report(1, -1);
            else if (c_digit()) {  /* a numbered line: store it (no READY, as MS) */
                t = number();
                if (!err) store(t, si, n - si);
                if (!err) continue;
                report(err, -1);
            } else command();
        }
        if (tty) {
            fresh();
            outs("READY.\n");
        }
    }
    return 0;
}
