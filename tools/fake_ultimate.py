#!/usr/bin/env python3
"""A fake Ultimate REST server for testing tools/ultimate.py and
tools/ultimatetest.py without hardware.

It implements the endpoints those tools use over a 64 KB byte array that stands
in for C64 memory. It does not emulate a C64: keys it receives are recorded
(`events`), not turned into screen output; tests set up memory themselves.
Written from the documentation, so it shares that documentation's gaps.
"""
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEYS = (["inst_del", "return", "cursor_left_right", "f7", "f1", "f3", "f5", "cursor_up_down",
         "left_shift", "right_shift", "plus", "minus", "period", "colon", "at", "comma",
         "pound", "star", "semicolon", "clr_home", "equals", "arrow_up", "slash",
         "arrow_left", "ctrl", "space", "commodore", "run_stop", "restore"]
        + list("0123456789") + [chr(c) for c in range(ord("a"), ord("z") + 1)])


def parse_multipart(ctype, body):
    m = re.search(r"boundary=(.+)$", ctype)
    if not m:
        return []
    sep = b"--" + m.group(1).encode()
    parts = []
    for chunk in body.split(sep)[1:]:
        if chunk.startswith(b"--"):
            break
        head, _, data = chunk.partition(b"\r\n\r\n")
        data = data[:-2] if data.endswith(b"\r\n") else data
        name = re.search(rb'name="([^"]*)"', head)
        fname = re.search(rb'filename="([^"]*)"', head)
        parts.append((name.group(1).decode() if name else "",
                      fname.group(1).decode() if fname else "", data))
    return parts


class FakeUltimate:
    def __init__(self, password=None, product="Fake Ultimate 64"):
        self.ram = bytearray(65536)
        self.password = password
        self.product = product
        self.events = []        # every input event received, in order
        self.requests = []      # (method, path) of every request
        self.resets = 0
        self.paused = False
        self.lock = threading.Lock()   # a stand-in C64 thread takes it to work: pause waits for it
        self.mounts = []        # dicts: drive, type, mode, size, how, name
        self.runs = []          # dicts: how ("upload" or "file"), size, loaded
        self.streams = {}
        self.menu = bytearray(2000)
        self._server = None

    # ---- lifecycle
    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake._handle(self, "GET")

            def do_PUT(self):
                fake._handle(self, "PUT")

            def do_POST(self):
                fake._handle(self, "POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host, self.port = self._server.server_address
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()

    # ---- helpers for tests
    def poke(self, address, data):
        self.ram[address:address + len(data)] = data

    # ---- request handling
    def _reply(self, h, status, body=b"", ctype="application/json"):
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def _json(self, h, status=200, errors=(), **fields):
        fields["errors"] = list(errors)
        self._reply(h, status, json.dumps(fields).encode())

    def _handle(self, h, method):
        n = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(n) if n else b""
        u = urllib.parse.urlsplit(h.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self.requests.append((method, u.path))
        if self.password is not None and h.headers.get("X-Password") != self.password:
            return self._reply(h, 403, b"{}")
        m = re.match(r"^/v1/([^/:]+)(?:/([^:]*))?(?::(\w+))?$", u.path)
        if not m:
            return self._json(h, 404, ["no such route"])
        route, sub, cmd = m.groups()
        fn = getattr(self, f"_{route}", None)
        if fn is None:
            return self._json(h, 404, [f"unknown route {route}"])
        fn(h, method, sub, cmd, q, body)

    def _version(self, h, method, sub, cmd, q, body):
        self._json(h, version="0.1")

    def _info(self, h, method, sub, cmd, q, body):
        self._json(h, product=self.product, firmware_version="3.14", hostname="fake")

    def _machine(self, h, method, sub, cmd, q, body):
        if cmd in ("reset", "reboot"):
            self.resets += 1
            self.paused = False
            return self._json(h)
        if cmd == "pause":
            with self.lock:
                self.paused = True
            return self._json(h)
        if cmd == "resume":
            with self.lock:
                self.paused = False
            return self._json(h)
        if cmd == "menu_button":
            return self._json(h)
        if cmd == "readmem":
            a, ln = int(q["address"], 16), int(q.get("length", 256))
            if a + ln > 0x10000 or ln < 1:
                return self._json(h, 400, ["bad range"])
            return self._reply(h, 200, bytes(self.ram[a:a + ln]), "application/octet-stream")
        if cmd == "writemem":
            a = int(q["address"], 16)
            if method == "PUT":
                data = bytes.fromhex(q.get("data", ""))
                if len(data) > 128:
                    return self._json(h, 400, ["too many bytes for PUT"])
            else:
                data = body
            if a + len(data) > 0x10000:
                return self._json(h, 400, ["wraps past $FFFF"])
            self.ram[a:a + len(data)] = data
            return self._json(h)
        if cmd == "menu_screen":
            return self._reply(h, 200, bytes(self.menu), "application/octet-stream")
        if cmd == "input":
            if len(body) > 4096:
                return self._json(h, 400, ["JSON body is too large."])
            try:
                events = json.loads(body)["events"]
            except (ValueError, KeyError):
                return self._json(h, 400, ["bad JSON"])
            if not 1 <= len(events) <= 64:
                return self._json(h, 400, ["1 to 64 events"])
            for ev in events:
                if ev.get("kind") == "keyboard":
                    ins = ev.get("inputs", [])
                    if not 1 <= len(ins) <= 8 or any(i not in KEYS for i in ins):
                        return self._json(h, 400, [f"bad keyboard inputs {ins}"])
                    if ev.get("transition") not in ("press", "release", "tap"):
                        return self._json(h, 400, ["bad transition"])
                elif ev.get("kind") != "release_all":
                    return self._json(h, 400, ["unknown event kind"])
            self.events.extend(events)
            return self._json(h, keyboard={"inputs": []}, joysticks=[])
        self._json(h, 404, [f"unknown machine command {cmd}"])

    def _attachment(self, h, body):
        ctype = h.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            parts = parse_multipart(ctype, body)
            return ("multipart", parts[0][1], parts[0][2]) if parts else ("multipart", "", b"")
        return ("raw", "", body)

    def _runners(self, h, method, sub, cmd, q, body):
        if cmd not in ("run_prg", "load_prg"):
            return self._json(h, 404, ["unknown runner"])
        if method == "PUT":
            self.runs.append({"cmd": cmd, "how": "file", "file": q.get("file")})
        else:
            how, _, data = self._attachment(h, body)
            if len(data) >= 2:
                load = data[0] | data[1] << 8
                self.ram[load:load + len(data) - 2] = data[2:]
            else:
                load = None
            self.runs.append({"cmd": cmd, "how": how, "size": len(data), "loaded": load})
        self.resets += 1
        self._json(h)

    def _drives(self, h, method, sub, cmd, q, body):
        if cmd is None and method == "GET":
            return self._json(h, drives=[{"a": {"enabled": True, "bus_id": 8, "type": "1541"}}])
        if cmd == "mount":
            if method == "PUT":
                rec = {"drive": sub, "how": "file", "image": q.get("image")}
            else:
                how, name, data = self._attachment(h, body)
                rec = {"drive": sub, "how": how, "name": name, "size": len(data), "data": data}
            rec.update(type=q.get("type"), mode=q.get("mode"))
            self.mounts.append(rec)
            return self._json(h)
        if cmd in ("remove", "reset", "on", "off", "set_mode"):
            return self._json(h)
        self._json(h, 404, [f"unknown drive command {cmd}"])

    def _streams(self, h, method, sub, cmd, q, body):
        if cmd == "start":
            self.streams[sub] = q.get("ip")
        elif cmd == "stop":
            self.streams.pop(sub, None)
        self._json(h)


if __name__ == "__main__":
    with FakeUltimate() as f:
        print(f"fake Ultimate on {f.host}:{f.port}; Ctrl-C to stop")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
