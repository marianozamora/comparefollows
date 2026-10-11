import threading
import time

import pytest
import requests

import cache
import instagram
import jobs

PROFILE = {"followers": 1, "following": 2, "posts": 3, "verified": False}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", str(tmp_path / "c.db"))
    monkeypatch.setattr(jobs, "_sleep", lambda job, s: None)   # sin esperas reales
    monkeypatch.setattr(instagram, "make_session", lambda sid: object())


def _job(users):
    _, job = jobs.create(users)
    return job


def _http_error(code):
    r = requests.Response()
    r.status_code = code
    return requests.HTTPError(response=r)


def test_fetches_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(instagram, "fetch_profile", lambda s, u: calls.append(u) or PROFILE)
    job = _job(["a", "b"])
    jobs.run(job, ["a", "b"], "sid")
    assert job["results"] == {"a": PROFILE, "b": PROFILE}
    assert (job["done"], job["running"]) == (2, False)

    # segunda corrida: todo sale de la caché
    calls.clear()
    job2 = _job(["a", "b"])
    jobs.run(job2, ["a", "b"], "sid")
    assert calls == [] and job2["done"] == 2


def test_failure_marks_none_after_retries(monkeypatch):
    monkeypatch.setattr(instagram, "fetch_profile", lambda s, u: (_ for _ in ()).throw(_http_error(500)))
    job = _job(["a"])
    jobs.run(job, ["a"], "sid")
    assert job["results"] == {"a": None}
    assert job["last_error"] == "HTTP 500"


def test_429_backoff_is_exponential(monkeypatch):
    waits = []
    monkeypatch.setattr(jobs, "_sleep", lambda job, s: waits.append(s))
    monkeypatch.setattr(jobs.random, "uniform", lambda a, b: 1)
    outcomes = [_http_error(429), _http_error(429), PROFILE]

    def fake(s, u):
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(instagram, "fetch_profile", fake)
    job = _job(["a"])
    jobs.run(job, ["a"], "sid")
    assert job["results"]["a"] == PROFILE
    assert waits[:2] == [30, 60]


def test_stop_interrupts(monkeypatch):
    job = _job(["a", "b", "c"])

    def fake(s, u):
        job["running"] = False   # el usuario detiene durante la primera consulta
        return PROFILE

    monkeypatch.setattr(instagram, "fetch_profile", fake)
    jobs.run(job, ["a", "b", "c"], "sid")
    assert list(job["results"]) == ["a"]


def test_pause_blocks_until_resumed(monkeypatch):
    fetched = []
    monkeypatch.setattr(instagram, "fetch_profile", lambda s, u: fetched.append(u) or PROFILE)
    job = _job(["a"])
    job["paused"] = True
    t = threading.Thread(target=jobs.run, args=(job, ["a"], "sid"))
    t.start()
    time.sleep(0.5)
    assert fetched == []
    job["paused"] = False
    t.join(timeout=5)
    assert fetched == ["a"] and not t.is_alive()


def test_clean_usernames():
    assert jobs.clean_usernames(["a", "a", "b c", 5, "ok.user_1"]) == ["a", "ok.user_1"]
    assert jobs.clean_usernames("nope") == []
