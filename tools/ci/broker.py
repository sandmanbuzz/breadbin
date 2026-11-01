#!/usr/bin/env python3
"""Tiny lease broker: named resources, FIFO queue, lease dies with the connection.

  broker.py [--listen HOST:PORT | --listen unix:/path]     (default 127.0.0.1:7077)
  broker.py status [--addr ADDR]                            print holders and queues

Protocol (one line each way, UTF-8, over one connection that the client keeps open):
  client: ACQUIRE <resource> <label...>   -> server: QUEUED <pos> (0 or more, as the
                                             queue moves), then GRANTED
  client: STATUS                          -> server: text, then a line "END"
  The lease is held until the client closes the connection (or sends RELEASE).
State is in memory only: a broker restart drops every lease and queue entry, and
clients must re-request. Stdlib only.
"""
import asyncio
import os
import sys
import time
from collections import deque

DEFAULT_ADDR = "127.0.0.1:7077"


class Waiter:
    def __init__(self, writer, label):
        self.writer, self.label, self.since = writer, label, time.time()


class Broker:
    def __init__(self):
        self.holder = {}                # resource -> Waiter
        self.queue = {}                 # resource -> deque[Waiter]

    def _send(self, w, text):
        try:
            w.writer.write((text + "\n").encode())
        except Exception:
            pass

    def acquire(self, res, w):
        q = self.queue.setdefault(res, deque())
        q.append(w)
        self._advance(res)
        if w in q:
            self._send(w, f"QUEUED {list(q).index(w) + 1}")

    def drop(self, w):
        """Connection gone or RELEASE: forget w wherever it is."""
        for res in list(set(self.holder) | set(self.queue)):
            q = self.queue.get(res, deque())
            changed = False
            if w in q:
                q.remove(w)
                changed = True
            if self.holder.get(res) is w:
                del self.holder[res]
                changed = True
            if changed:
                self._advance(res)
                for i, x in enumerate(q):
                    self._send(x, f"QUEUED {i + 1}")

    def _advance(self, res):
        q = self.queue.get(res)
        if res not in self.holder and q:
            w = q.popleft()
            self.holder[res] = w
            w.since = time.time()
            self._send(w, "GRANTED")

    def status(self):
        lines = []
        now = time.time()
        for res in sorted(set(self.holder) | set(self.queue)):
            h = self.holder.get(res)
            lines.append(f"{res}: " + (f"held by '{h.label}' for {now - h.since:.0f}s" if h else "free"))
            for i, w in enumerate(self.queue.get(res, ())):
                lines.append(f"  {i + 1}. {w.label} (waiting {now - w.since:.0f}s)")
        return "\n".join(lines) if lines else "(no resources in use)"

    async def handle(self, reader, writer):
        w = Waiter(writer, "?")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                parts = line.decode(errors="replace").split()
                if not parts:
                    continue
                cmd = parts[0].upper()
                if cmd == "ACQUIRE" and len(parts) >= 2:
                    w.label = " ".join(parts[2:]) or "unlabelled"
                    self.acquire(parts[1], w)
                elif cmd == "STATUS":
                    writer.write((self.status() + "\nEND\n").encode())
                    await writer.drain()
                elif cmd == "RELEASE":
                    self.drop(w)
                else:
                    writer.write(b"ERROR unknown command\n")
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.drop(w)
            writer.close()


async def serve(addr):
    b = Broker()
    if addr.startswith("unix:"):
        path = addr[5:]
        if os.path.exists(path):
            os.unlink(path)
        srv = await asyncio.start_unix_server(b.handle, path)
    else:
        host, _, port = addr.rpartition(":")
        srv = await asyncio.start_server(b.handle, host or "127.0.0.1", int(port))
    print(f"broker listening on {addr}", flush=True)
    async with srv:
        await srv.serve_forever()


def query_status(addr):
    import socket
    s = connect(addr)
    s.sendall(b"STATUS\n")
    data = b""
    while not data.endswith(b"END\n"):
        c = s.recv(4096)
        if not c:
            break
        data += c
    return data.decode().rsplit("END", 1)[0].rstrip("\n")


def connect(addr, timeout=5):
    import socket
    if addr.startswith("unix:"):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(timeout)
        s.connect(addr[5:])
    else:
        host, _, port = addr.rpartition(":")
        s = socket.create_connection((host or "127.0.0.1", int(port)), timeout=timeout)
    s.settimeout(None)
    return s


def main(argv):
    addr = os.environ.get("BREADBIN_BROKER", DEFAULT_ADDR)
    args = list(argv)
    status = bool(args and args[0] == "status")
    if status:
        args.pop(0)
    while args:
        a = args.pop(0)
        if a in ("--listen", "--addr") and args:
            addr = args.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if status:
        try:
            print(query_status(addr))
        except OSError as e:
            print(f"broker: cannot reach {addr}: {e}", file=sys.stderr)
            return 69
        return 0
    try:
        asyncio.run(serve(addr))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
