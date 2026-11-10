"""Host tests for experiments/iec-stall/cfgdump.py against the fake Ultimate: full dump, privacy
redaction, GET-only, diff. No hardware."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "experiments", "iec-stall"))

import cfgdump  # noqa: E402
import fake_ultimate  # noqa: E402
from ultimate import Ultimate  # noqa: E402


def make_fake():
    f = fake_ultimate.FakeUltimate().start()
    f.configs.update({
        ("Drive A Settings", "Drive Type"): "1541",
        ("Drive A Settings", "Drive Bus ID"): "9",
        ("Drive A Settings", "Drive Host IP"): "pending",          # item name has ip word and host
        ("Drive A Settings", "Sneaky"): "192.168.7.20",           # value looks like an IP
        ("Drive A Settings", "Wire"): "de:ad:be:ef:00:01",        # value looks like a MAC
        ("Audio", "Volume"): "5",
        ("Network Settings", "Static IP"): "10.1.2.3",
        ("Network Settings", "Gateway"): "10.1.2.1",
        ("Cartridge", "REU Size"): "2 MB",
    })
    f.config_defaults.update({("Drive A Settings", "Drive Type"): "1541",
                              ("Drive A Settings", "Drive Bus ID"): "8",
                              ("Audio", "Volume"): "5",
                              ("Cartridge", "REU Size"): "None"})
    return f


class CfgDump(unittest.TestCase):
    def setUp(self):
        self.fake = make_fake()
        self.addCleanup(self.fake.stop)
        self.u = Ultimate(self.fake.host, port=self.fake.port)
        self.tmp = tempfile.mkdtemp()

    def run_dump(self, name="a.json"):
        path = os.path.join(self.tmp, name)
        lines = []
        cfgdump.main([path], client=self.u, out=lines.append)
        return path, lines

    def test_full_dump_and_non_defaults(self):
        path, lines = self.run_dump()
        d = json.load(open(path))
        self.assertEqual(d["Audio"]["Volume"], {"current": "5", "default": "5"})
        self.assertEqual(d["Drive A Settings"]["Drive Bus ID"], {"current": "9", "default": "8"})
        self.assertEqual(d["Cartridge"]["REU Size"]["current"], "2 MB")
        report = "\n".join(lines)
        self.assertIn("Drive A Settings/Drive Bus ID: 9 (default 8)", report)
        self.assertIn("Cartridge/REU Size: 2 MB (default None)", report)
        self.assertNotIn("Audio/Volume", report)
        self.assertEqual(list(d), sorted(d))

    def test_network_and_ip_like_values_are_redacted(self):
        path, _ = self.run_dump()
        text = open(path).read()
        d = json.loads(text)
        body = text.split('"_redacted"')[0]       # values and kept names; _redacted lists names only
        for secret in ("10.1.2.3", "10.1.2.1", "192.168.7.20", "de:ad:be:ef:00:01", "Static IP",
                       "Gateway", "pending"):
            self.assertNotIn(secret, body)
        self.assertNotIn("Network Settings", [k for k in d if k != "_redacted"])
        self.assertEqual(d["_redacted"], ["Drive A Settings/Drive Host IP", "Drive A Settings/Sneaky",
                                          "Drive A Settings/Wire", "Network Settings"])
        for v in ("10.1.2.3", "192.168.7.20", "de:ad:be:ef:00:01", "pending"):
            self.assertNotIn(v, text)

    def test_matchers(self):
        for n in ("Network Settings", "WiFi", "Ethernet", "Telnet Server", "FTP", "Web Remote",
                  "Hostname", "DNS", "User Interface", "Device Name", "SSID", "MAC Address", "LAN"):
            self.assertTrue(cfgdump.name_sensitive(n), n)
        for n in ("Drive Type", "Volume", "REU Size", "Clock", "Skip", "Balance"):
            self.assertFalse(cfgdump.name_sensitive(n), n)
        for v in ("1.2.3.4", "fe80::1", "AA-BB-CC-DD-EE-FF", "::1"):
            self.assertTrue(cfgdump.value_sensitive(v), v)
        for v in ("1541", "2 MB", "1.2", "12:30"):
            self.assertFalse(cfgdump.value_sensitive(v), v)

    def test_only_gets(self):
        self.run_dump()
        self.assertTrue(self.fake.requests)
        self.assertEqual({m for m, _ in self.fake.requests}, {"GET"})
        self.assertTrue(all(p.startswith("/v1/configs") for _, p in self.fake.requests))
        self.assertEqual(self.fake.config_puts, [])
        self.assertEqual(self.fake.resets, 0)

    def test_diff(self):
        a, _ = self.run_dump("a.json")
        self.fake.configs[("Audio", "Volume")] = "7"
        self.fake.configs[("Audio", "New")] = "x"
        b, _ = self.run_dump("b.json")
        lines = []
        cfgdump.main(["diff", a, b], out=lines.append)
        self.assertEqual(lines, ["Audio/New: <absent> -> x", "Audio/Volume: 5 -> 7",
                                 "2 item(s) changed"])


# A saved configuration: CRLF, comment and blank lines, spaces around '=', a value containing '=',
# a network category with an IP-looking item, an IP-looking value, and one garbage line (line 6).
SAMPLE_CFG = [
    "; saved by the firmware",          # 1
    "[Drive A Settings]",               # 2
    "Drive Type=1541",                  # 3
    "Drive Bus ID = 8",                 # 4
    "Odd Value=a=b=c",                  # 5
    "this line is not a config line",   # 6  garbage: must be counted, number printed, content not
    "",                                 # 7
    "# another comment",                # 8
    "[Network Settings]",               # 9
    "Static IP=10.1.2.3",               # 10
    "Gateway=10.1.2.1",                 # 11
    "[Audio]",                          # 12
    "Volume=5",                         # 13
    "Sneaky=192.168.7.20",              # 14
    "[Cartridge]",                      # 15
    "REU Size=2 MB",                    # 16
]


class FromCfg(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "saved.cfg")
        with open(self.cfg, "wb") as f:
            f.write(("\r\n".join(SAMPLE_CFG) + "\r\n").encode("utf-8"))
        self.out = os.path.join(self.tmp, "saved.json")

    def convert(self):
        lines, err = [], io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cfgdump.main(["fromcfg", self.cfg, self.out], out=lines.append)
        self.assertEqual(rc, 0)
        with open(self.out) as f:
            return json.load(f), lines, err.getvalue()

    def test_redaction_unparsed_count_and_shape(self):
        d, _, err = self.convert()
        self.assertEqual(d["_redacted"], ["Audio/Sneaky", "Network Settings"])
        self.assertEqual(d["_unparsed_lines"], 1)
        self.assertNotIn("Network Settings", d)
        self.assertIn("Volume", d["Audio"])
        self.assertNotIn("Sneaky", d["Audio"])
        self.assertNotIn("garbage", err)
        self.assertNotIn("this line", err)
        with open(self.out) as f:
            text = f.read()
        for secret in ("10.1.2.3", "10.1.2.1", "192.168.7.20", "Static IP", "Gateway"):
            self.assertNotIn(secret, text)
        self.assertNotIn("Network Settings", [k for k in d if k != "_redacted"])

    def test_values_and_parsing(self):
        d, _, _ = self.convert()
        self.assertEqual(d["Drive A Settings"]["Odd Value"], {"current": "a=b=c", "default": None})
        self.assertEqual(d["Drive A Settings"]["Drive Bus ID"], {"current": "8", "default": None})
        self.assertEqual(d["Drive A Settings"]["Drive Type"]["current"], "1541")
        self.assertEqual(d["Audio"], {"Volume": {"current": "5", "default": None}})
        self.assertEqual(d["Cartridge"]["REU Size"]["current"], "2 MB")
        for cat, items in d.items():
            if cat.startswith("_"):
                continue
            for item, v in items.items():
                self.assertIsNone(v["default"], item)
                self.assertNotIn("\r", v["current"])
                self.assertNotIn("\n", v["current"])
        self.assertEqual(list(d), sorted(d))

    def test_unparsed_lines_are_numbered_not_quoted_and_comments_are_not_counted(self):
        _, _, err = self.convert()
        self.assertEqual(err.strip(), "cfgdump: 1 unparsed line(s) at line number(s): 6")

    def test_binary_input_exits_nonzero(self):
        with open(self.cfg, "wb") as f:
            f.write(b"[Audio]\nVolume=5\x00\x01\xff")
        with self.assertRaises(SystemExit) as cm:
            cfgdump.main(["fromcfg", self.cfg, self.out], out=lambda s: None)
        self.assertIn("binary", str(cm.exception.code))
        self.assertFalse(os.path.exists(self.out))

    def test_non_utf8_input_exits_nonzero(self):
        with open(self.cfg, "wb") as f:
            f.write(b"[Audio]\nVolume=\xff\xfe\n")
        with self.assertRaises(SystemExit) as cm:
            cfgdump.main(["fromcfg", self.cfg, self.out], out=lambda s: None)
        self.assertIn("UTF-8", str(cm.exception.code))

    def test_no_header_exits_nonzero(self):
        with open(self.cfg, "wb") as f:
            f.write(b"Volume=5\nDrive Type=1541\n")
        with self.assertRaises(SystemExit) as cm:
            cfgdump.main(["fromcfg", self.cfg, self.out], out=lambda s: None)
        self.assertIn("no [Category] header", str(cm.exception.code))
        self.assertFalse(os.path.exists(self.out))

    def test_diff_saved_file_against_live_dump(self):
        # Live dump: Bus ID 9 (default 8), Volume 5, REU 2 MB, plus redacted network/IP items.
        dump_path = os.path.join(self.tmp, "live.json")
        self.convert()
        fake = make_fake()
        self.addCleanup(fake.stop)
        cfgdump.write_dump(Ultimate(fake.host, port=fake.port), dump_path)
        lines = []
        cfgdump.main(["diff", dump_path, self.out], out=lines.append)
        # Null default in the saved file is unknown: no default row, even though live defaults are set.
        self.assertEqual(lines, ["Drive A Settings/Drive Bus ID: 9 -> 8",
                                 "Drive A Settings/Odd Value: <absent> -> a=b=c",
                                 "2 item(s) changed"])

    def test_diff_null_default_is_unknown_not_a_difference(self):
        a = {"C": {"I": {"current": "1", "default": "1"}}}
        b = {"C": {"I": {"current": "1", "default": None}}}
        self.assertEqual(cfgdump.diff(a, b), [])
        self.assertEqual(cfgdump.diff(b, a), [])
        c = {"C": {"I": {"current": "1", "default": "2"}}}
        self.assertEqual(cfgdump.diff(a, c), [("C", "I", "default 1", "default 2")])


if __name__ == "__main__":
    unittest.main()
