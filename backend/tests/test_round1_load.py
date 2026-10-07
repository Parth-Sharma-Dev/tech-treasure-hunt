"""Opt-in local HTTP contention measurement; never touches the application database."""

import json
import os
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path
from threading import Barrier
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest
from django.contrib.auth import get_user_model
from test_gameplay import game as _game

from competition.models import Completion, SubmissionDecision, Team

game = _game


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    os.environ.get("TTH_LOCAL_LOAD_TEST") != "1", reason="Opt-in local HTTP load measurement."
)
def test_round1_local_http_contention(game, live_server):
    round, missions, _, _, _ = game
    team_count = int(os.environ.get("TTH_LOAD_TEAMS", "8"))
    sessions = int(os.environ.get("TTH_LOAD_SESSIONS", "4"))
    assert 1 <= team_count <= 100 and 1 <= sessions <= 4
    codes = []
    for index in range(team_count):
        code = f"LOAD-{index:03d}"
        user = get_user_model().objects.create_user(username=code, password="synthetic-load-only")
        Team.objects.create(code=code, user=user, name=code, member_count=3)
        codes.append(code)
    barrier = Barrier(team_count * sessions)

    def worker(code):
        opener = build_opener(HTTPCookieProcessor(CookieJar()))

        def request(path, data=None, key=None):
            headers = {}
            if data is not None:
                with opener.open(live_server.url + "/api/auth/csrf", timeout=30) as response:
                    token = json.load(response)["csrf_token"]
                headers = {"Content-Type": "application/json", "X-CSRFToken": token}
                if key:
                    headers["Idempotency-Key"] = key
            started = time.perf_counter()
            with opener.open(
                Request(
                    live_server.url + path,
                    data=json.dumps(data).encode() if data is not None else None,
                    headers=headers,
                ),
                timeout=30,
            ) as response:
                assert response.status == 200
                result = json.load(response)
            return result, (time.perf_counter() - started) * 1000

        request("/api/auth/login", {"team_code": code, "password": "synthetic-load-only"})
        request("/api/missions/open", {"token": missions[0].token})
        barrier.wait(timeout=30)
        answer, submit_ms = request(
            f"/api/missions/{missions[0].token}/submit", {"answer": "0042"}, str(uuid.uuid4())
        )
        reads = [request(f"/api/rounds/{round.pk}/state")[1] for _ in range(3)]
        request("/api/auth/logout", {})
        return answer["outcome"], submit_ms, reads

    with ThreadPoolExecutor(max_workers=team_count * sessions) as pool:
        results = list(pool.map(worker, [code for code in codes for _ in range(sessions)]))
    assert Completion.objects.filter(team__code__in=codes).count() == team_count
    assert sum(item[0] == "accepted" for item in results) == team_count
    assert all(item[0] in ["accepted", "already_completed"] for item in results)
    decisions = SubmissionDecision.objects.filter(team__code__in=codes)
    admission_ms = [
        (item.admitted_at - item.ingress_at).total_seconds() * 1000 for item in decisions
    ]

    def percentile(values):
        return round_value(
            statistics.quantiles(values, n=100, method="inclusive")[94]
            if len(values) > 1
            else values[0]
        )

    report = {
        "scope": "isolated local Django HTTP + PostgreSQL; not production capacity certification",
        "teams": team_count,
        "sessions_per_team": sessions,
        "submit_requests": len(results),
        "state_requests": len(results) * 3,
        "submit_p95_ms": percentile([item[1] for item in results]),
        "state_p95_ms": percentile([value for item in results for value in item[2]]),
        "database_admission_p95_ms": percentile(admission_ms),
        "effective_completions": team_count,
    }
    path = Path(__file__).resolve().parents[2] / ".local" / "round1-load-evidence.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def round_value(value):
    return float(f"{value:.3f}")
