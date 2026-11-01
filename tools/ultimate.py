#!/usr/bin/env python3
"""Client for the Ultimate's REST API (Ultimate 64, C64 Ultimate, Ultimate-II+).

Standard library only. Written from the firmware documentation
(github.com/GideonZ/1541u-documentation, api/api_calls.rst) and tested against
tools/fake_ultimate.py; NOT yet run against hardware. Things that are unverified
until it is are marked UNVERIFIED.

    u = Ultimate("192.168.1.64", password=None)
    u.info()                          # product, firmware version
    u.readmem(0x0400, 1000)           # DMA read of C64 memory
    u.writemem(0x0277, b"hi")
    u.keyboard(["left_shift", "1"])   # tap SHIFT+1
    u.mount("a", open("build/breadbin.d64", "rb").read(), mode="unlinked")
    u.reset()

Errors: a non-200 status, an unparseable reply, or a non-empty "errors" list in
the JSON reply raises UltimateError.
"""
import http.client
import json
import os
import urllib.parse
import uuid

MAX_EVENTS = 64        # keyboard/joystick events per request
MAX_BODY = 4096        # bytes of JSON per input request
MAX_PUT_WRITE = 128    # bytes writemem accepts on the PUT (hex in the URL) form


class UltimateError(Exception):
    pass


class KeyInjectionUnavailable(UltimateError):
    """This product has no keyboard input over REST (the C64 Ultimate, firmware
    1.1.0, answers 404; the documentation lists it as Ultimate 64 only)."""


def multipart(parts):
    """parts: [(field, filename, bytes)] -> (content_type, body)."""
    boundary = "----breadbin" + uuid.uuid4().hex
    out = []
    for field, filename, data in parts:
        out.append(f"--{boundary}\r\n".encode())
        out.append(
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode())
        out.append(data)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(out)


class Ultimate:
    def __init__(self, host, password=None, port=80, timeout=10, attach="multipart"):
        """attach: how POST uploads are encoded, "multipart" or "raw" (UNVERIFIED:
        the documentation only says the file is 'attached' and mentions a
        Content-Disposition filename, which suggests multipart)."""
        if ":" in host and port == 80:
            host, port = host.rsplit(":", 1)
            port = int(port)
        self.host, self.port, self.timeout = host, port, timeout
        self.password = password
        self.attach = attach

    @classmethod
    def from_env(cls, **kw):
        """BREADBIN_ULTIMATE=host[:port], BREADBIN_ULTIMATE_PASSWORD=..."""
        host = os.environ.get("BREADBIN_ULTIMATE")
        if not host:
            raise UltimateError("set BREADBIN_ULTIMATE=host[:port]")
        return cls(host, password=os.environ.get("BREADBIN_ULTIMATE_PASSWORD"), **kw)

    # ---- transport
    def request(self, method, path, params=None, body=None, content_type=None):
        """-> (status, headers, body bytes). path like "/v1/machine:readmem"."""
        url = path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {}
        if self.password:
            headers["X-Password"] = self.password
        if content_type:
            headers["Content-Type"] = content_type
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request(method, url, body=body, headers=headers)
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        except OSError as e:
            raise UltimateError(f"{method} {url}: {e}") from e
        finally:
            conn.close()

    def call(self, method, path, params=None, body=None, content_type=None):
        """Request that answers with JSON; returns the parsed dict."""
        status, _, data = self.request(method, path, params, body, content_type)
        if status == 403:
            raise UltimateError("403 Forbidden: wrong or missing network password")
        try:
            reply = json.loads(data.decode() or "{}")
        except ValueError:
            raise UltimateError(f"{method} {path}: HTTP {status}, not JSON: {data[:80]!r}")
        if status != 200 or reply.get("errors"):
            raise UltimateError(f"{method} {path}: HTTP {status}: {reply.get('errors')}")
        return reply

    def upload(self, path, data, params=None, filename="upload.bin"):
        if self.attach == "raw":
            return self.call("POST", path, params, data, "application/octet-stream")
        ctype, body = multipart([("file", filename, data)])
        return self.call("POST", path, params, body, ctype)

    # ---- device
    def version(self):
        return self.call("GET", "/v1/version")

    def info(self):
        return self.call("GET", "/v1/info")

    # ---- machine
    def reset(self):
        self.call("PUT", "/v1/machine:reset")

    def reboot(self):
        self.call("PUT", "/v1/machine:reboot")

    def pause(self):
        self.call("PUT", "/v1/machine:pause")

    def resume(self):
        self.call("PUT", "/v1/machine:resume")

    def menu_button(self):
        self.call("PUT", "/v1/machine:menu_button")

    def readmem(self, address, length=256):
        """DMA read of C64 memory (what the CPU currently sees); 1 to 65536 bytes."""
        if not 0 <= address < 0x10000 or length < 1 or address + length > 0x10000:
            raise ValueError("range must lie inside $0000-$FFFF")
        status, _, data = self.request("GET", "/v1/machine:readmem",
                                       {"address": f"{address:04X}", "length": length})
        if status != 200 or len(data) != length:
            raise UltimateError(f"readmem ${address:04X}+{length}: HTTP {status}, {len(data)} bytes")
        return data

    def writemem(self, address, data):
        """DMA write. Up to 128 bytes go in the URL as hex; more as a binary body."""
        data = bytes(data)
        if not data:
            return
        if address < 0 or address + len(data) > 0x10000:
            raise ValueError("range must lie inside $0000-$FFFF")
        if len(data) <= MAX_PUT_WRITE:
            self.call("PUT", "/v1/machine:writemem",
                      {"address": f"{address:04X}", "data": data.hex()})
        else:
            self.call("POST", "/v1/machine:writemem", {"address": f"{address:04X}"},
                      data, "application/octet-stream")

    def menu_screen(self):
        """The firmware menu: (1000 character codes, 1000 colour bytes)."""
        status, _, data = self.request("GET", "/v1/machine:menu_screen")
        if status != 200 or len(data) != 2000:
            raise UltimateError(f"menu_screen: HTTP {status}, {len(data)} bytes")
        return data[:1000], data[1000:]

    # ---- keyboard and joystick (Ultimate 64 only; others answer 501)
    def input(self, events):
        """Send input events, splitting so each request has at most 64 events and
        4096 bytes of JSON. Returns the last reply."""
        reply = None
        batch = []
        for ev in events:
            trial = json.dumps({"events": batch + [ev]}, separators=(",", ":"))
            if batch and (len(batch) + 1 > MAX_EVENTS or len(trial) > MAX_BODY):
                reply = self._send_events(batch)
                batch = []
            batch.append(ev)
        if batch:
            reply = self._send_events(batch)
        return reply

    def _send_events(self, batch):
        body = json.dumps({"events": batch}, separators=(",", ":")).encode()
        try:
            return self.call("POST", "/v1/machine:input", None, body, "application/json")
        except UltimateError as e:
            if "HTTP 404" in str(e) or "HTTP 501" in str(e):
                raise KeyInjectionUnavailable(
                    "this Ultimate has no key injection (machine:input): " + str(e)) from e
            raise

    def keyboard(self, inputs, transition="tap"):
        """tap, press or release the named keys (1 to 8, e.g. ["left_shift", "a"])."""
        return self.input([{"kind": "keyboard", "inputs": list(inputs), "transition": transition}])

    def release_all(self):
        return self.input([{"kind": "release_all"}])

    # ---- programs and disks
    def run_prg(self, prg):
        """Reset, load the PRG by DMA and run it. prg: bytes."""
        return self.upload("/v1/runners:run_prg", prg, filename="prog.prg")

    def load_prg(self, prg):
        return self.upload("/v1/runners:load_prg", prg, filename="prog.prg")

    def run_prg_file(self, path):
        """Same, for a file already on the Ultimate's file system."""
        return self.call("PUT", "/v1/runners:run_prg", {"file": path})

    def drives(self):
        return self.call("GET", "/v1/drives")

    def mount(self, drive, image, type="d64", mode="readwrite", name=None):
        """Mount a disk image. image: bytes (uploaded) or str (a path on the
        Ultimate). mode: readwrite, readonly, or unlinked (writable, but changes
        are not written back to the file: the safe default for tests)."""
        path = f"/v1/drives/{drive}:mount"
        if isinstance(image, str):
            return self.call("PUT", path, {"image": image, "type": type, "mode": mode})
        return self.upload(path, image, {"type": type, "mode": mode},
                           filename=name or f"disk.{type}")

    def remove(self, drive):
        return self.call("PUT", f"/v1/drives/{drive}:remove")

    def drive_reset(self, drive):
        return self.call("PUT", f"/v1/drives/{drive}:reset")

    def set_drive_mode(self, drive, mode):
        """mode: 1541, 1571 or 1581 (also loads that drive's ROM)."""
        return self.call("PUT", f"/v1/drives/{drive}:set_mode", {"mode": mode})

    # ---- video (Ultimate 64): the C64 screen as a UDP stream to ip[:port]
    def stream_start(self, name, ip):
        return self.call("PUT", f"/v1/streams/{name}:start", {"ip": ip})

    def stream_stop(self, name):
        return self.call("PUT", f"/v1/streams/{name}:stop")


if __name__ == "__main__":
    import sys
    u = Ultimate.from_env()
    print(json.dumps(u.info(), indent=2))
    if len(sys.argv) > 1 and sys.argv[1] == "screen":
        mem = u.readmem(0x0400, 1000)
        for r in range(25):
            print("".join(chr(c) if 32 <= c < 127 else "." for c in mem[r * 40:(r + 1) * 40]))
