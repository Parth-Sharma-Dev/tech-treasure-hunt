"""Authenticated HTTP rehearsal against an isolated database on the deployed website.

Uses one cookie session per team. Reports aggregate metrics, never credentials or
response bodies. Optional writes claim one unique code and replay the same UUID.
"""

import argparse
import csv
import json
import math
import random
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = defaultdict(list)
        self.statuses = Counter()
        self.failures = Counter()
        self.logged_in = 0

    def record(self, label, status, elapsed):
        with self.lock:
            self.samples[label].append(elapsed * 1000)
            self.statuses[f"{label}:{status}"] += 1

    def fail(self, label):
        with self.lock:
            self.failures[label] += 1

    def report(self):
        def percentile(values, fraction):
            return round(
                sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2
            )

        return {
            "logged_in_teams": self.logged_in,
            "request_statuses": dict(self.statuses),
            "functional_failures": dict(self.failures),
            "latency_ms": {
                label: {
                    "requests": len(values),
                    "p95": percentile(values, 0.95),
                    "p99": percentile(values, 0.99),
                    "max": round(max(values), 2),
                }
                for label, values in self.samples.items()
            },
        }


class Client:
    def __init__(self, base, metrics, timeout):
        self.base, self.metrics, self.timeout = base, metrics, timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = None

    def request(self, label, path, data=None, extra=None):
        headers = {
            "Accept": "application/json",
            "Origin": self.base,
            "Referer": self.base + "/",
            "User-Agent": "TTH-isolated-load-rehearsal/1",
        }
        if data is not None:
            headers.update(
                {"Content-Type": "application/json", "X-CSRFToken": self.csrf or ""}
            )
        headers.update(extra or {})
        req = Request(
            self.base + path,
            headers=headers,
            data=json.dumps(data).encode() if data is not None else None,
        )
        started = time.perf_counter()
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                status, raw = response.status, response.read(3 * 1024 * 1024)
                if "no-store" not in response.headers.get("Cache-Control", ""):
                    self.metrics.fail("authenticated_response_cached")
        except HTTPError as error:
            status, raw = error.code, error.read(100000)
        except (URLError, OSError, TimeoutError):
            status, raw = 0, b""
        self.metrics.record(label, status, time.perf_counter() - started)
        if status != 200:
            self.metrics.fail(f"{label}_http_failure")
            return None
        if label == "image":
            return bool(raw.startswith(b"\x89PNG\r\n\x1a\n"))
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            self.metrics.fail(f"{label}_invalid_json")
            return None

    def login(self, row):
        token = self.request("csrf", "/api/auth/csrf")
        if not token or not token.get("csrf_token"):
            return False
        self.csrf = token["csrf_token"]
        result = self.request(
            "login",
            "/api/auth/login",
            {"team_code": row["Team ID"], "password": row["Password"]},
        )
        if not result or result.get("team", {}).get("code") != row["Team ID"]:
            return False
        self.csrf = result["csrf_token"]
        with self.metrics.lock:
            self.metrics.logged_in += 1
        return True


def read_credentials(path, count, submit):
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        if not {"Team ID", "Password"}.issubset(reader.fieldnames or []):
            raise ValueError(
                "CSV requires Team ID and Password columns; other roster columns are allowed."
            )
        rows = list(reader)
    if len(rows) < count or count < 1:
        raise ValueError("Not enough credential rows for the requested team count.")
    rows = rows[:count]
    if any(
        None in row or not row.get("Team ID") or not row.get("Password") for row in rows
    ):
        raise ValueError("Malformed or blank credentials.")
    if len({r["Team ID"] for r in rows}) != count:
        raise ValueError("Team IDs must be distinct; keep one session per team.")
    if submit and (
        any(not row.get("Load Code") for row in rows)
        or len({row["Load Code"].upper() for row in rows}) != count
    ):
        raise ValueError(
            "Write mode requires one distinct unclaimed Load Code per team."
        )
    return rows


def worker(index, row, args, metrics, deadline, abort):
    client = Client(args.base_url, metrics, args.timeout)
    # Event.wait makes abort/interrupt stop ramp delays promptly.
    if abort.wait(args.ramp_seconds * index / max(1, args.teams - 1)):
        return
    signed_in = False
    try:
        signed_in = client.login(row)
        if not signed_in:
            metrics.fail("login_setup_failed")
            abort.set()
            return
        if args.mission_token:
            opened = client.request(
                "open", "/api/missions/open", {"token": args.mission_token}
            )
            if not opened or not opened.get("opened"):
                metrics.fail("mission_open_failed")
                abort.set()
                return
            if args.submit:
                key = str(uuid.uuid4())
                path = f"/api/missions/{args.mission_token}/submit"
                body, headers = {"answer": row["Load Code"]}, {"Idempotency-Key": key}
                first = client.request("submit", path, body, headers)
                replay = client.request("replay", path, body, headers)
                if (
                    not first
                    or not replay
                    or first.get("outcome") != "accepted"
                    or any(
                        first.get(field) != replay.get(field)
                        for field in ("decision_id", "points_awarded", "receipt")
                    )
                ):
                    metrics.fail("claim_or_replay_failed")
                    abort.set()
                    return
        image_at = 0
        while time.monotonic() < deadline and not abort.is_set():
            me = client.request("me", "/api/me")
            dashboard = client.request("dashboard", "/api/rounds")
            state = client.request("state", f"/api/rounds/{args.round_id}/state")
            if (
                not me
                or not dashboard
                or not state
                or not any(
                    r.get("id") == args.round_id for r in dashboard.get("rounds", [])
                )
            ):
                metrics.fail("round_or_session_unavailable")
                abort.set()
                break
            if args.mission_token:
                mission = client.request(
                    "mission", f"/api/missions/{args.mission_token}"
                )
                if mission and mission.get("image") and time.monotonic() >= image_at:
                    if not client.request("image", mission["image"]["url"]):
                        metrics.fail("image_invalid_or_unavailable")
                    image_at = time.monotonic() + args.image_seconds
            abort.wait(args.poll_seconds * random.uniform(0.87, 1.13))
    except Exception:  # noqa: BLE001 - redact errors that could contain private response data.
        # No exception traceback can echo private response content or credential rows.
        metrics.fail("unexpected_worker_failure")
        abort.set()
    finally:
        if signed_in:
            client.request("logout", "/api/auth/logout", {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--round-id", type=int, required=True)
    parser.add_argument("--teams", type=int, default=110)
    parser.add_argument("--duration-seconds", type=float, default=300)
    parser.add_argument("--ramp-seconds", type=float, default=60)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--image-seconds", type=float, default=60)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--mission-token")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--confirm-isolated-database", action="store_true", required=True
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    parsed = urlsplit(args.base_url)
    if (
        parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}
    ) or (
        parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        parser.error("Use your HTTPS website origin without a path or credentials.")
    if (
        not 1 <= args.teams <= 500
        or min(
            args.duration_seconds, args.poll_seconds, args.image_seconds, args.timeout
        )
        <= 0
        or args.ramp_seconds < 0
        or args.round_id < 1
    ):
        parser.error("Use positive durations/IDs, 1–500 teams and a nonnegative ramp.")
    if args.submit and not args.mission_token:
        parser.error("Write mode needs a released mission token.")
    if args.report.exists():
        parser.error("Choose a new report path; existing reports are preserved.")
    try:
        rows = read_credentials(args.credentials, args.teams, args.submit)
    except (OSError, ValueError, csv.Error):
        parser.error(
            "Credential input is invalid; check columns, distinct IDs and Load Codes."
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    metrics, abort = Metrics(), threading.Event()
    started = time.monotonic()
    deadline = started + args.ramp_seconds + args.duration_seconds
    with ThreadPoolExecutor(max_workers=args.teams) as pool:
        futures = [
            pool.submit(worker, i, row, args, metrics, deadline, abort)
            for i, row in enumerate(rows)
        ]
        try:
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            abort.set()
    report = metrics.report()
    report.update(
        {
            "target": args.base_url,
            "requested_teams": args.teams,
            "duration_seconds": round(time.monotonic() - started, 2),
            "poll_seconds": args.poll_seconds,
            "write_mode": args.submit,
        }
    )
    total = sum(report["request_statuses"].values())
    http_errors = sum(
        v for k, v in report["request_statuses"].items() if not k.endswith(":200")
    )
    report["http_error_rate"] = http_errors / total if total else 1
    reads = [
        v
        for k, v in report["latency_ms"].items()
        if k in {"me", "dashboard", "state", "mission", "image"}
    ]
    report["passed"] = bool(
        not abort.is_set()
        and metrics.logged_in == args.teams
        and not metrics.failures
        and reads
        and report["http_error_rate"] < 0.01
        and all(v["p95"] < 2000 and v["p99"] < 5000 for v in reads)
    )
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
