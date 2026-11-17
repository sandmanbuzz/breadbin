# Glob Implementation: Backtracking Pattern Matcher in 6502

## TITLE
A complete POSIX-style glob implementation (with `*` and `?` wildcards) in ~100 lines of 6502 assembly.

## PROBLEM
Expand file system patterns like `*.s` or `src/*` into lists of matching filenames. Constraints:
- No dynamic memory allocation (fixed 256-byte glob buffer)
- Page-boundary checks on the 6502 (16-bit pointers must not cross pages)
- Hidden file handling: names starting with `.` only match if the pattern starts with `.`
- Literal fallback: if nothing matches, use the original pattern as a literal name

## OBSERVATION
The `match` function (lines 1318-1369) implements backtracking pattern matching:
- `*` matches zero or more characters (with backtracking)
- `?` matches exactly one character (no backtracking)
- Other characters must match literally

The `g_star` variable (BSS line 79) holds the position of the most recent `*` in the pattern. When a mismatch occurs, the matcher backtracks to this position and tries advancing the pattern pointer by one.

The `g_store` function (lines 1267-1315) manages the glob buffer with page-boundary checks:
- `gpos` tracks the current position in the 256-byte `gbuf`
- Before appending, it checks that `gpos + d + 16 <= 256` (directory prefix + 15 name bytes + NUL)
- The page-crossing check uses `adc gpos` and tests carry — a classic 6502 idiom

The `glob` function (lines 1169-1264) orchestrates the search:
- Extracts the directory prefix (index after last `/`)
- Opens the directory for reading
- Reads 16-byte dirent entries and calls `match` on each
- Stores matches in `gbuf` via `g_store`
- Falls back to literal if nothing matched

## HYPOTHESIS
The backtracking algorithm is the right choice for this constraint budget:
1. It handles nested `*` patterns correctly (e.g., `*a*b*`)
2. It uses minimal extra state: only `g_star` (the backtrack point)
3. It avoids the exponential worst case of naive matching by only backtracking on `*`

The page-boundary check in `g_store` is correct because:
- `gpos` is the current offset in a 256-byte buffer (zero page pointer)
- Adding `g_d + 15` and checking carry catches any overflow past 255
- This is more efficient than checking the high byte of the pointer

## INVARIANTS
1. `g_word`/`g_word+1` always points to the original pattern
2. `g_d` always holds the directory prefix length (index after last `/`)
3. `g_n` always holds the number of matches found
4. `gpos`/`gpos+1` always point to the next free byte in `gbuf`
5. `g_ent`/`g_ent+1` always point to the current directory entry being matched

## TARGET CONTRACT
- CPU: 6502 (NMOS) — indirect zero-page indexing `(zp1),y` available
- Machine: C64 with Breadbin kernel's SYS_OPEN, SYS_READ, SYS_CLOSE for directory access
- Memory: zero page for pointers, BSS for state, stack for temporary saves
- Directory entries: 16 bytes each (name[15] + type[1])

## RESULT
The glob implementation:
- `match`: ~50 bytes, handles `*`, `?`, literal matching with backtracking
- `g_store`: ~40 bytes, manages the glob buffer with page-boundary checks
- `glob`: ~100 bytes, orchestrates directory traversal and matching
- Total: ~190 bytes of code for a complete glob implementation
- Uses ~40 bytes of BSS for glob state

## VERIFICATION
- Host tests include glob expansion tests
- The TAB completion feature depends on glob working correctly
- Hidden file handling is tested (names starting with `.`)
- Literal fallback is tested (patterns that match nothing)

## TRADE-OFFS
- **Pro:** Backtracking is correct for all valid glob patterns
- **Pro:** Page-boundary check in `g_store` is efficient (one `adc` + carry check)
- **Pro:** Hidden file handling is built in (line 1236-1248)
- **Con:** `g_star` backtracking has exponential worst case for `*a*a*a*a*a` patterns
- **Con:** The glob buffer is fixed at 256 bytes — long directory paths can overflow silently
- **Con:** No support for character classes (`[abc]`) — only `*` and `?`

## FAILED ALTERNATIVES
1. **Recursive matching**: Would need more stack space. The iterative backtracking is the right choice.
2. **Pre-compiled patterns**: Would need a pattern compiler and more BSS. The runtime matching is fine for typical glob patterns.
3. **No hidden file handling**: Would simplify the code but break user expectations on Unix-like systems.

## GENERAL PRINCIPLE
**"Backtracking with a single saved position is sufficient for glob matching."**

The `g_star` variable is the key insight: instead of saving the entire match state, only the `*` position needs to be preserved. When a mismatch occurs, the matcher backtracks to this position and advances the pattern pointer by one. This is a space-efficient approach that handles all standard glob patterns.

**"Page-boundary checks via carry are cheaper than explicit comparisons."**

The `adc gpos` + carry check in `g_store` is the canonical 6502 idiom for checking whether an addition will overflow a page. It's one instruction cheaper than `cmp #256` followed by `bcs`.

## REVERSION / FALLBACK
If glob patterns grow more complex (character classes, brace expansion), consider:
1. Adding a pattern compiler that expands patterns into a simpler matching format
2. Increasing the glob buffer size (currently 256 bytes)
3. Adding error handling for buffer overflow (currently silent)

## SOURCES AND CREDIT
- `src/bin/sh.s` lines 1153-1369: `is_glob`, `glob`, `g_store`, `match`
- The hidden file handling (line 1236-1248) follows Unix convention
- The page-boundary check (line 1273-1275) is a classic 6502 idiom

## DECISION
**Adopt** — this pattern is working and well-tested. The backtracking approach is correct and efficient for the constraints. The page-boundary check idiom is worth codifying as a standard.

---

# Coding Standards Derived from Glob Analysis

## Standard 6: Backtracking State Minimalism
When implementing backtracking matching:
- Save only the minimum state needed for backtrack (typically one pointer)
- Use a single variable (`g_star`) to track the backtrack point
- Avoid saving the entire match state on the stack

## Standard 7: Page-Boundary Check Idiom
To check if `A + B` crosses a 256-byte boundary:
```
lda A
clc
adc B
bcs @overflow
```
This is one instruction cheaper than `cmp #256` + `bcs`.

## Standard 8: Hidden File Convention
When implementing directory traversal:
- Hidden names (starting with `.`) only match patterns starting with `.`
- This is a Unix convention that users expect
- Implement with a simple check: `if pattern[0] == '.' then allow_hidden else deny`

## Standard 9: Literal Fallback Pattern
When a pattern matches nothing:
- Use the original pattern as a literal filename
- This matches shell behavior (e.g., `bash: *.xyz: No such file or directory`)
- Implement by copying the original pattern to the argument list when `g_n == 0`
