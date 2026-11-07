"""Tests for tools/claude-quota against a local mock of the usage endpoint (http.server in a
thread). Never touches the real endpoint, credentials or keychain: every run gets a fake token, a
loopback base URL and a DB under a temp dir."""
import csv
import datetime as dt
import http.server
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude-quota")
UTC = dt.timezone.utc


def iso(t):
    return t.astimezone(UTC).isoformat(timespec="seconds")


class Mock(http.server.BaseHTTPRequestHandler):
    status = 200
    body = "{}"

    def do_GET(self):
        data = type(self).body.encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class QuotaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), Mock)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(lambda: self.tmp.cleanup())
        self.newdb()
        self.env = dict(
            os.environ, CLAUDE_QUOTA_TOKEN="fake-token", CLAUDE_QUOTA_DB=self.db,
            CLAUDE_QUOTA_BASE_URL="http://127.0.0.1:%d" % self.srv.server_address[1],
            CLAUDE_CREDENTIALS=os.path.join(self.tmp.name, "no-such-credentials"))
        self.serve(200, {})

    def newdb(self):
        self.n = getattr(self, "n", 0) + 1
        self.dbdir = os.path.join(self.tmp.name, "sub%d" % self.n, "q")
        self.db = os.path.join(self.dbdir, "quota.db")
        if hasattr(self, "env"):
            self.env["CLAUDE_QUOTA_DB"] = self.db

    def serve(self, status, body):
        Mock.status = status
        Mock.body = body if isinstance(body, str) else json.dumps(body)

    def run_q(self, *args):
        return subprocess.run([sys.executable, TOOL, *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def rows(self, sql, *a):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, a).fetchall()
        finally:
            con.close()

    def flat(self, five=25.0, week=10.0, reset=None):
        reset = reset or iso(dt.datetime.now(UTC) + dt.timedelta(hours=3))
        return {"five_hour": {"utilization": five, "resets_at": reset},
                "seven_day": {"utilization": week, "resets_at": "2099-01-01T00:00:00Z"}}

    def seed(self, bucket, resets_at, points):
        """Insert one snapshot per (age_hours, utilization), via the real schema."""
        self.assertEqual(self.run_q("mark", "init").returncode, 0)
        con = sqlite3.connect(self.db)
        now = dt.datetime.now(UTC)
        with con:
            for age, u in points:
                t = iso(now - dt.timedelta(hours=age))
                cur = con.execute("INSERT INTO snapshots(first_seen,last_seen,fingerprint,raw)"
                                  " VALUES (?,?,?,?)", (t, t, "x%s" % age, "{}"))
                con.execute("INSERT INTO buckets VALUES (?,?,?,?)", (cur.lastrowid, bucket, u, resets_at))
        con.close()

    def now_burn(self, bucket="five_hour"):
        r = self.run_q("now")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["buckets"][bucket].get("burn")


class Fetch(QuotaCase):
    def test_flat_keys(self):
        self.serve(200, self.flat())
        r = self.run_q("now")
        self.assertEqual(r.returncode, 0, r.stderr)
        b = json.loads(r.stdout)["buckets"]
        self.assertEqual(b["five_hour"]["utilization"], 25.0)
        self.assertEqual(b["five_hour"]["remaining"], 75.0)
        self.assertEqual(b["seven_day"]["resets_at"], "2099-01-01T00:00:00+00:00")

    def test_limits_array(self):
        self.serve(200, {"limits": [
            {"name": "weekly", "utilization": 40, "resets_at": "2099-01-01T00:00:00Z",
             "scope": {"model": {"display_name": "Opus"}}},
            {"window": "five_hour", "used_percentage": 5, "resets_at": 4070908800}]})
        b = json.loads(self.run_q("now").stdout)["buckets"]
        self.assertEqual(b["weekly_opus"]["utilization"], 40.0)
        self.assertEqual(b["five_hour"]["utilization"], 5.0)
        self.assertEqual(b["five_hour"]["resets_at"], "2099-01-01T00:00:00+00:00")

    def test_extra_usage(self):
        p = self.flat()
        p["extra_usage"] = {"is_enabled": True, "utilization": 12.5, "used_credits": 3,
                            "monthly_limit": 100}
        self.serve(200, p)
        b = json.loads(self.run_q("now").stdout)["buckets"]["extra_usage"]
        self.assertEqual((b["utilization"], b["used_credits"], b["monthly_limit"]), (12.5, 3.0, 100.0))
        p["extra_usage"]["is_enabled"] = False
        self.serve(200, p)
        self.assertNotIn("extra_usage", json.loads(self.run_q("now").stdout)["buckets"])

    def test_exit_codes(self):
        for status, code in ((401, 2), (403, 2), (500, 3)):
            self.serve(status, {})
            r = self.run_q("now")
            self.assertEqual(r.returncode, code, status)
            self.assertEqual(json.loads(r.stderr)["exit_code"], code)
        self.serve(200, "<html>not json")
        self.assertEqual(self.run_q("now").returncode, 4)
        self.serve(200, {"nothing": "useful"})
        self.assertEqual(self.run_q("now").returncode, 4)

    def test_network_error_is_3(self):
        self.env["CLAUDE_QUOTA_BASE_URL"] = "http://127.0.0.1:1"
        self.assertEqual(self.run_q("now").returncode, 3)

    def test_missing_token_is_2(self):
        # no token and no credentials file (CLAUDE_CREDENTIALS points nowhere): exit 2
        del self.env["CLAUDE_QUOTA_TOKEN"]
        r = self.run_q("now")
        self.assertEqual(r.returncode, 2, r.stderr)


class Storage(QuotaCase):
    def test_poll_adds_row_only_on_change(self):
        self.serve(200, self.flat(five=25))
        self.assertEqual(json.loads(self.run_q("poll").stdout)["changed"], True)
        self.assertEqual(json.loads(self.run_q("poll").stdout)["changed"], False)
        self.assertEqual(len(self.rows("SELECT id FROM snapshots")), 1)
        first, last = self.rows("SELECT first_seen, last_seen FROM snapshots")[0]
        self.assertGreaterEqual(last, first)
        self.serve(200, self.flat(five=26))
        self.assertEqual(json.loads(self.run_q("poll").stdout)["changed"], True)
        self.assertEqual(len(self.rows("SELECT id FROM snapshots")), 2)

    def test_poll_quiet_and_failure_logged(self):
        self.serve(200, self.flat())
        r = self.run_q("poll", "--quiet")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.serve(500, {})
        self.assertEqual(self.run_q("poll", "--quiet").returncode, 3)
        self.assertEqual(self.rows("SELECT count(*) FROM polls WHERE ok=0")[0][0], 1)

    def test_now_without_record_creates_no_db(self):
        self.serve(200, self.flat())
        r = self.run_q("now")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.db))
        self.assertFalse(os.path.exists(self.dbdir))
        self.assertIn("note", json.loads(r.stdout)["buckets"]["five_hour"]["burn"])

    def test_now_without_record_does_not_write_existing_db(self):
        self.serve(200, self.flat())
        self.assertEqual(self.run_q("poll", "--quiet").returncode, 0)
        q = ("SELECT (SELECT count(*) FROM snapshots), (SELECT count(*) FROM polls),"
             " (SELECT max(last_seen) FROM snapshots)")
        before = self.rows(q)
        self.assertEqual(self.run_q("now").returncode, 0)
        self.assertEqual(before, self.rows(q))

    def test_now_record_stores(self):
        self.serve(200, self.flat())
        self.assertEqual(json.loads(self.run_q("now", "--record").stdout)["recorded"], True)
        self.assertEqual(json.loads(self.run_q("now", "--record").stdout)["recorded"], False)

    def test_permissions(self):
        self.serve(200, self.flat())
        self.assertEqual(self.run_q("poll", "--quiet").returncode, 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.db).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.dbdir).st_mode), 0o700)
        for ext in ("-wal", "-shm"):
            if os.path.exists(self.db + ext):
                self.assertEqual(stat.S_IMODE(os.stat(self.db + ext).st_mode) & 0o077, 0)

    def test_mark_creates_db_0600(self):
        self.assertEqual(self.run_q("mark", "hello").returncode, 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.db).st_mode), 0o600)

    def test_mark_and_history_interleave(self):
        self.serve(200, self.flat(five=25))
        self.run_q("poll", "--quiet")
        self.assertEqual(self.run_q("mark", "start: sprint, with comma", "--tag", "swarm").returncode, 0)
        self.serve(200, self.flat(five=30))
        self.run_q("poll", "--quiet")
        r = self.run_q("history", "--since", "1h", "--format", "csv")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = list(csv.reader(io.StringIO(r.stdout)))
        self.assertEqual(rows[0][0], "kind")
        marks = [x for x in rows[1:] if x[0] == "mark"]
        self.assertEqual(len(marks), 1)
        self.assertEqual((marks[0][6], marks[0][7]), ("swarm", "start: sprint, with comma"))
        self.assertEqual(len([x for x in rows[1:] if x[0] == "usage"]), 4)  # 2 snapshots x 2 buckets
        j = json.loads(self.run_q("history", "--bucket", "five_hour").stdout)
        self.assertEqual([u["utilization"] for u in j["usage"]], [25.0, 30.0])
        self.assertEqual(len(j["marks"]), 1)
        self.assertEqual(self.run_q("history", "--since", "garbage").returncode, 4)


class Burn(QuotaCase):
    def reset_in(self, hours):
        return iso(dt.datetime.now(UTC) + dt.timedelta(hours=hours))

    def test_no_history_note(self):
        self.serve(200, self.flat())
        self.assertEqual(self.run_q("now", "--record").returncode, 0)
        self.assertIn("note", self.now_burn())

    def test_will_cap_true(self):
        reset = self.reset_in(10)
        self.seed("five_hour", reset, [(2, 40), (1, 50)])
        self.serve(200, self.flat(five=60, reset=reset))
        b = self.now_burn()
        self.assertAlmostEqual(b["rate_pct_per_hour"], 10, delta=0.5)
        self.assertAlmostEqual(b["hours_until_cap"], 4, delta=0.3)
        self.assertAlmostEqual(b["projected_at_reset"], 160, delta=6)
        self.assertIs(b["will_cap_before_reset"], True)

    def test_will_cap_false(self):
        reset = self.reset_in(2)
        self.seed("five_hour", reset, [(2, 40), (1, 50)])
        self.serve(200, self.flat(five=60, reset=reset))
        b = self.now_burn()
        self.assertAlmostEqual(b["rate_pct_per_hour"], 10, delta=0.5)
        self.assertAlmostEqual(b["projected_at_reset"], 80, delta=2)
        self.assertIs(b["will_cap_before_reset"], False)

    def test_flat_usage_never_caps(self):
        reset = self.reset_in(2)
        self.seed("five_hour", reset, [(2, 60), (1, 60)])
        self.serve(200, self.flat(five=60, reset=reset))
        b = self.now_burn()
        self.assertIsNone(b["hours_until_cap"])
        self.assertIs(b["will_cap_before_reset"], False)

    def test_other_window_excluded(self):
        # rows from the previous window (90% used) must not pollute the fit
        reset = self.reset_in(10)
        old = iso(dt.datetime.now(UTC) - dt.timedelta(hours=20))
        self.seed("five_hour", old, [(4, 90), (3, 95)])
        con = sqlite3.connect(self.db)
        now = dt.datetime.now(UTC)
        with con:
            for age, u in [(2, 40), (1, 50)]:
                t = iso(now - dt.timedelta(hours=age))
                cur = con.execute("INSERT INTO snapshots(first_seen,last_seen,fingerprint,raw)"
                                  " VALUES (?,?,?,?)", (t, t, "y%s" % age, "{}"))
                con.execute("INSERT INTO buckets VALUES (?,?,?,?)", (cur.lastrowid, "five_hour", u, reset))
        con.close()
        self.serve(200, self.flat(five=60, reset=reset))
        self.assertAlmostEqual(self.now_burn()["rate_pct_per_hour"], 10, delta=0.5)

    def test_resets_at_jitter_within_120s_matches(self):
        reset = dt.datetime.now(UTC) + dt.timedelta(hours=10)
        for jit in (-100, 100):
            with self.subTest(jit=jit):
                self.newdb()
                self.seed("five_hour", iso(reset + dt.timedelta(seconds=jit)), [(2, 40), (1, 50)])
                self.serve(200, self.flat(five=60, reset=iso(reset)))
                self.assertAlmostEqual(self.now_burn()["rate_pct_per_hour"], 10, delta=0.5)

    def test_resets_at_beyond_slop_does_not_match(self):
        reset = dt.datetime.now(UTC) + dt.timedelta(hours=10)
        self.seed("five_hour", iso(reset + dt.timedelta(seconds=150)), [(2, 40), (1, 50)])
        self.serve(200, self.flat(five=60, reset=iso(reset)))
        self.assertIn("note", self.now_burn())


class StatusBase(QuotaCase):
    """`status` reads only the DB: the env has no usable token and a dead base URL."""

    def setUp(self):
        super().setUp()
        self.env["CLAUDE_QUOTA_TOKEN"] = ""
        self.env["CLAUDE_QUOTA_BASE_URL"] = "http://127.0.0.1:1"
        self.now = dt.datetime.now(UTC)

    def build(self, snaps, polls):
        """snaps: (age_h, {bucket: (util, resets_at)}); polls: (age_min, ok, error)."""
        self.assertEqual(self.run_q("mark", "init").returncode, 0)
        con = sqlite3.connect(self.db)
        with con:
            for i, (age, bs) in enumerate(snaps):
                t = iso(self.now - dt.timedelta(hours=age))
                cur = con.execute("INSERT INTO snapshots(first_seen,last_seen,fingerprint,raw)"
                                  " VALUES (?,?,?,?)", (t, t, "f%d" % i, "{}"))
                for b, (u, r) in bs.items():
                    con.execute("INSERT INTO buckets VALUES (?,?,?,?)", (cur.lastrowid, b, u, r))
            for age, ok, err in polls:
                con.execute("INSERT INTO polls VALUES (?,?,?,?)",
                            (iso(self.now - dt.timedelta(minutes=age)), ok, None, err))
        con.close()

    def status(self, *args):
        r = self.run_q("status", *args)
        return r, (json.loads(r.stdout) if r.stdout.strip() else None)

    def reset(self, h=3):
        return iso(self.now + dt.timedelta(hours=h))


class Status(StatusBase):
    def test_fresh(self):
        rs = self.reset()
        self.build([(2, {"five_hour": (40.0, rs)}), (1, {"five_hour": (50.0, rs)}),
                    (0.0, {"five_hour": (60.0, rs)})], [(3, 1, None)])
        r, j = self.status()
        self.assertEqual(r.returncode, 0, r.stderr)
        b = j["buckets"]["five_hour"]
        self.assertEqual((b["utilization"], b["remaining"]), (60.0, 40.0))
        self.assertAlmostEqual(b["burn"]["rate_pct_per_hour"], 10, delta=1)
        self.assertFalse(j["stale"])
        self.assertAlmostEqual(j["last_poll_age_min"], 3, delta=0.5)
        self.assertEqual(j["recent_failures"]["count"], 0)
        self.assertNotIn("window", b)

    def test_stale_exits_6_but_prints(self):
        self.build([(1, {"five_hour": (50.0, self.reset())})], [(20, 1, None)])
        r, j = self.status()
        self.assertEqual(r.returncode, 6)
        self.assertTrue(j["stale"])
        self.assertEqual(j["buckets"]["five_hour"]["utilization"], 50.0)

    def test_stale_boundary(self):
        self.build([(1, {"five_hour": (50.0, self.reset())})], [(14, 1, None)])
        self.assertEqual(self.status()[0].returncode, 0)

    def test_never_polled_ok_is_stale(self):
        self.build([(1, {"five_hour": (50.0, self.reset())})], [(2, 0, "boom")])
        r, j = self.status()
        self.assertEqual(r.returncode, 6)
        self.assertIsNone(j["last_poll_ok"])

    def test_missing_db(self):
        r, j = self.status()
        self.assertEqual((r.returncode, j["exit_code"]), (5, 5))
        self.assertFalse(os.path.exists(self.db), "status must not create the DB")

    def test_empty_db(self):
        self.assertEqual(self.run_q("mark", "init").returncode, 0)
        r, j = self.status()
        self.assertEqual(r.returncode, 5)
        self.assertIn("error", j)

    def test_zero_byte_db(self):
        os.makedirs(self.dbdir)
        open(self.db, "w").close()
        self.assertEqual(self.status()[0].returncode, 5)

    def test_garbage_db(self):
        os.makedirs(self.dbdir)
        with open(self.db, "w") as f:
            f.write("this is not sqlite" * 50)
        self.assertEqual(self.status()[0].returncode, 5)

    def test_failures(self):
        self.build([(1, {"five_hour": (50.0, self.reset())})],
                   [(1, 1, None), (5, 0, "HTTP 500 from usage endpoint"),
                    (10, 0, "older error"), (90, 0, "too old")])
        r, j = self.status()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(j["recent_failures"]["count"], 2)
        self.assertEqual(j["recent_failures"]["last_error"], "HTTP 500 from usage endpoint")

    def test_window_delta(self):
        rs = self.reset()
        self.build([(10, {"five_hour": (5.0, rs)}), (5, {"five_hour": (20.0, rs)}),
                    (0.5, {"five_hour": (50.0, rs)})], [(1, 1, None)])
        r, j = self.status("--window-hours", "4")
        w = j["buckets"]["five_hour"]["window"]
        self.assertEqual((w["delta"], w["from"], w["partial"]), (30.0, 20.0, False))
        self.assertEqual(j["window_hours"], 4)
        w = self.status("--window-hours", "6")[1]["buckets"]["five_hour"]["window"]
        self.assertEqual((w["delta"], w["partial"]), (45.0, False))
        w = self.status("--window-hours", "24")[1]["buckets"]["five_hour"]["window"]
        self.assertEqual((w["delta"], w["partial"]), (45.0, True))

    def test_window_partial_and_reset(self):
        self.build([(2, {"five_hour": (90.0, self.reset(-1))}),
                    (0.5, {"five_hour": (4.0, self.reset(5))})], [(1, 1, None)])
        w = self.status("--window-hours", "48")[1]["buckets"]["five_hour"]["window"]
        self.assertEqual((w["delta"], w["partial"], w["reset_in_window"]), (-86.0, True, True))

    def test_human(self):
        self.build([(1, {"five_hour": (50.0, self.reset())})], [(1, 1, None)])
        r = self.run_q("status", "--human", "--window-hours", "2")
        self.assertEqual(r.returncode, 0)
        self.assertIn("five_hour", r.stdout)
        self.assertIn("last good poll", r.stdout)

    def test_status_does_not_write(self):
        self.build([(1, {"five_hour": (50.0, self.reset())})], [(1, 1, None)])
        before = self.rows("SELECT count(*) FROM polls")
        self.status()
        self.assertEqual(self.rows("SELECT count(*) FROM polls"), before)


class Tier(StatusBase):
    """Rate-driven tier: synthetic histories, controlled timestamps, DB only."""

    def ramp(self, week=(60.0, 0.1), five=(20.0, 0.1), week_h=48, five_h=3, hours=3, step=0.25,
             polls=((3, 1, None), (20, 1, None))):
        """One snapshot every `step` hours over `hours`; each bucket is (util_now, %/h)."""
        rw, rf = self.reset(week_h), self.reset(five_h)
        snaps = []
        n = int(round(hours / step))
        for i in range(n, -1, -1):
            age = i * step
            snaps.append((age, {"seven_day": (round(week[0] - week[1] * age, 3), rw),
                                "five_hour": (round(five[0] - five[1] * age, 3), rf)}))
        self.build(snaps, list(polls))

    def tier(self, *args):
        r, j = self.status(*args)
        self.assertIn(r.returncode, (0, 6), r.stderr)
        return j

    def test_steady_low_is_green(self):
        self.ramp(week=(60.0, 0.1), five=(20.0, 0.3))
        j = self.tier()
        self.assertEqual((j["suggested_tier"], j["tier_now"], j["tier_15m_ago"]), ("G", "G", "G"))
        rt = j["buckets"]["seven_day"]["rate"]
        self.assertEqual(rt["basis"], "1h")
        self.assertAlmostEqual(rt["measured_pct_per_hour"], 0.1, delta=0.02)
        self.assertAlmostEqual(rt["budget_rate_pct_per_hour"], 40 / 48, delta=0.02)
        self.assertAlmostEqual(rt["ratio"], 0.12, delta=0.03)
        self.assertAlmostEqual(rt["floor_headroom_pct"], 37.0)
        self.assertNotIn("floor_headroom_pct", j["buckets"]["five_hour"]["rate"])
        w = rt["windows"]
        self.assertFalse(w["1h"]["partial"])
        self.assertTrue(w["6h"]["partial"])
        self.assertAlmostEqual(w["6h"]["span_hours"], 3, delta=0.05)

    def test_near_budget_is_yellow(self):
        self.ramp(week=(60.0, 0.7))  # budget 0.83%/h: ratio 0.84
        j = self.tier()
        self.assertEqual(j["suggested_tier"], "Y")
        self.assertAlmostEqual(j["buckets"]["seven_day"]["rate"]["ratio"], 0.84, delta=0.05)

    def test_over_budget_is_red(self):
        self.ramp(week=(60.0, 1.5))
        j = self.tier()
        self.assertEqual(j["suggested_tier"], "R")
        self.assertIn("seven_day", j["reason"])
        self.assertIn("cap", j["reason"])

    def test_five_hour_over_budget_is_red(self):
        self.ramp(week=(60.0, 0.1), five=(50.0, 20.0), five_h=3)  # budget 16.7%/h
        self.assertEqual(self.tier()["suggested_tier"], "R")

    def test_negative_rate_is_green(self):
        self.ramp(week=(60.0, -0.5))
        j = self.tier()
        self.assertEqual(j["suggested_tier"], "G")
        self.assertLess(j["buckets"]["seven_day"]["rate"]["ratio"], 0)

    def test_unknown_rate_is_yellow(self):
        self.build([(0.0, {"seven_day": (60.0, self.reset(48)), "five_hour": (20.0, self.reset(3))})],
                   [(1, 1, None)])
        j = self.tier()
        rt = j["buckets"]["seven_day"]["rate"]
        self.assertEqual((j["suggested_tier"], rt["basis"], rt["ratio"]), ("Y", None, None))
        self.assertIsNone(rt["measured_pct_per_hour"])
        self.assertIn("rate unknown", j["reason"])
        self.assertIsNone(j["tier_15m_ago"])  # nothing existed 15 minutes ago

    def test_under_ten_minutes_is_unknown(self):
        rs, rf = self.reset(48), self.reset(3)
        self.build([(0.15, {"seven_day": (59.0, rs), "five_hour": (20.0, rf)}),
                    (0.0, {"seven_day": (60.0, rs), "five_hour": (21.0, rf)})], [(1, 1, None)])
        self.assertIsNone(self.tier()["buckets"]["seven_day"]["rate"]["measured_pct_per_hour"])

    def test_falls_back_to_longer_window(self):
        # one reading 5h ago, then nothing until now: 1h has no span
        rs, rf = self.reset(48), self.reset(3)
        self.build([(5.0, {"seven_day": (55.0, rs), "five_hour": (5.0, rf)}),
                    (0.0, {"seven_day": (60.0, rs), "five_hour": (10.0, rf)})], [(1, 1, None)])
        rt = self.tier()["buckets"]["seven_day"]["rate"]
        self.assertEqual(rt["basis"], "6h")
        self.assertAlmostEqual(rt["measured_pct_per_hour"], 1.0, delta=0.02)

    def test_reset_inside_window(self):
        old, new = self.reset(-1.9), self.reset(4.5)
        snaps = [(3.0, {"five_hour": (90.0, old)}), (2.5, {"five_hour": (95.0, old)}),
                 (2.0, {"five_hour": (96.0, old)})]
        for i in range(6, -1, -1):  # new window from 1.5h ago, +2 points/hour
            snaps.append((i * 0.25, {"five_hour": (2.0 + 2.0 * (6 - i) * 0.25, new)}))
        self.build(snaps, [(1, 1, None)])
        j = self.tier()
        rt = j["buckets"]["five_hour"]["rate"]
        for n in ("6h", "24h"):
            self.assertTrue(rt["windows"][n]["reset_in_window"], n)
            self.assertTrue(rt["windows"][n]["partial"], n)
            self.assertAlmostEqual(rt["windows"][n]["pct_per_hour"], 2.0, delta=0.1)
            self.assertAlmostEqual(rt["windows"][n]["span_hours"], 1.5, delta=0.05)
        self.assertEqual(rt["tier"], "G")  # not the -90 a naive delta would give, nor red

    def test_floor(self):
        for week in (97.0, 99.0, 100.0):
            with self.subTest(week=week):
                self.newdb()
                self.ramp(week=(week, 0.0))
                j = self.tier()
                self.assertEqual(j["suggested_tier"], "FLOOR")
                self.assertIn("soft all-stop: hand to owner", j["reason"])
        self.newdb()
        self.ramp(week=(96.9, 0.0), week_h=100)
        self.assertNotEqual(self.tier()["suggested_tier"], "FLOOR")

    def test_five_hour_90_is_red_whatever_the_rate(self):
        self.ramp(five=(90.0, 0.0))
        j = self.tier()
        self.assertEqual(j["suggested_tier"], "R")
        self.assertIn("five_hour", j["reason"])
        self.newdb()
        self.ramp(five=(100.0, 0.0))
        self.assertEqual(self.tier()["suggested_tier"], "R")
        self.newdb()
        self.ramp(five=(89.0, 0.0))
        self.assertEqual(self.tier()["suggested_tier"], "G")

    def test_stale_poller_forces_yellow(self):
        self.ramp(polls=((20, 1, None),))
        r, j = self.status()
        self.assertEqual(r.returncode, 6)
        self.assertEqual(j["suggested_tier"], "Y")
        self.assertIn("stale", j["reason"])

    def test_stale_does_not_mask_red(self):
        self.ramp(week=(60.0, 1.5), polls=((20, 1, None),))
        self.assertEqual(self.status()[1]["suggested_tier"], "R")

    def test_no_budget_left_or_reset_passed(self):
        self.ramp(five=(100.0, 5.0))
        j = self.tier()
        self.assertEqual(j["suggested_tier"], "R")
        self.assertIsNone(j["buckets"]["five_hour"]["rate"]["ratio"])
        self.newdb()
        self.ramp(five_h=-1)  # reset time already passed: no division by zero or negative hours
        j = self.tier()
        self.assertEqual(j["suggested_tier"], "Y")
        self.assertIsNone(j["buckets"]["five_hour"]["rate"]["budget_rate_pct_per_hour"])

    def test_hysteresis_green_now_red_then(self):
        rs, rf = self.reset(48), self.reset(3)
        ages = [3, 2.5, 2, 1.5, 1.25, 1.1, 1.0, 0.75, 0.5, 0.25, 0.0]
        snaps = [(a, {"seven_day": (58.0 if a >= 1.25 else 60.0, rs),
                      "five_hour": (20.0 - 0.1 * a, rf)}) for a in ages]
        self.build(snaps, [(1, 1, None)])
        j = self.tier()
        self.assertEqual((j["tier_now"], j["tier_15m_ago"], j["suggested_tier"]), ("G", "R", "R"))
        self.assertIn("held", j["reason"])

    def test_step_down_is_immediate(self):
        self.ramp(week=(60.0, 1.5))
        j = self.tier()
        self.assertEqual(j["tier_now"], "R")

    def test_human_lines(self):
        self.ramp(week=(60.0, 0.7))
        r = self.run_q("status", "--human")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tier: Y", r.stdout)
        self.assertIn("budget", r.stdout)
        self.assertIn("ratio", r.stdout)
        self.assertIn("%/h (1h)", r.stdout)

    def test_unknown_human_does_not_crash(self):
        self.build([(0.0, {"seven_day": (60.0, self.reset(48))})], [(1, 1, None)])
        r = self.run_q("status", "--human")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rate unknown", r.stdout)

    def test_no_network_no_write(self):
        self.ramp()
        before = self.rows("SELECT (SELECT count(*) FROM polls),(SELECT count(*) FROM snapshots)")
        self.assertEqual(self.tier()["suggested_tier"], "G")
        self.assertEqual(before, self.rows(
            "SELECT (SELECT count(*) FROM polls),(SELECT count(*) FROM snapshots)"))


class Installer(unittest.TestCase):
    SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "install-quota-timer.sh")
    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        self.marker = os.path.join(self.tmp.name, "systemctl.log")
        stub = os.path.join(self.bin, "systemctl")
        with open(stub, "w") as f:
            f.write('#!/bin/sh\necho "$@" >> "%s"\n' % self.marker)
        os.chmod(stub, 0o755)
        self.env = dict(os.environ, HOME=self.home, PATH=self.bin + os.pathsep + os.environ["PATH"])
        self.env.pop("QUOTA_UNIT_DIR", None)

    def run_sh(self, *args):
        return subprocess.run(["/bin/sh", self.SH, *args], env=self.env, capture_output=True,
                              text=True, timeout=60)

    def test_dry_run_changes_nothing(self):
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DRY RUN", r.stdout)
        self.assertEqual(os.listdir(self.home), [])
        self.assertFalse(os.path.exists(self.marker))
        self.assertIn("ExecStart=/usr/bin/env python3 %s/tools/claude-quota poll --quiet" % self.REPO,
                      r.stdout)
        self.assertIn("OnUnitActiveSec=5min", r.stdout)
        self.assertNotIn("@REPO@", r.stdout)

    def test_uninstall_dry_run_changes_nothing(self):
        r = self.run_sh("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DRY RUN", r.stdout)
        self.assertFalse(os.path.exists(self.marker))

    def test_yes_installs_and_uninstalls(self):
        d = os.path.join(self.home, ".config", "systemd", "user")
        self.assertEqual(self.run_sh("--yes").returncode, 0)
        with open(os.path.join(d, "claude-quota.service")) as f:
            self.assertIn("%s/tools/claude-quota poll --quiet" % self.REPO, f.read())
        self.assertTrue(os.path.exists(os.path.join(d, "claude-quota.timer")))
        with open(self.marker) as f:
            log = f.read()
        self.assertIn("--user enable --now claude-quota.timer", log)
        self.assertEqual(self.run_sh("--uninstall", "--yes").returncode, 0)
        self.assertEqual(os.listdir(d), [])

    def test_unknown_arg_rejected(self):
        self.assertEqual(self.run_sh("--bogus").returncode, 2)
        self.assertFalse(os.path.exists(self.marker))


if __name__ == "__main__":
    unittest.main()
