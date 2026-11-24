# Compiled files: BUILD and brun

`bas` runs a program by compiling it to p-code in memory. For a program too big to keep as text
beside its compiler, or to hand to someone who only needs to run it, `BUILD` writes the compiled
code to a file and `brun` runs that file. `brun` is the runtime and the VM with no compiler and no
program text, so the whole arena is left for the program.

## Making a file

Put `BUILD` after the program, give `bas` the text on its input and send its output to a file:

    bas < hello.bas > hello.bx
    brun hello.bx

`BUILD` compiles the whole program, as `RUN` does, but writes it instead of running it. The program
stays in memory, so `RUN` after `BUILD` still works. Anything `BUILD` has to say goes to standard
output like the file itself, so the output of a failed build is an error message, not a file:
build non-interactively, and read the file's first two bytes (`BX`) if a script must be sure.

An example (the examples in this book are run by `tools/test_manual.py`; a `bas` block is the
program, the `out` block after it is what `brun` prints):

```bas
10 FOR I=1 TO 3
20 PRINT I;
30 NEXT I
40 PRINT "BUILT"
50 PRINT 1/0
60 PRINT "NEVER"
BUILD
```

```out
 1  2  3 BUILT
?DIVISION BY ZERO ERROR IN 50
```

`brun` exits 1 after a runtime error, 0 after a normal end, so `brun hello.bx && next` behaves.

Numbers are the same fixed point as in `RUN` (four decimals), and a program gives the same output
either way: the tests run every example both ways and compare.

```bas
10 X=1109.0726
20 PRINT X;X*2;-X
BUILD
```

```out
 1109.0726  2218.1452 -1109.0726 
```

## What a file is

A `.bx` file is `"BX"`, a format byte (1), a layout id (2), the code's length (2), the variables'
size (2), the code, then a line table: for each program line the offset of its code and its
number (2 + 2 bytes). The code holds no addresses, only offsets, so the file does not depend on
where the arena is; `brun` turns the offsets back into addresses as it loads. The line table is
only read when an error happens, to say `IN 50`.

The layout id is a number computed from the sizes of the two runtime blocks the offsets point
into. `brun` refuses a file whose id is not its own, with `brun: not a file of this bas`: a file
is only good for the `bas` that made it, so rebuild after the system is updated.

## Limits and cautions

- **A file is code, not data.** `brun` checks the header and that the code and variables fit in
  memory (`brun: out of memory` otherwise), but it does not check each operand of a file: a file
  damaged after `BUILD` can misbehave. Treat a `.bx` as you would any program you run.
- **`BUILD` needs the room of `RUN`.** The compiled code is made in the arena beside the text,
  and then written; a program that does not compile in the arena does not build either.
- **A failed write stops the build** with `bas: write failed` and exit status 1.
- **Interactive use writes the banner into the file.** Redirect only non-interactive input.
