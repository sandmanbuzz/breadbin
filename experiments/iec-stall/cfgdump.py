#!/usr/bin/env python3
"""Read-only dump of the Ultimate's whole configuration, a diff of two dumps, and an import of a
saved configuration file into the same JSON shape.

  cfgdump.py OUT.json                  dump (needs BREADBIN_ULTIMATE=host[:port]); report non-defaults
  cfgdump.py fromcfg IN.cfg OUT.json   convert a configuration file saved by the Ultimate firmware
  cfgdump.py diff A.json B.json        print the items that differ

Only GET requests are ever made: no PUT, POST or machine/drive command. The JSON is
{category: {item: {"current": v, "default": v}}} sorted, plus "_redacted": [names].

The file format of saved configurations is not known: fromcfg takes an INI-like text, with
`[Category Name]` headers and `Item Name=Value` lines (spaces around '=' tolerated, values may
contain '=', CRLF accepted; ';' or '#' start a comment). A file has no defaults, so every default
is null. A null default means unknown: diff never reports it as a difference. Lines that match
none of those patterns are counted under "_unparsed_lines", and their NUMBERS (never their
content, which could be private) are printed to stderr.

PRIVACY. A category or item is dropped entirely (name listed under "_redacted", never a value) when
its name matches, case-insensitively, any of: the substrings network, ethernet, wifi, wlan, gateway,
netmask, password, ssid, ftp, telnet, http, host, dns, remote (a "Device Name" item goes by the whole word "name");
or any whole word (split on non-alphanumerics) ip, lan, mac, web, user, name, net; or when a
value looks like an IPv4/IPv6 address or a MAC address. A dropped category takes all its items.
Errs on the side of dropping: "User Interface" goes too. dump and fromcfg share these checks.
"""
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

SUBSTR = ("network", "ethernet", "wifi", "wi-fi", "wlan", "gateway", "netmask", "password", "ssid",
          "ftp", "telnet", "http", "host", "dns", "remote")
WORDS = {"ip", "lan", "mac", "web", "user", "name", "net"}
IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
MAC = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}(?![0-9a-f])")
IPV6 = re.compile(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])")
HEADER = re.compile(r"^\[([^\[\]]+)\]$")
ITEM = re.compile(r"^([^=]+?)\s*=\s*(.*)$")


def name_sensitive(name):
    n = name.lower()
    if any(s in n for s in SUBSTR):
        return True
    return any(w in WORDS for w in re.split(r"[^a-z0-9]+", n))


def value_sensitive(v):
    s = str(v)
    return bool(IPV4.search(s) or MAC.search(s) or IPV6.search(s))


# The three redaction steps, shared by dump() and fromcfg(). Each records the name and returns True
# when the category or item must be dropped.
def _drop_category(cat, redacted):
    if name_sensitive(cat):
        redacted.append(cat)
        return True
    return False


def _drop_item_name(cat, item, redacted):
    if name_sensitive(item):
        redacted.append(f"{cat}/{item}")
        return True
    return False


def _drop_item_value(cat, item, cur, dflt, redacted):
    if value_sensitive(cur) or value_sensitive(dflt):
        redacted.append(f"{cat}/{item}")
        return True
    return False


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
        if _drop_category(cat, redacted):
            continue
        items = u.call("GET", _q(cat)).get(cat, {})
        res = {}
        for item in sorted(items):
            if _drop_item_name(cat, item, redacted):
                continue
            cur, dflt = _cur_def(items[item])
            if dflt is None:                      # the category listing lacks it: ask the item
                try:
                    d = u.call("GET", _q(cat, item)).get(cat, {}).get(item, {})
                    c2, dflt = _cur_def(d)
                    cur = cur if cur is not None else c2
                except Exception:                # noqa: BLE001 - a missing default is not fatal
                    pass
            if _drop_item_value(cat, item, cur, dflt, redacted):
                continue
            res[item] = {"current": cur, "default": dflt}
        if res:
            out[cat] = res
    out["_redacted"] = sorted(set(redacted))
    return out


def parse_cfg(data):
    """Bytes of a saved configuration -> (items, unparsed line numbers).
    items is {category: {item: value-string}}. Raises SystemExit for binary or header-less input."""
    if b"\0" in data:
        raise SystemExit("cfgdump: input is binary, not a text configuration file")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SystemExit("cfgdump: input is not UTF-8 text, not a configuration file")
    items, unparsed, cat, seen_header = {}, [], None, False
    for n, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r").strip()
        if not line or line[0] in ";#":
            continue
        m = HEADER.match(line)
        if m:
            cat, seen_header = m.group(1).strip(), True
            items.setdefault(cat, {})
            continue
        m = ITEM.match(line)
        if m and m.group(1).strip() and cat is not None:
            items[cat][m.group(1).strip()] = m.group(2).strip()
            continue
        unparsed.append(n)
    if not seen_header:
        raise SystemExit("cfgdump: no [Category] header found, not a configuration file")
    return items, unparsed


def from_cfg(data):
    """Saved configuration bytes -> the dump dict shape, redacted with the same checks as dump()."""
    raw, unparsed = parse_cfg(data)
    out, redacted = {}, []
    for cat in sorted(raw):
        if _drop_category(cat, redacted):
            continue
        res = {}
        for item in sorted(raw[cat]):
            if _drop_item_name(cat, item, redacted):
                continue
            cur, dflt = raw[cat][item], None      # a saved file carries no defaults
            if _drop_item_value(cat, item, cur, dflt, redacted):
                continue
            res[item] = {"current": cur, "default": dflt}
        if res:
            out[cat] = res
    out["_redacted"] = sorted(set(redacted))
    out["_unparsed_lines"] = len(unparsed)
    return out, unparsed


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
    """Rows (category, item, old, new). A null default on either side is unknown: no default row."""
    rows = []
    for cat in sorted(k for k in set(a) | set(b) if not k.startswith("_")):
        for item in sorted(set(a.get(cat, {})) | set(b.get(cat, {}))):
            ea, eb = a.get(cat, {}).get(item, {}), b.get(cat, {}).get(item, {})
            x, y = ea.get("current", "<absent>"), eb.get("current", "<absent>")
            if x != y:
                rows.append((cat, item, x, y))
            da, db = ea.get("default"), eb.get("default")
            if da is not None and db is not None and da != db:
                rows.append((cat, item, f"default {da}", f"default {db}"))
    return rows


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(d, path):
    with open(path, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
        f.write("\n")
    return d


def write_dump(u, path):
    return write_json(dump(u), path)


def main(argv=None, client=None, out=print):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "diff":
        if len(argv) != 3:
            raise SystemExit("usage: cfgdump.py diff A.json B.json")
        a, b = (_load_json(p) for p in argv[1:])
        rows = diff(a, b)
        for cat, item, x, y in rows:
            out(f"{cat}/{item}: {x} -> {y}")
        out(f"{len(rows)} item(s) changed")
        return 0
    if argv and argv[0] == "fromcfg":
        if len(argv) != 3:
            raise SystemExit("usage: cfgdump.py fromcfg IN.cfg OUT.json")
        with open(argv[1], "rb") as f:
            d, unparsed = from_cfg(f.read())
        write_json(d, argv[2])
        if unparsed:
            print(f"cfgdump: {len(unparsed)} unparsed line(s) at line number(s): "
                  f"{', '.join(map(str, unparsed))}", file=sys.stderr)
        out(f"{sum(len(v) for k, v in d.items() if not k.startswith('_'))} items imported, "
            f"{len(d['_redacted'])} redacted, {len(unparsed)} unparsed line(s)")
        return 0
    if len(argv) != 1:
        raise SystemExit("usage: cfgdump.py OUT.json | fromcfg IN.cfg OUT.json | diff A.json B.json")
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
