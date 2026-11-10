"""Host tests for experiments/iec-stall/cfgdump.py against the fake Ultimate: full dump, privacy
redaction, GET-only, diff. No hardware."""
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


if __name__ == "__main__":
    unittest.main()
