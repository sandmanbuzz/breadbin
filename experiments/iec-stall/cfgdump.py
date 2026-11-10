#!/usr/bin/env python3
"""Read-only dump of the Ultimate's whole configuration, and a diff of two dumps.

  cfgdump.py OUT.json                  dump (needs BREADBIN_ULTIMATE=host[:port]); report non-defaults
  cfgdump.py diff A.json B.json        print the items that differ

Only GET requests are ever made: no PUT, POST or machine/drive command. The JSON is
{category: {item: {"current": v, "default": v}}} sorted, plus "_redacted": [names].

PRIVACY. A category or item is dropped entirely (name listed under "_redacted", never a value) when
its name matches, case-insensitively, any of: the substrings network, ethernet, wifi, wlan, gateway,
netmask, password, ssid, ftp, telnet, http, host, dns, remote, device (as in name-of-device);
or any whole word (split on non-alphanumerics) ip, lan, mac, web, user, name, net; or when a
value looks like an IPv4/IPv6 address or a MAC address. A dropped category takes all its items.
Errs on the side of dropping: "User Interface" goes too.
"""
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

SUBSTR = ("network", "ethernet", "wifi", "wi-fi", "wlan", "gateway", "netmask", "password", "ssid",
          "ftp", "telnet", "http", "host", "dns", "remote", "device")
WORDS = {"ip", "lan", "mac", "web", "user", "name", "net"}
IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
MAC = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}(?![0-9a-f])")
IPV6 = re.compile(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])")


def name_sensitive(name):
    n = name.lower()
    if any(s in n for s in SUBSTR):
        return True
    return any(w in WORDS for w in re.split(r"[^a-z0-9]+", n))


def value_sensitive(v):
    s = str(v)
    return bool(IPV4.search(s) or MAC.search(s) or IPV6.search(s))


def _cur_def(node):
    if isinstance(node, dict):
        return node.get("current", node.get("value")), node.get("default")
    return node, None


def _q(*parts):
    return "/v1/configs/" + "/".join(urllib.parse.quote(p, safe="") for p in parts)


def dump(u):
    """-> the sanitised dump dict. Uses GET only, through u.call."""
    out, redacted = {}, []
    cats = u.call("GET", "/v1/configs").get("categories", [])
    for cat in sorted(cats):
        if name_sensitive(cat):
            redacted.append(cat)
            continue
        items = u.call("GET", _q(cat)).get(cat, {})
        res = {}
        for item in sorted(items):
            if name_sensitive(item):
                redacted.append(f"{cat}/{item}")
                continue
            cur, dflt = _cur_def(items[item])
            if dflt is None:                      # the category listing lacks it: ask the item
                try:
                    d = u.call("GET", _q(cat, item)).get(cat, {}).get(item, {})
                    c2, dflt = _cur_def(d)
                    cur = cur if cur is not None else c2
                except Exception:                # noqa: BLE001 - a missing default is not fatal
                    pass
            if value_sensitive(cur) or value_sensitive(dflt):
                redacted.append(f"{cat}/{item}")
                continue
            res[item] = {"current": cur, "default": dflt}
        if res:
            out[cat] = res
    out["_redacted"] = sorted(set(redacted))
    return out


def non_defaults(d):
    rows = []
    for cat, items in d.items():
        if cat.startswith("_"):
            continue
        for item, v in items.items():
            if v.get("default") is not None and str(v["current"]) != str(v["default"]):
                rows.append((cat, item, v["current"], v["default"]))
    return sorted(rows)


def diff(a, b):
    rows = []
    for cat in sorted((set(a) | set(b)) - {"_redacted"}):
        for item in sorted(set(a.get(cat, {})) | set(b.get(cat, {}))):
            x = a.get(cat, {}).get(item, {}).get("current", "<absent>")
            y = b.get(cat, {}).get(item, {}).get("current", "<absent>")
            if x != y:
                rows.append((cat, item, x, y))
    return rows


def write_dump(u, path):
    d = dump(u)
    with open(path, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
        f.write("\n")
    return d


def main(argv=None, client=None, out=print):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "diff":
        if len(argv) != 3:
            raise SystemExit("usage: cfgdump.py diff A.json B.json")
        a, b = (json.load(open(p)) for p in argv[1:])
        rows = diff(a, b)
        for cat, item, x, y in rows:
            out(f"{cat}/{item}: {x} -> {y}")
        out(f"{len(rows)} item(s) changed")
        return 0
    if len(argv) != 1:
        raise SystemExit("usage: cfgdump.py OUT.json | diff A.json B.json")
    if client is None:
        from ultimate import Ultimate
        client = Ultimate.from_env()
    d = write_dump(client, argv[0])
    rows = non_defaults(d)
    out(f"{sum(len(v) for k, v in d.items() if not k.startswith('_'))} items dumped, "
        f"{len(d['_redacted'])} redacted, {len(rows)} differ from default")
    for cat, item, cur, dflt in rows:
        out(f"  {cat}/{item}: {cur} (default {dflt})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
