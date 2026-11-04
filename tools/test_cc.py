"""Host-only tests of the S14 reference compiler (tools/cc.py): no VICE, no device, no `as`."""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cc  # noqa: E402


def compile_src(src):
    return cc.compile_c(src)


def defined_labels(text):
    return [m.group(1) for m in re.finditer(r"^([A-Za-z_][A-Za-z_0-9]*):", text, re.M)]


def branch_targets(text):
    # sys_* names are predefined by `as` (the system call table), not labels of this file
    # relative targets (*+5) name no label; sys_* names are predefined by `as`
    return [t for t in re.findall(r"^\s+(?:jmp|beq|bne|bcc|bcs)\s+(\S+)", text, re.M)
            if not t.startswith(("sys_", "*"))]


HELLO = """\
int main() {
  puts("hello, world!\\n");
  return 0;
}
"""


class Hello(unittest.TestCase):
    def test_entry_calls_main_and_exits(self):
        out = compile_src(HELLO)
        self.assertTrue(out.startswith("start:\n"), out[:40])
        self.assertIn("        jsr fn_main\n        lda #0\n        jmp sys_exit\n", out)

    def test_string_is_zero_terminated_bytes(self):
        out = compile_src(HELLO)
        self.assertIn("s_1:\n        .byte 104, 101, 108, 108, 111, 44, 32, 119, 111, 114, 108, 100, 33, 10, 0\n", out)

    def test_long_string_is_split_into_short_lines(self):
        # as reads at most 127 characters a line and drops the rest silently
        text = "the quick brown fox jumps over the lazy dog, twice over and over again\\n"
        out = compile_src('int main() { puts("%s"); return 0; }' % text)
        lines = out.split("\n")
        self.assertTrue(all(len(l) <= 127 for l in lines), max(len(l) for l in lines))
        data = []
        for l in lines:
            if l.startswith("        .byte "):
                data += [int(v) for v in l[len("        .byte "):].split(",")]
        self.assertEqual(data, list(text.replace("\\n", "\n").encode("latin-1")) + [0])

    def test_puts_goes_through_the_runtime_and_sys_write(self):
        out = compile_src(HELLO)
        self.assertIn("        lda #<s_1\n        sta cc_ptr\n        lda #>s_1\n        sta cc_ptr+1\n"
                      "        jsr rt_puts\n", out)
        self.assertIn("rt_puts:", out)
        self.assertIn("        lda (cc_ptr),y\n", out)
        self.assertIn("        jsr sys_write\n", out)

    def test_string_pointer_is_zero_page(self):
        # (zp),y needs a zero-page pointer; `as` does not check it (the machine run found the bug)
        out = compile_src(HELLO)
        self.assertIn("cc_ptr = $2b", out)
        self.assertNotIn("cc_ptr: .res", out)

    def test_every_branch_target_is_defined_once(self):
        out = compile_src(HELLO)
        labels = defined_labels(out)
        self.assertEqual(len(labels), len(set(labels)), labels)
        for t in branch_targets(out):
            self.assertIn(t, labels, t)


class Control(unittest.TestCase):
    SRC = """\
int main() {
  int i = 0;
  int n = 0;
  while (i < 10) {
    if (i == 3) {
      n = n + 100;
    } else {
      n = n + i;
    }
    i = i + 1;
  }
  return n;
}
"""

    def test_branches_use_the_long_form(self):
        # a short conditional branch reaches 127 bytes; a body can be longer than that
        body = "".join("    n = n + %d;\n" % i for i in range(60))
        src = "int main() { int n = 0; int i = 0; while (i < 2) {\n" + body + "    i = i + 1; } return n; }\n"
        out = compile_src(src)
        lines = out.split("fn_main:\n", 1)[1].split("; --- runtime", 1)[0].split("\n")
        for i, line in enumerate(lines):
            if re.match(r"\s+(beq|bne|bcc|bcs)\s", line):
                self.assertTrue(lines[i + 1].startswith("        jmp "), (line, lines[i + 1]))

    def test_while_and_if_labels_resolve(self):
        out = compile_src(self.SRC)
        labels = defined_labels(out)
        self.assertEqual(len(labels), len(set(labels)))
        for t in branch_targets(out):
            self.assertIn(t, labels, t)

    def test_locals_are_static_storage(self):
        out = compile_src(self.SRC)
        self.assertIn("v_main_i: .res 2", out)
        self.assertIn("v_main_n: .res 2", out)

    def test_comparison_and_arithmetic_routines_used(self):
        out = compile_src(self.SRC)
        self.assertIn("        jsr cc_lt\n", out)
        self.assertIn("        jsr cc_eq\n", out)
        self.assertIn("        jsr cc_add\n", out)

    def test_every_operator_maps_to_its_routines(self):
        cases = {
            "+": ["cc_add"],
            "-": ["cc_sub"],
            "==": ["cc_eq"],
            "!=": ["cc_eq", "cc_not"],
            "<": ["cc_lt"],
            ">": ["cc_swap", "cc_lt"],
            "<=": ["cc_swap", "cc_lt", "cc_not"],
            ">=": ["cc_lt", "cc_not"],
        }
        for op, routines in cases.items():
            src = f"int main() {{ return 1 {op} 2; }}"
            out = compile_src(src)
            body = out.split("fn_main:\n", 1)[1].split("cc_pop\n", 1)[1]
            seq = re.findall(r"jsr (cc_\w+)", body)[:len(routines)]
            self.assertEqual(seq, routines, op)

    def test_unary_minus_subtracts_from_zero(self):
        out = compile_src("int main() { return -5; }")
        self.assertIn("        lda #0\n        sta tmp\n        sta tmp+1\n        jsr cc_sub\n", out)

    def test_call_to_user_function(self):
        src = "int f() { return 7; }\nint main() { f(); return 0; }\n"
        out = compile_src(src)
        self.assertIn("fn_f:\n", out)
        self.assertIn("        jsr fn_f\n", out)


class Errors(unittest.TestCase):
    def assertFails(self, src, message):
        with self.assertRaises(cc.CompileError) as ctx:
            compile_src(src)
        self.assertIn(message, str(ctx.exception))

    def test_no_main(self):
        self.assertFails("int f() { return 0; }", "no function main")

    def test_undefined_variable(self):
        self.assertFails("int main() { return x; }", "undefined variable x")

    def test_undefined_function(self):
        self.assertFails("int main() { g(); return 0; }", "undefined function g")

    def test_redeclared_local(self):
        self.assertFails("int main() { int a; int a; return 0; }", "already declared")

    def test_string_is_not_a_number(self):
        self.assertFails('int main() { return "x"; }', "return: a pointer where a number is needed")

    def test_puts_needs_one_literal(self):
        self.assertFails("int main() { puts(3); return 0; }", "puts takes one string literal")

    def test_wrong_argument_count(self):
        self.assertFails("int f(int a) { return a; }\nint main() { return f(); }", "takes 1 argument(s), not 0")

    def test_array_parameters_are_refused(self):
        self.assertFails("int f(int a[]) { return 0; }\nint main() { return 0; }", "array parameters")

    def test_array_of_pointers_is_refused(self):
        self.assertFails("int main() { char *a[3]; return 0; }", "array of pointers")

    def test_an_int_is_not_stored_into_a_pointer(self):
        self.assertFails("int main() { int *p; p = 5; return 0; }", "assign: a number where a pointer is needed")

    def test_a_pointer_is_not_stored_into_an_int(self):
        self.assertFails("int main() { int *p; int x = p; return 0; }", "initialise: a pointer where a number is needed")

    def test_pointer_base_must_match(self):
        self.assertFails("int main() { int *p; char *q; q = p; return 0; }",
                         "assign: a pointer to int where a pointer to char is needed")

    def test_argument_type_is_checked(self):
        self.assertFails("int g(int *p) { return 0; }\nint main() { return g(5); }",
                         "argument p of g: a number where a pointer is needed")

    def test_return_of_a_pointer_is_refused(self):
        self.assertFails("int main() { int *p; return p; }", "return: a pointer where a number is needed")

    def test_main_takes_no_parameters(self):
        self.assertFails("int main(int argc) { return argc; }", "main takes no parameters")

    def test_unary_minus_of_a_pointer_is_refused(self):
        self.assertFails("int main() { int a[2]; return -a; }", "- of a pointer")

    def test_static_bytes_are_bounded(self):
        self.assertFails("int main() { char s[9000]; return 0; }", "static variables take 9000 bytes")

    def test_the_null_pointer_constant_is_allowed(self):
        compile_src("int main() { int *p; p = 0; return 0; }")

    def test_a_global_initialiser_must_be_a_literal(self):
        self.assertFails("int g = 1 + 2;\nint main() { return g; }", "a global needs a literal initialiser")

    def test_a_pointer_cannot_be_multiplied(self):
        self.assertFails("int main() { int a[2]; return a * 2; }", "a pointer can only be added to or subtracted from")

    def test_a_string_array_needs_a_string(self):
        self.assertFails("int main() { char s[] = 5; return 0; }", "an array can only be initialised from a string literal")

    def test_a_string_array_needs_the_size_or_a_string(self):
        self.assertFails("int main() { char s[]; return 0; }", "needs a size or a string")

    def test_a_string_is_not_a_global_pointer_to_int(self):
        self.assertFails('int *p = "abc";\nint main() { return 0; }', "a string is a pointer to char")

    def test_a_local_char_array_must_hold_its_string(self):
        self.assertFails('int main() { char s[2] = "abc"; return 0; }', "the string does not fit in s")

    def test_int_alone_and_int_star_alone_are_compile_errors(self):
        self.assertFails("int", "expected id")
        self.assertFails("int *", "expected id")
        self.assertFails("char", "expected id")

    def test_a_nul_in_a_string_is_refused_everywhere(self):
        self.assertFails('char msg[] = "a\\0b";\nint main() { return 0; }', "would end it early")
        self.assertFails('char *p = "a\\0b";\nint main() { return 0; }', "would end it early")

    def test_a_char_global_takes_0_to_255(self):
        self.assertFails("char c = 300;\nint main() { return c; }", "a char global takes 0 to 255")

    def test_a_global_cannot_share_a_function_name(self):
        self.assertFails("int f;\nint f() { return 0; }\nint main() { return 0; }", "is a function")

    def test_initialised_data_comes_before_every_res(self):
        src = ("char buf[100];\nint seed = 1;\nchar *msg = \"hi\";\nint n;\n"
               "int main() { char local[9]; buf[0] = 1; return seed; }")
        out = compile_src(src)
        lines = out.split("\n")
        # the global and local reservations (the runtime's own .res are not in question)
        first_res = min(i for i, l in enumerate(lines) if ".res" in l and l.split(":")[0].startswith(("g_", "v_")))
        for init_line in ("g_seed:", "g_msg: .word"):
            self.assertLess(next(i for i, l in enumerate(lines) if l.startswith(init_line)), first_res)

    def test_a_pointer_to_a_literal_has_its_own_bytes(self):
        # the same text used by puts and by a pointer: the pointer may be written, so it is not shared
        out = compile_src('char *p = "abc";\nint main() { char *q = "abc"; puts("abc"); return 0; }')
        self.assertEqual(out.count(".byte 97, 98, 99, 0"), 3)     # the global, the local and puts: three labels

    def test_index_needs_a_pointer(self):
        self.assertFails("int main() { int x = 1; return x[0]; }", "needs a pointer or an array")

    def test_cannot_assign_to_an_array(self):
        self.assertFails("int main() { int a[3]; a = 1; return 0; }", "cannot assign to the array a")

    def test_pointers_to_pointers_are_refused(self):
        self.assertFails("int main() { int *p; int *q; q = &p; return 0; }", "pointers to pointers")

    def test_deref_needs_a_pointer(self):
        self.assertFails("int main() { int x; return *x; }", "* needs a pointer")

    def test_missing_brace(self):
        self.assertFails("int main() { return 0;", "missing '}'")

    def test_bad_character(self):
        self.assertFails("int main() { return 0; } @", "bad character '@'")

    def test_unterminated_string(self):
        self.assertFails('int main() { puts("abc); return 0; }', "bad character")

    def test_number_too_big(self):
        self.assertFails("int main() { return 70000; }", "does not fit in 16 bits")

    def test_duplicate_function(self):
        self.assertFails("int main() { return 0; }\nint main() { return 1; }", "defined twice")

    def test_as_symbol_limit(self):
        self.assertFails("int main() { int abcdefghijklmnop; return 0; }", "longer than 14 characters")

    def test_names_clash_regardless_of_case(self):
        self.assertFails("int main() { int Count = 1; int count = 2; return 0; }", "clashes with")

    def test_function_name_length(self):
        self.assertFails("int abcdefghijklmn() { return 0; }\nint main() { return 0; }", "longer than 14 characters")

    def test_recursion_is_refused(self):
        self.assertFails("int f() { return f(); }\nint main() { return f(); }", "recursion")

    def test_mutual_recursion_is_refused(self):
        self.assertFails("int f() { return g(); }\nint g() { return f(); }\nint main() { return f(); }",
                         "recursion")

    def test_stack_along_a_call_chain_is_checked(self):
        # each function is within 31 levels; the call from inside an expression adds to the chain
        inner = "1+(" * 20 + "1" + ")" * 20
        src = ("int f() { return %s; }\n"
               "int main() { int y = %s f() %s; return 0; }\n") % (inner, "1+(" * 20, ")" * 20)
        self.assertFails(src, "stack use along one call chain")

    def test_latin1_only(self):
        self.assertFails('int main() { puts("\u20ac"); return 0; }', "Latin-1")

    def test_string_longer_than_rt_puts_allows(self):
        self.assertFails('int main() { puts("%s"); return 0; }' % ("a" * 255), "longer than 254 bytes")

    def test_embedded_nul_is_refused(self):
        self.assertFails('int main() { puts("a\\0b"); return 0; }', "would end it early")

    def test_a_string_is_not_a_number(self):
        self.assertFails('int main() { return "x"; }', "return: a pointer where a number is needed")

    def test_division_by_a_pointer_is_refused(self):
        self.assertFails("int main() { int a[2]; return 6 / a; }", "a pointer cannot be the right side of /")

    def test_deep_parentheses_are_a_compile_error(self):
        src = "int main() { return " + "(" * 400 + "1" + ")" * 400 + "; }"
        self.assertFails(src, "too deeply for the parser")

    def test_symbol_table_limit(self):
        body = "".join("    if (%d == 1) { }\n" % i for i in range(200))
        self.assertFails("int main() {\n" + body + "    return 0;\n}\n", "symbols; as holds 220")

    def test_expression_depth_limit(self):
        ok = "int main() { return " + "1+(" * 31 + "1" + ")" * 31 + "; }"
        compile_src(ok)
        too_deep = "int main() { return " + "1+(" * 32 + "1" + ")" * 32 + "; }"
        self.assertFails(too_deep, "too deeply nested")


class Cli(unittest.TestCase):
    def test_usage_and_error_exit_codes(self):
        self.assertEqual(cc.main(["cc.py"]), 2)
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as f:
            f.write("int f() { return 0; }\n")
        try:
            self.assertEqual(cc.main(["cc.py", f.name]), 1)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
