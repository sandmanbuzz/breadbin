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
extern int incsi(); /* void */   /* si + 1 */
extern int c_sres();
extern int c_more();
extern int c_binop(int c);
extern int c_relop(int m); /* void */
extern int c_vars();
extern int c_ch();   /* src[si] */
extern int deeper(); /* void */   /* deep + 2 */
extern int shallower(); /* void */   /* deep - 2 */
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
char kwt[] = "ABS|AND|BYE|END|FOR|GOSUB|GOTO|GO|IF|INT|LET|LIST|NEW|NEXT|NOT|OR|PRINT|REM|RETURN|RUN|SGN|STEP|STOP|SYSTEM|THEN|TO|BUILD|LEFT$|RIGHT$|MID$|LEN|CHR$|ASC|STR$|VAL|INPUT|DIM|SAVE|LOAD|";
                        /* the keywords: the program holds each as a token, 128 + its place
                           here, written as the number with "tk NAME" in a comment (test_bas checks the
                           numbers; bas-rt.s has PRINT's, REM's and DIM's); a keyword before its prefixes, as
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
int nfix;               /* forward GOTOs, in ctl while compiling (a run starts with it empty): 6 bytes
                           each, where the address goes, the target and the line, nfix of them to 32 */

/* ---- output ---- */

/* ---- parsing: c_sp, c_digit, c_letter and c_tok (bas-rt.s) read src[si] ---- */

int scan(char *s) {      /* parse s from its start */
    src = s;
    si = 0;
    return 0;
}
int number() {          /* a line number at si (0 to 63999, unsigned), spaces among its digits
                           and after it skipped, as MS; none or too big is a syntax error */
    int n = 0;
    if (!c_digit()) c_fail(1);
    while (c_digit()) {
        if (n > 6399) c_fail(1);
        n = n * 10 + c_ch() - '0';
        incsi();
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
    char *q = mem + p;
    if (p < ptop && mw(p) == n) old = next(p) - p;
    if (len) add = len + 6;
    if (ptop - old + add > msz) {
        c_fail(2);
        return 0;
    }
    move(q + add, q + old, ptop - p - old);
    ptop = ptop - old + add;
    if (len) {
        putw(q, n);
        q[2] = len;
        move(q + 5, ib + t, len);
        q[5 + len] = 0;         /* the compiler reads the text in place */
    }
    clearv();    /* as MS: an edit clears the variables */
    return 0;
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

int pcall(char *f, int d) {     /* CALL f, a bytecode function, which changes the eval stack's depth by d
                                   (c_ncall is for the natives) */
    c_opw(84 /* PO_CALL */, f - nul);
    straight = 0;
    epush(d);
    return 0;
}

int ecall(char *f, int d) {     /* pcall, then DROP its result */
    pcall(f, d);
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
    finish();
    return 0;
}

/* ---- the runtime the compiled code calls ---- */

/* ---- expressions: a kind, 1 for a number (on the number stack), 2 for an int (eval) ---- */

int npush(int d) {
    nd = nd + d;
    if (nd > 14) c_fail(11);      /* bas-rt.s holds 16; rt_pow and rt_next use 2 */
    return 0;
}

int epush(int d) {
    ed = ed + d;
    if (ed > 6) c_fail(11);
    return 0;
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
    nc1 = c_ch();
    nc2 = 0;
    incsi();
    while (c_letter() || c_digit()) {   /* a keyword is a token: it ends the name */
        if (!nc2) nc2 = c_ch();
        incsi();
    }
    vint = 0;
    if (c_tok('$')) {
        vint = 2;
        nc1 = nc1 | 128;
    } else if (c_tok('%')) vint = 1;
    if (vint) nc2 = nc2 | 128;
    return 0;
}

int vsz(int c2) {      /* the bytes of a value, by the name's second character: a number's 4, an int's or a string's 2 */
    return 4 - (c2 & 128) / 64;
}

int esz(int p) {        /* the size of the table entry at p: a variable's 6 or 4 bytes, or an array's header (name, the
                           counts of its two dimensions: the second 0 for one) and its elements, 4 bytes or 2 */
    int z = vsz(mem[p + 1]);
    int n;
    if (!(mem[p] & 32)) return 2 + z;
    n = mw(p + 4);
    if (!n) n = 1;
    return 6 + n * mw(p + 2) * z;
}

int slot(int c1, int c2) {      /* the table entry named so, or -1 */
    int p = vbot;
    c1 = c1 + (c2 << 8);        /* the name as a word */
    while (p < msz) {
        if (mw(p) == c1) return p;
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
    p = addr(vbot);
    hhi = p;
    if (!hlo) clim = vbot;
    mem[vbot] = 0;
    c_mcpy(p + 1, p, size - 1);
    return vbot;
}

int var() {             /* the variable at si (a letter): its value's address, made 0 if new;
                           vint says whether it is an integer. An element of an array: its address is
                           pushed instead, and the value returned is 0 (as after an error) */
    int p;
    name();
    if (c_ch() == '(') return elem();
    p = slot(nc1, nc2);
    if (p >= 0) return addr(p + 2);
    p = grab(2 + vsz(nc2));
    if (err) return 0;
    putw(mem + p, nc1 + (nc2 << 8));
    return addr(p + 2);
}

int array(int n1, int n2) {     /* the array nc1, nc2 of n1 elements (n2 by n1 for two dimensions, else 0), made if it is
                                   not there: its offset. An explicit DIM that disagrees with it is a REDIM'D ARRAY */
    int p = slot(nc1 | 32, nc2);
    int q;
    char *e;
    if (p >= 0) {
        if (n1 && (mw(p + 2) != n1 || mw(p + 4) != n2)) c_fail(15);
        return p;
    }
    if (!n1) {
        n1 = 11;                /* not DIMed: 0 to 10, as MS */
        if (n2) n2 = 11;
    }
    q = 30720 / vsz(nc2);       /* elements that fit in 30,720 bytes: the size stays a positive int */
    if (n2) q = q / n2;
    if (n1 > q) {
        c_fail(2);
        return 0;
    }
    q = n1;
    if (n2) q = n1 * n2;
    p = grab(6 + q * vsz(nc2));
    if (err) return 0;
    e = mem + p;
    e[0] = nc1 | 32;
    e[1] = nc2;
    putw(e + 2, n1);
    putw(e + 4, n2);
    return p;
}


int pushi(int v) {      /* pushint, counted on the eval stack */
    pushint(v);
    epush(1);
    return 0;
}

int iop(int op) {       /* a VM op on the eval stack's top two ints */
    c_op1(op);
    epush(-1);
    return 0;
}

int isub(int m) {       /* the subscript on top checked for 0 to m */
    pushi(m);
    pcall(&rt_sub, -1);
    return 0;
}

int elem() {            /* A(i) or A(i, j): the element's address on the eval stack, after a check of each subscript */
    int n2 = c_more();
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
    deeper();
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
    shallower();
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
    } else {
        c_room(5);
        c_emit(204 /* x LDK */);
        for (i = 0; i < 4; i = i + 1) c_emit(pb[i]);
        straight = 0;   /* the VM renormalises IP past the operand */
    }
    npush(1);
    return 1;
}

int deep;
int fn(int f) {       /* a function of one number: f(...) */
    if (c_sp() != '(') {
        c_fail(1);
        return 1;
    }
    deeper();       /* fn and primary's frames, over the climb the '(' enters */
    tonum(primary());
    shallower();
    c_xop(f);
    return 1;
}

int strlit() {          /* a string literal after its quote: a CS, whose address is the string; "" is 0 */
    int i = si;
    int n;
    int c;
    while (c_ch() && c_ch() != '"') incsi();
    n = si - i;
    c_tok('"');                 /* an unclosed string ends at the end of the line, as MS */
    if (n) {
        c_room(2);
        c_emit(46 /* PO_CS */);
        c_emit(n);
        for (c = 0; c < n; c = c + 1) c_emit(src[i + c]);
        straight = n + 1;       /* CS moves the base to the string: the next op is past it */
    } else c_op1(0 /* PO_CN 0 */);
    epush(1);
    return 0;
}

int val() {             /* VAL of the string on the eval stack, to the number stack */
    ecall(&rt_val, -1);
    npush(1);
    return 1;
}

int sfn(int t) {        /* a string function, after its keyword (token 155 LEFT$, 156 RIGHT$, 157 MID$, 158 LEN,
                           159 CHR$, 160 ASC, 161 STR$, 162 VAL): its kind */
    int k = 3;
    need('(');
    deeper();
    if (t == 161) {
        tonum(climb(1));
        pcall(&rt_str, 1);
        npush(-1);
    } else if (t == 159) {
        toint(climb(1));
        pcall(&rt_chr, 0);
    } else {
        if (climb(1) != 3) c_fail(13);
        if (t == 158) {
            pcall(&rt_len, 0);
            k = 2;
        } else if (t == 160) {
            pcall(&rt_asc, 0);
            k = 2;
        } else if (t == 162) k = val(); else {
            need(',');
            toint(climb(1));
            if (t == 157) {
                c_sp();
                if (c_tok(',')) {
                    toint(climb(1));
                } else pushint(255);
                pcall(&rt_mid, -2);
            } else if (t == 155) pcall(&rt_left, -1);
            else pcall(&rt_right, -1);
        }
    }
    need(')');
    shallower();
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
    if (c_tok('"')) {
        strlit();
        return 3;
    }
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
            npush(1);
            return 1;
        }
        if (vint) {
            c_opw(106 /* PO_LAW */, k);
            epush(1);
            return vint + 1;
        }
        c_xopw(200 /* x LDV */, k);
        npush(1);
        return 1;
    }
    c_fail(1);
    return 1;
}


int operand() {         /* a primary, or - + NOT and theirs. Each ( and unary op nests through
                           here (climb counts the frames: see there) */
    int k = 1;
    c_sp();
    if (c_tok('-')) {       /* binds looser than ^, as MS: -2^2 is -4 */
        tonum(climb(10));
        c_xop(216 /* x NEG */);
    } else if (c_tok('+')) k = climb(10);
    else if (c_tok(142 /* tk NOT */)) {    /* of the relation after it, as MS */
        toint(climb(6));
        c_op1(146 /* PO_COMP */);
        k = 2;
    } else k = primary();
    return k;
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
        incsi();
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
    deeper();    /* every nesting goes through here, a chain of up to 6 per level: its frames
                           (and operand's and primary's under it) are all the frame stack holds */
    if (deep + nif > 24) c_fail(11);
    else k = operand();
    while (!err) {
        c = c_sp();
        p = c_binop(c);
        if (p < min) break;         /* none is 0 */
        if (p == 6) {
            p = cmpops(c);   /* the relation's bits: p is not needed again here */
            if (k == 3) {
                if (climb(7) != 3) c_fail(13);
                pcall(&rt_scmp, -1);
            } else {
                tonum(k);
                tonum(climb(7));
                c_xop(218 /* x CMP */);
                npush(-2);
                epush(1);
            }
            pushi(0);
            c_relop(p);
            epush(-1);
            k = 2;
            continue;
        }
        incsi();
        if (p <= 4) {
            toint(k);
            toint(climb(p + 1));
            if (p == 4) iop(148 /* PO_BAND */);
            else iop(150 /* PO_IOR */);
            k = 2;
            continue;
        }
        if (k == 3) {           /* a string: + joins */
            if (c != '+' || climb(p + 1) != 3) c_fail(13);
            pcall(&rt_scat, -1);
            continue;
        }
        tonum(k);
        tonum(climb(p + 1));
        if (c == '^') ecall(&rt_pow, 0);
        else if (c == '*') c_xop(212 /* x MUL */);
        else if (c == '/') c_xop(214 /* x DIV */);
        else if (c == '+') c_xop(208 /* x ADD */);
        else c_xop(210 /* x SUB */);
        npush(-1);
        k = 1;
    }
    shallower();
    return k;
}

/* ---- statements ---- */

int assign(int a, int t, int k) {       /* the value of kind k to the variable of type t at a (var's), or for
                                           a = 0 to the array element whose address is under the value */
    if (t == 2) {               /* the address of the variable was pushed before the expression */
        if (k != 3) c_fail(13);
        ecall(&rt_sset, -2);
        return 0;
    }
    if (t) {
        toint(k);
        if (a) {
            c_opw(122 /* PO_SAW */, a);
            epush(-1);
            return 0;
        }
        ecall(&rt_sw, -2);
        return 0;
    }
    tonum(k);
    if (a) {
        c_xopw(202 /* x STV */, a);
        npush(-1);
        return 0;
    }
    c_xop(246 /* c_stv */);
    npush(-1);
    epush(-1);
    return 0;
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
    assign(a, i, climb(1));
    return 0;
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
            ecall(&rt_tab, 0);
            continue;
        }
        nl = 1;
        c = climb(1);
        if (c == 3) {
            ecall(&rt_prs, -1);
        } else {
            tonum(c);
            ecall(&rt_prn, 0);
            npush(-1);
        }
    }
    if (nl) ecall(&rt_nl, 0);
    return 0;
}

int jump(int t) {       /* JUMP to line t: a line not compiled yet is fixed up when it is */
    int p;
    char *q;
    c_room(3);
    c_emit(196 /* PO_JUMP */);
    straight = 0;
    if (cur != -1 && c_ult(cur, t)) {
        if (nfix == 32) {
            c_fail(2);
            return 0;
        }
        q = ctl + nfix * 6;
        putw(q, cend);
        putw(q + 2, t);
        putw(q + 4, cur);
        nfix = nfix + 1;
        c_emit(0);
        return c_emit(0);
    }
    p = find(t);
    if (p == ptop || mw(p) != t || (cur == -1 && !pend)) {
        c_fail(10);
        return 0;
    }
    p = addr(mw(p + 3));
    c_emit(p);
    return c_emit(p >> 8);
}

int gotol() {
    c_sp();
    if (!c_digit()) {
        c_fail(1);
        return 0;
    }
    jump(number());
    return 0;
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
    if (c_tok(134 /* tk GOTO */)) { gotol(); return 0; }
    if (!c_tok(152 /* tk THEN */)) {
        c_fail(1);
        return 0;
    }
    c_sp();
    if (c_digit()) { gotol(); return 0; }
    stmt();
    return 0;
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
    ecall(&rt_for, 0);
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
        pcall(&rt_next, 0);
        c_ncall(&rt_go);
        c_sp();
        if (!c_tok(',')) return 0;
    }
    return 0;
}

int sres() {            /* rt_sres's room for the statement's temporaries (c_sres), if it has strings */
    int n = c_sres();
    if (n) {
        pushint(n);
        ecall(&rt_sres, 0);
    }
    return 0;
}

int inputs() {          /* INPUT ["prompt";] v [, v ...]: rt_inp reads and checks the line (the count, found by a
                           look ahead, and the kinds go to it as a mask, put in the constant once the variables are
                           parsed), then each variable takes its field (rt_ifld) */
    int m = 0;
    int n;
    int i;
    int c;
    int a;
    int k;
    int t;
    c_sp();
    if (c_tok('"')) {
        strlit();
        need(';');
    } else {
        pushi(0);
    }
    c_sp();
    n = c_vars();
    if (n > 7) c_fail(11);
    pushi(n * 128);
    i = cend - 1 - (n > 1);     /* the constant's low byte (a CB's or a CW's): the mask is added to it */
    ecall(&rt_inp, -2);
    for (k = 0; k < n && !err; k = k + 1) {
        if (k) need(',');
        if (!c_sp() || !c_letter()) {
            c_fail(1);
            return 0;
        }
        a = var();
        t = vint;
        if (t != 2) m = m + (1 << k);
        sla(a, t);
        pcall(&rt_ifld, 1);
        c = 3;
        if (t != 2) c = val();
        assign(a, t, c);
    }
    mem[i] = mem[i] + m;
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
        c_sp();
        if (c_tok(',')) {
            c_sp();
            n2 = number() + 1;
            if (n2 < 1 || n2 > 15360) c_fail(2);
        }
        if (!need(')') || err) return 0;
        array(n1 + 1, n2);
        c_sp();
        if (!c_tok(',')) return 0;
    }
    return 0;
}

int predim() {          /* every DIM of the program, before a line is compiled: a subroutine at the end may DIM what the lines
                           before it use */
    int p = 0;
    int q;
    int c;
    while (p < ptop && !err) {
        scan(mem + p + 5);
        q = 0;
        c = src[0];
        while (c && c != 145 /* tk REM */ && !err) {
            if (c == '"') q = 1 - q;
            incsi();
            if (c == 164 /* tk DIM */ && !q) {
                nd = 0;
                ed = 0;
                dims();
                if (err) eline = mw(p);
            }
            c = c_ch();
        }
        p = next(p);
    }
    return 0;
}

int stmt() {
    c_sp();
    sres();
    if (c_tok(144 /* tk PRINT */)) { prints(); return 0; }
    if (c_tok(145 /* tk REM */)) {
        while (c_ch()) incsi();
        return 0;
    }
    if (c_tok(163 /* tk INPUT */)) { inputs(); return 0; }
    if (c_tok(164 /* tk DIM */)) { dims(); return 0; }
    if (c_tok(138 /* tk LET */)) { let(); return 0; }
    if (c_tok(136 /* tk IF */)) { ifs_(); return 0; }
    if (c_tok(133 /* tk GOSUB */)) {
        c_room(6);        /* the return address is 10 bytes on */
        c_opw(38 /* PO_LA */, addr(cend + 10));
        ecall(&rt_gosub, 0);
        gotol();
        c_ncall(&rt_ln);  /* the return address: the line is current again */
        return 0;
    }
    if (c_tok(134 /* tk GOTO */)) { gotol(); return 0; }
    if (c_tok(135 /* tk GO */)) {     /* GO TO */
        if (need(153 /* tk TO */)) { gotol(); return 0; }
        return 0;
    }
    if (c_tok(146 /* tk RETURN */)) {
        pcall(&rt_return, 0);
        return c_ncall(&rt_go);
    }
    if (c_tok(132 /* tk FOR */)) { fors(); return 0; }
    if (c_tok(141 /* tk NEXT */)) { nexts(); return 0; }
    if (c_tok(131 /* tk END */)) {
        c_op1(0 /* PO_CN 0 */);
        return c_op1(92 /* PO_RET */);
    }
    if (c_tok(150 /* tk STOP */)) {
        c_op1(18 /* PO_CN 9 */);
        return c_ncall(&c_throw);
    }
    if (c_letter()) { let(); return 0; }
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
        int p = ifh;
        ifh = mw(p);
        putw(mem + p, addr(cend));
    }
    return 0;
}

int cline(int p) {      /* compile the line at p */
    int n = mw(p);
    int i = 0;
    char *q;
    int t;
    putw(mem + p + 3, cend);
    while (i < nfix) {  /* the GOTOs waiting for this line, or for one that is not there */
        q = ctl + i * 6;
        t = getw(q + 2);
        if (t == n) putw(mem + getw(q), addr(cend));
        else if (c_ult(t, n)) {
            c_fail(10);
            eline = getw(q + 4);
            return 0;
        } else {
            i = i + 1;
            continue;
        }
        nfix = nfix - 1;
        c_mcpy(q - nul, ctl + nfix * 6 - nul, 6);
    }
    cur = n;
    c_xop(206 /* x LN */);
    scan(mem + p + 5);
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
        eline = getw(ctl + 4);
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

int wbad;               /* a write of BUILD's failed */

int wr(char *b, int n) {
    if (write(1, b, n) != n) wbad = 1;
    return 0;
}

int build() {           /* BUILD: the program as a file on the output: "BX", 1, rtid, the code's length, the
                           variables' size, the code, then the line table: per line the offset of its code
                           and its number. The code in the arena is spent */
    int p;
    clearv();
    compile();
    if (err) { report(err, eline); return 0; }
    reloc(addr(ptop), pend - ptop, addr(vbot), 1);
    ib[0] = 'B';
    ib[1] = 'X';
    ib[2] = 1;
    putw(ib + 3, rtid());
    putw(ib + 5, pend - ptop);
    putw(ib + 7, msz - vbot);
    wr(ib, 9);
    wr(mem + ptop, pend - ptop);
    for (p = 0; p < ptop; p = next(p)) {
        putw(ib, mw(p + 3) - ptop);
        putw(ib + 2, mw(p));
        wr(ib, 4);
    }
    if (wbad) {
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
        for (p = 0; p < ptop; p = next(p)) if (mw(p + 3) < a) ln = mw(p);
    report(e, ln);
    return 0;
}

int run(int t, int has) {       /* RUN [t] */
    clearv();
    compile();
    if (err) { report(err, eline); return 0; }
    heapinit();
    if (!has) { go(ptop); return 0; }
    cend = pend;
    cur = -1;
    prologue();
    jump(t);
    if (err) { report(err, -1); return 0; }
    go(pend);
    return 0;
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
    finish();
    return 0;
}

int immediate() {       /* compile the line after the program's code (compiling the program
                           first, for GOTO, if it is out of date) */
    int at;
    if (!pend && ptop) {
        compile();
        err = 0;
        scan(ib);     /* compile() read the program's lines */
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
        list(a, b);
        return 0;
    }
    if (c_tok(140 /* tk NEW */)) {
        if (!ended()) return 0;
        ptop = 0;
        clearv();
        return 0;
    }
    if (c_tok(147 /* tk RUN */)) {
        c_sp();
        if (c_digit()) {
            a = number();
            b = 1;
        }
        if (!ended()) return 0;
        run(a, b == 1);
        return 0;
    }
    if (c_tok(154 /* tk BUILD */)) {
        if (!ended()) return 0;
        build();
        return 0;
    }
    if (c_tok(165 /* tk SAVE */) || c_tok(166 /* tk LOAD */)) {
        a = ib[si - 1];     /* the token just taken: only its low bit tells them apart */
        c_sp();
        if (!c_tok('"')) {
            report(1, -1);
            return 0;
        }
        b = si;
        while (c_ch() && c_ch() != '"') incsi();
        ib[si] = 0;     /* the name, ended in place; the line has nothing else to give */
        if (!(a & 1)) {      /* LOAD, 166 */
            a = open(ib + b, 0);
            if (a >= 0) {
                if (ifd) close(ifd);     /* a LOAD in a loaded file takes over from it */
                ptop = 0;
                clearv();
                ifd = a;
            }
        } else {
            a = open(ib + b, 1 + 16 + 32);       /* O_WRONLY | O_CREAT | O_TRUNC */
            if (a >= 0) {
                ofd = a;
                list(0, -1);
                b = ofd;
                ofd = 1;
                close(a);
                if (b < 0) a = -1;      /* a write failed */
            }
        }
        if (a < 0) report(16, -1);
        return 0;
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
    if (err) { report(err, -1); return 0; }
    go(at);
    return 0;
}

int ifd;                /* the file a LOAD is reading, else 0: the keyboard */

int main() {
    int tty = isatty(0);
    int n;
    int t;
    msz = c_grow(120) * 256;    /* as many pages as are free, to 30,720 bytes: ints stay positive */
    if (msz < 4096) {
        write(2, "bas: out of memory\n", 19);
        exit(1);
    }
    ofd = 1;
    clearv();
    if (tty) {
        outu(vbot - ptop);
        outs(" BYTES FREE\nREADY.\n");
    }
    while (1) {
        il = 0;         /* the next line of stdin into ib (iread) */
        iov = 0;
        if (!iread(ifd)) {
            if (!ifd) break;
            close(ifd);         /* the end of a LOAD: back to the keyboard */
            ifd = 0;
            continue;
        }
        if (iov) report(3, -1);     /* too long */
        else {
            n = c_crunch(ib, kwt);  /* ib in place: keywords to tokens and the rest upper case,
                           outside quotes; tabs to spaces and runs of them to one, none leading
                           or trailing (but inside an unclosed string); a REM's text as typed.
                           The length, or -1 for a byte above 127 outside quotes */
            if (n == 0) continue;
            scan(ib);
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
