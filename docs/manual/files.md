# Keeping programs: SAVE and LOAD

A program lives in memory until you leave `bas`. To keep it, give it a name:

```text
SAVE "/home/hello.bas"
```

`SAVE` writes the program as `LIST` would print it, one numbered line to each line of the file,
and makes the file if it is not there or empties it if it is. Nothing is printed. The name is
whatever is between the quotes, exactly as typed (capitals and all), and may be a path.

To bring a program back:

```text
LOAD "/home/hello.bas"
```

`LOAD` first does a `NEW`: the program in memory and every variable are gone. Then each line
of the file is read as if you had typed it, so a line with a number is stored, and a line without
one is a command and is run. A file that ends with `RUN` therefore runs itself when loaded. At
the end of the file you are back at the keyboard.

Both are commands, like `LIST` and `RUN`: they work on a line typed to `bas`, not inside a
program.

## Errors

- `?FILE NOT FOUND ERROR`: `LOAD` could not open the name, or `SAVE` could not make it (a
  directory that is not there, a full disk). A failed `LOAD` leaves the program as it was.
- `?SYNTAX ERROR`: the name is not in quotes.

## Without typing LOAD

`bas` reads its commands from the keyboard or from a pipe, so a saved program also runs with the
shell's own redirection: `bas < /home/hello.bas` loads the lines and, if the file ends in `RUN`,
runs them. Add `BYE` (or let the input end) to leave.

## Differences from the C64

`SAVE` and `LOAD` take a Unix path, not a device number, and there is no `VERIFY`. A
`LOAD "name"` does not mean `,8`: the file is read from wherever the path says.
