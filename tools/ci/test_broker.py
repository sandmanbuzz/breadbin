import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import broker  # noqa: E402

LEASE = os.path.join(HERE, "lease")


class BrokerThread:
    def __init__(self, addr):
        import asyncio
        self.addr = addr
        self.loop = asyncio.new_event_loop()
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import asyncio
        asyncio.set_event_loop(self.loop)
        self.task = self.loop.create_task(broker.serve(self.addr))
        try:
            self.loop.run_until_complete(self.task)
        except BaseException:
            pass

    def start(self):
        self.t.start()
        for _ in range(100):
            try:
                broker.connect(self.addr).close()
                return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("broker did not start")

    def stop(self):
        self.loop.call_soon_threadsafe(self.task.cancel)
        self.t.join(2)


def read_until(s, word, timeout=3):
    s.settimeout(timeout)
    buf = b""
    while word.encode() not in buf:
        buf += s.recv(4096)
    return buf.decode()


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addr = "unix:" + os.path.join(self.d, "b.sock")
        self.b = BrokerThread(self.addr).start()

    def tearDown(self):
        self.b.stop()

    def acquire(self, res, label):
        s = broker.connect(self.addr)
        s.sendall(f"ACQUIRE {res} {label}\n".encode())
        return s

    def test_grant_and_fifo(self):
        a, b, c = self.acquire("vice", "A"), self.acquire("vice", "B"), self.acquire("vice", "C")
        self.assertIn("GRANTED", read_until(a, "GRANTED"))
        self.assertIn("QUEUED 1", read_until(b, "QUEUED"))
        self.assertIn("QUEUED 2", read_until(c, "QUEUED"))
        st = broker.query_status(self.addr)
        self.assertIn("held by 'A'", st)
        self.assertLess(st.index("B"), st.index("C"))
        a.close()
        self.assertIn("GRANTED", read_until(b, "GRANTED"))
        b.close()
        self.assertIn("GRANTED", read_until(c, "GRANTED"))

    def test_resources_independent(self):
        a, b = self.acquire("vice", "A"), self.acquire("ultimate", "B")
        self.assertIn("GRANTED", read_until(a, "GRANTED"))
        self.assertIn("GRANTED", read_until(b, "GRANTED"))

    def test_queued_client_dropping_leaves_queue(self):
        a, b, c = self.acquire("vice", "A"), self.acquire("vice", "B"), self.acquire("vice", "C")
        read_until(a, "GRANTED"); read_until(b, "QUEUED"); read_until(c, "QUEUED")
        b.close()
        time.sleep(0.2)
        a.close()
        self.assertIn("GRANTED", read_until(c, "GRANTED"))

    def test_release_command(self):
        a, b = self.acquire("vice", "A"), self.acquire("vice", "B")
        read_until(a, "GRANTED")
        a.sendall(b"RELEASE\n")
        self.assertIn("GRANTED", read_until(b, "GRANTED"))

    def test_status_empty(self):
        self.assertIn("no resources", broker.query_status(self.addr))

    def run_lease(self, *args, **kw):
        env = dict(os.environ, BREADBIN_BROKER=self.addr)
        env.pop("BREADBIN_LEASE_FALLBACK", None)
        return subprocess.run([sys.executable, LEASE, *args], env=env, capture_output=True, text=True, **kw)

    def test_lease_runs_command_and_exit_code(self):
        r = self.run_lease("-r", "vice", "--", "sh", "-c", "exit 7")
        self.assertEqual(r.returncode, 7)

    def test_lease_timeout(self):
        a = self.acquire("vice", "A")
        read_until(a, "GRANTED")
        r = self.run_lease("-r", "vice", "-t", "1", "--", "true")
        self.assertEqual(r.returncode, 75)
        self.assertIn("timeout", r.stderr)

    def test_lease_released_when_client_killed(self):
        env = dict(os.environ, BREADBIN_BROKER=self.addr)
        p = subprocess.Popen([sys.executable, LEASE, "-r", "vice", "--", "sleep", "30"], env=env)
        time.sleep(0.8)
        self.assertIn("held by", broker.query_status(self.addr))
        p.kill()
        p.wait()
        time.sleep(0.3)
        self.assertNotIn("held by", broker.query_status(self.addr))

    def test_lease_broker_down(self):
        env = dict(os.environ, BREADBIN_BROKER="unix:" + os.path.join(self.d, "nope.sock"))
        env.pop("BREADBIN_LEASE_FALLBACK", None)
        r = subprocess.run([sys.executable, LEASE, "--", "true"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 69)
        self.assertIn("unreachable", r.stderr)


if __name__ == "__main__":
    unittest.main()
