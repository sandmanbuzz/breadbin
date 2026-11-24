# Strings, INPUT and arrays (reference)

The reference entries for `bas` that came with L3d. Every example below is run by the tests
(`tools/test_manual.py`): the output shown is what the built file prints under `brun`, and what `RUN`
prints.

## Strings

A name ending in `$` is a string variable (`A$`, `N1$`). As in MS BASIC two characters of a name count, and
`A` and `A$` are different variables. A string is 0 to 255 characters; a longer result is `?STRING TOO LONG`.
A string and a number never mix: `A$=1` and `A=A$` are `?TYPE MISMATCH`, found when the line is compiled.

A string literal is in quotes (an unclosed one ends at the end of the line). `+` joins two strings; the
comparison operators `= <> < > <= >=` compare two strings by the codes of their characters, and the first
difference decides; a shorter string that is the start of a longer one sorts first.

```bas
10 A$="BREAD":B$="BIN"
20 C$=A$+B$
30 PRINT C$;LEN(C$)
40 IF A$<B$ THEN PRINT "A$ SORTS FIRST"
50 IF B$<A$ THEN PRINT "B$ SORTS FIRST"
BUILD
```
```out
BREADBIN 8 
B$ SORTS FIRST
```

| Function | Gives |
|---|---|
| `LEN(s$)` | the number of characters |
| `LEFT$(s$,n)` | the first n characters |
| `RIGHT$(s$,n)` | the last n characters |
| `MID$(s$,i[,n])` | n characters from the i-th (1 is the first); to the end without n |
| `ASC(s$)` | the code of the first character (`?ILLEGAL QUANTITY` for ""), `CHR$(n)` is its inverse |
| `CHR$(n)` | the character with code n (0 to 255) |
| `STR$(x)` | the number as `PRINT` writes it, without the space after (a space stands for a plus sign) |
| `VAL(s$)` | the number at the start of the string: spaces, a sign, digits, a point; 0 if there is none |

```bas
10 S$="BREADBIN"
20 PRINT LEFT$(S$,5);"|";RIGHT$(S$,3);"|";MID$(S$,3,4);"|";MID$(S$,6)
30 PRINT ASC(S$);CHR$(72);CHR$(ASC("A")+1)
BUILD
```
```out
BREAD|BIN|EADB|BIN
 66 HB
```

```bas
10 PRINT STR$(12.5);"|";STR$(-3);"|";VAL("  42.75xyz")+1;VAL("ABC")
20 PRINT VAL(STR$(3.1416))
BUILD
```
```out
 12.5|-3| 43.75  0 
 3.1416 
```

Differences from the C64's BASIC:

- `VAL` reads at most four decimals (the rest is dropped, not rounded) and has no exponent: numbers here are
  fixed point with four decimals.
- Type errors (`A$=1`) are found when the line is compiled, so a program with one does not start.
- A string literal assigned to a variable is copied, so an edit never changes a variable already set.
- The string heap is collected when a statement needs room (never in the middle of one), so a long program
  does not stop for "garbage collection" at a random point; running out of room is `?OUT OF MEMORY`.

## INPUT

`INPUT ["prompt";] v [, v ...]` writes the prompt and `? `, reads a line from the input and gives each variable
(up to 7) its field. Fields are separated by commas; leading spaces are dropped, and a field in quotes keeps
its commas. As in MS BASIC:

- a line with too few fields gets `??` and the rest is read from the next line;
- a number that is not one gives `?REDO FROM START` and the whole statement asks again (the prompt is not
  repeated);
- a line with too many fields gives `?EXTRA IGNORED`;
- an empty number field is 0, an empty string field is "".

At the end of the input the program stops with `BREAK`. (The examples of this book have no input to read, so
this one is not run: `10 INPUT "NAME";N$,AGE` then `20 PRINT N$;AGE` prints `NAME? ` and waits.)

## DIM and arrays

`DIM v(n [, m]) [, ...]` makes an array of numbers (`A`), integers (`A%`) or strings (`A$`), one dimension or two.
The subscripts run from 0 to the size given: `DIM A(4)` has five elements. An array that is not dimensioned
is made on first use with 0 to 10 (11 by 11 for two subscripts). A subscript out of range is `?BAD
SUBSCRIPT`; a second `DIM` of an array with other sizes is `?REDIM'D ARRAY`.

```bas
10 DIM A(4),N$(2)
20 FOR I=0 TO 4:A(I)=I*I:NEXT
30 N$(0)="ZERO":N$(1)="ONE":N$(2)="TWO"
40 PRINT A(3);A(4);N$(1);LEN(N$(2))
50 PRINT B(7)
BUILD
```
```out
 9  16 ONE 3 
 0 
```

```bas
10 DIM G(2,3)
20 FOR R=0 TO 2:FOR C=0 TO 3:G(R,C)=R*10+C:NEXT:NEXT
30 PRINT G(1,2);G(2,3)
40 GOSUB 100
50 PRINT T(5)
60 END
100 DIM T(9):T(5)=7:RETURN
BUILD
```
```out
 12  23 
 7 
```

Differences from the C64's BASIC:

- The sizes are numbers, not expressions (`DIM A(N)` is a `?SYNTAX ERROR`): the arrays are made when the
  program is compiled, which is also why the `DIM` in a subroutine at the end (above) is there for the lines
  before it. A `DIM` that is run again does nothing, where MS gives `?REDIM'D ARRAY`.
- An array takes 4 bytes an element (2 for integers and strings) and the room comes out of the same arena as
  the code, the variables and the strings; `?OUT OF MEMORY` if it does not fit.
