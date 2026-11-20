/* bas: Breadbin's compiled BASIC (docs/design/basic.md), slice L3b: the line store, LIST, NEW,
   RUN, and PRINT of string literals. It is /bin/bas until it replaces /bin/basic (L3e).

   The program is kept as text, sorted by line number. RUN compiles all of it to p-code in
   code[] and calls that (icall); a line typed without a number is compiled after the last RUN's
   code and run the same way. The compiled code calls the rt_ functions below by address.

   Mini C (tools/cc.py --pcode); built by mk/pvm.mk; tested by tools/test_bas.py (py65) and
   tests/test_pvm_machine.py (VICE). An opcode is written as its number with its name in a
   comment, which tools/test_bas.py checks against src/pvm/pvm.inc. */

char prog[4096];        /* the program: per line its number (low, high), length and text */
int ptop;               /* bytes in use */
char code[2048];        /* bytecode: the last RUN's program in [0, pend), then a typed line */
int pend;
int cend;
int straight;           /* bytes since the VM last reset Y: pvm.s addresses code as base + Y */
int err;                /* 1 syntax, 2 out of memory, 3 line too long */
char lbuf[162];         /* the line being read or compiled, NUL-ended */
char *src;
int si;                 /* the parse position in src */
char ibuf[128];         /* standard input */
int ipos;
int ilen;
char obuf[128];         /* standard output, flushed at each newline and before each read */
int olen;
int col;                /* the output is not at the start of a line */
char *nul;              /* 0: an address minus nul is the address as an int */

/* ---- output ---- */

int flush() {
    if (olen) write(1, obuf, olen);
    olen = 0;
    return 0;
}

int outc(int c) {
    if (olen == 128) flush();
    obuf[olen] = c;
    olen = olen + 1;
    col = c != '\n';
    if (c == '\n') flush();
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

int ult(int a, int b) { /* a < b, unsigned */
    return (a ^ -32768) < (b ^ -32768);
}

/* ---- input ---- */

int getline() {         /* the next line of stdin into lbuf: its length, -1 at the end, -2 too long */
    int n = 0;
    int over = 0;
    int c;
    while (1) {
        if (ipos == ilen) {
            flush();
            ilen = read(0, ibuf, 128);
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

int upper(int c) {
    if (c >= 'a' && c <= 'z') return c - 32;
    return c;
}

int normal() {          /* lbuf in place: upper case outside quotes, tabs to spaces and runs of
                           them to one, none leading or trailing (but inside an unclosed string);
                           a REM's text as typed. Returns the length. */
    int i = 0;
    int o = 0;
    int q = 0;
    int st = 1;         /* at the start of a statement (or in the line number) */
    int lead = 1;       /* in the line number */
    int c;
    while (lbuf[i]) {
        c = lbuf[i];
        if (c == 9 && !q) c = ' ';
        if (!q && st && upper(c) == 'R' && upper(lbuf[i + 1]) == 'E' && upper(lbuf[i + 2]) == 'M') {
            lbuf[o] = 'R';
            lbuf[o + 1] = 'E';
            lbuf[o + 2] = 'M';
            o = o + 3;
            i = i + 3;
            while (lbuf[i]) {
                lbuf[o] = lbuf[i];
                o = o + 1;
                i = i + 1;
            }
            q = 2;      /* keep the trailing spaces too */
            break;
        }
        i = i + 1;
        if (q) {
            if (c == '"') q = 0;
        } else if (c == ' ') {
            if (o == 0 || lbuf[o - 1] == ' ') continue;
        } else {
            c = upper(c);
            if (c == '"') q = 1;
            if (c == ':') st = 1;
            else if (!lead || c < '0' || c > '9') {
                st = 0;
                lead = 0;
            }
        }
        lbuf[o] = c;
        o = o + 1;
    }
    if (!q) while (o > 0 && lbuf[o - 1] == ' ') o = o - 1;
    lbuf[o] = 0;
    return o;
}

/* ---- parsing ---- */

int skipsp() {
    while (src[si] == ' ') si = si + 1;
    return 0;
}

int kw(char *k) {       /* the keyword k at si: step over it */
    int i = 0;
    while (k[i]) {
        if (src[si + i] != k[i]) return 0;
        i = i + 1;
    }
    si = si + i;
    return 1;
}

int digit() {
    return src[si] >= '0' && src[si] <= '9';
}

int number() {          /* a line number at si (0 to 63999, unsigned), spaces among its digits
                           and after it skipped, as MS; none or too big is a syntax error */
    int n = 0;
    if (!digit()) err = 1;
    while (digit()) {
        if (n > 6399) err = 1;
        n = n * 10 + src[si] - '0';
        si = si + 1;
        skipsp();
    }
    if (ult(63999, n)) err = 1;
    return n;
}

/* ---- the line store ---- */

int lineno(int p) {
    return prog[p] + (prog[p + 1] << 8);
}

int next(int p) {
    return p + 3 + prog[p + 2];
}

int find(int n) {       /* the first line numbered n or above */
    int p = 0;
    while (p < ptop && ult(lineno(p), n)) p = next(p);
    return p;
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

int store(int n, int t, int len) {  /* line n is lbuf from t, len bytes; none deletes it */
    int p = find(n);
    int old = 0;
    int add = 0;
    if (p < ptop && lineno(p) == n) old = next(p) - p;
    if (len) add = len + 3;
    if (ptop - old + add > 4096) {
        err = 2;
        return 0;
    }
    move(prog + p + add, prog + p + old, ptop - p - old);
    ptop = ptop - old + add;
    if (len) {
        prog[p] = n;
        prog[p + 1] = n >> 8;
        prog[p + 2] = len;
        move(prog + p + 3, lbuf + t, len);
    }
    pend = 0;           /* the compiled program is out of date */
    return 0;
}

int list(int a, int b) {
    int p = 0;
    int n;
    int i;
    while (p < ptop) {
        n = lineno(p);
        if (!ult(n, a) && !ult(b, n)) {
            outu(n);
            outc(' ');
            for (i = p + 3; i < next(p); i = i + 1) outc(prog[i]);
            outc('\n');
        }
        p = next(p);
    }
    return 0;
}

/* ---- the code generator ---- */

int emit(int b) {
    if (cend == 2048) {
        err = 2;
        return 0;
    }
    code[cend] = b;
    cend = cend + 1;
    straight = straight + 1;
    return 0;
}

int room(int n) {       /* before an instruction of n bytes: past 240, a branch to the next
                           instruction resets Y (as cc_pcode's op()) */
    if (straight + n > 240) {
        emit(80 /* PO_BRNCH */);
        emit(2);        /* relative to the offset word: the next instruction */
        emit(0);
        straight = 0;
    }
    return 0;
}

int ecall(char *f) {    /* CALL f, DROP its result */
    int a = f - nul;
    room(3);
    emit(84 /* PO_CALL */);
    emit(a);
    emit(a >> 8);
    straight = 0;       /* the return resets Y */
    emit(48 /* PO_DROP */);
    return 0;
}

int begin() {           /* a bytecode function's header: JSR pvm_interp, as main's */
    char *m = &main;
    emit(m[0]);
    emit(m[1]);
    emit(m[2]);
    straight = 0;
    return 0;
}

int finish() {
    room(2);
    emit(0 /* PO_CN 0 */);
    emit(92 /* PO_RET */);
    return 0;
}

/* ---- the runtime the compiled code calls ---- */

int rt_prs(char *s) {   /* a CS string: length, then the text */
    int i;
    for (i = 1; i <= s[0]; i = i + 1) outc(s[i]);
    return 0;
}

int rt_nl() {
    outc('\n');
    return 0;
}

/* ---- statements ---- */

int prints() {          /* PRINT: string literals; ; between them, or after the last for no newline */
    int nl = 1;
    int i;
    int n;
    while (1) {
        skipsp();
        if (src[si] == 0 || src[si] == ':') break;
        if (src[si] == ';') {
            si = si + 1;
            nl = 0;
            continue;
        }
        if (src[si] != '"') {
            err = 1;
            return 0;
        }
        si = si + 1;
        i = si;
        while (src[si] && src[si] != '"') si = si + 1;
        n = si - i;
        if (src[si]) si = si + 1;   /* an unclosed string ends at the end of the line, as MS */
        if (n) {
            room(2);
            emit(46 /* PO_CS */);
            emit(n);
            while (i < si && src[i] != '"') {
                emit(src[i]);
                i = i + 1;
            }
            straight = n + 1;       /* CS moves the base to the string: the next op is past it */
            ecall(&rt_prs);
        }
        nl = 1;
    }
    if (nl) ecall(&rt_nl);
    return 0;
}

int stmt() {
    if (kw("PRINT") || kw("?")) return prints();
    if (kw("REM")) {
        while (src[si]) si = si + 1;
        return 0;
    }
    err = 1;
    return 0;
}

int stmts() {           /* the statements of src from si, : between them */
    while (!err) {
        skipsp();
        if (src[si] == 0) return 0;
        if (src[si] == ':') {
            si = si + 1;
            continue;
        }
        stmt();
        if (err) return 0;
        skipsp();
        if (src[si] == ':') si = si + 1;
        else if (src[si]) err = 1;
    }
    return 0;
}

/* ---- commands ---- */

int report(int line) {  /* the error in err, as MS prints it; line -1 for none */
    fresh();
    outc('?');
    if (err == 1) outs("SYNTAX");
    else if (err == 2) outs("OUT OF MEMORY");
    else outs("LINE TOO LONG");
    outs(" ERROR");
    if (line != -1) {
        outs(" IN ");
        outu(line);
    }
    outc('\n');
    err = 0;
    return 0;
}

int run() {
    int p = 0;
    int len;
    pend = 0;           /* the buffer is rewritten from the start */
    cend = 0;
    begin();
    while (p < ptop) {
        len = prog[p + 2];
        move(lbuf, prog + p + 3, len);
        lbuf[len] = 0;
        src = lbuf;
        si = 0;
        stmts();
        if (err) {
            cend = 0;
            return report(lineno(p));
        }
        p = next(p);
    }
    finish();
    if (err) {
        cend = 0;
        return report(-1);
    }
    pend = cend;
    icall(code);
    return 0;
}

int ended() {           /* nothing after a command but spaces, and no error so far */
    skipsp();
    if (src[si]) err = 1;
    return !err;
}

int command() {         /* a line without a number */
    int a = 0;
    int b = -1;
    if (kw("LIST")) {
        skipsp();
        if (digit()) {
            a = number();
            b = a;
        }
        skipsp();
        if (src[si] == '-') {
            si = si + 1;
            skipsp();
            b = -1;
            if (digit()) b = number();
        }
        if (!ended()) return report(-1);
        return list(a, b);
    }
    if (kw("NEW")) {
        if (!ended()) return report(-1);
        ptop = 0;
        pend = 0;
        return 0;
    }
    if (kw("RUN")) {
        if (!ended()) return report(-1);
        return run();
    }
    if (kw("BYE") || kw("SYSTEM")) {
        if (!ended()) return report(-1);
        flush();
        exit(0);
    }
    cend = pend;        /* immediate mode: compile the line after the program, run it */
    begin();
    stmts();
    finish();
    if (err == 2 && pend) {     /* no room after the program: drop its code, as RUN recompiles */
        err = 0;
        pend = 0;
        cend = 0;
        si = 0;
        begin();
        stmts();
        finish();
    }
    if (err) return report(-1);
    icall(code + pend);
    return 0;
}

int main() {
    int tty = isatty(0);
    int n;
    int t;
    if (tty) outs("READY.\n");
    while (1) {
        n = getline();
        if (n == -1) break;
        if (n == -2) {
            err = 3;
            report(-1);
            if (tty) {
                fresh();
                outs("READY.\n");
            }
            continue;
        }
        n = normal();
        if (n == 0) continue;
        src = lbuf;
        si = 0;
        if (digit()) {  /* a numbered line: store it (no READY, as MS) */
            t = number();
            if (!err) {
                store(t, si, n - si);
            }
            if (!err) continue;
            report(-1);
        } else command();
        if (tty) {
            fresh();
            outs("READY.\n");
        }
    }
    flush();
    return 0;
}
