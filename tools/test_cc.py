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
    return [t for t in re.findall(r"^\s+(?:jmp|beq|bne|bcc|bcs)\s+(\S+)", text, re.M)
            if not t.startswith("sys_")]


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
        want = "s_1: .byte 104, 101, 108, 108, 111, 44, 32, 119, 111, 114, 108, 100, 33, 10, 0\n"
        self.assertIn(want, out)

    def test_puts_goes_through_the_runtime_and_sys_write(self):
        out = compile_src(HELLO)
        self.assertIn("        lda #<s_1\n        sta cc_ptr\n        lda #>s_1\n        sta cc_ptr+1\n"
                      "        jsr rt_puts\n", out)
        self.assertIn("rt_puts:", out)
        self.assertIn("        lda (cc_ptr),y\n", out)
        self.assertIn("        jsr sys_write\n", out)

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

    def test_string_outside_puts(self):
        self.assertFails('int main() { return "x"; }', "only an argument to puts")

    def test_puts_needs_one_literal(self):
        self.assertFails("int main() { puts(3); return 0; }", "puts takes one string literal")

    def test_parameters_are_refused(self):
        self.assertFails("int f(int a) { return a; }\nint main() { return 0; }", "parameters are not in this slice")

    def test_arguments_are_refused(self):
        self.assertFails("int f() { return 0; }\nint main() { return f(1); }", "arguments are not in this slice")

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
        self.assertFails("int main() { int abcdefghijklmnop; return 0; }", "longer than 15 characters")

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
