import base64
import importlib

import pytest

import app as appmod
import jobs
import ratelimit
from app import app


@pytest.fixture
def client():
    ratelimit.hits.clear()
    yield app.test_client()
    ratelimit.hits.clear()


def test_index_serves_assets(client):
    html = client.get("/").get_data(as_text=True)
    for asset in ("/static/lib.js", "/static/app.js", "/static/style.css"):
        assert asset in html
        assert client.get(asset).status_code == 200


def test_removed_routes(client):
    assert client.get("/test-session?sid=abc").status_code == 404
    assert client.post("/compare").status_code == 404


def test_fetch_counts_validation(client):
    assert client.post("/fetch-counts", json={"usernames": ["a"]}).status_code == 401
    assert client.post("/fetch-counts", json={"sessionid": "x", "usernames": []}).status_code == 400
    r = client.post("/fetch-counts", json={"sessionid": "x", "usernames": ["bad name!"]})
    assert r.status_code == 400


def test_unknown_job(client):
    assert client.get("/fetch-progress?job_id=nope").status_code == 404
    assert client.post("/stop-fetch", json={"job_id": "nope"}).status_code == 404
    assert client.post("/pause-fetch", json={"job_id": "nope"}).status_code == 404


def test_jobs_are_isolated_and_controllable(client, monkeypatch):
    monkeypatch.setattr(jobs, "run", lambda *a, **k: None)
    ids = [client.post("/fetch-counts", json={"sessionid": "x", "usernames": [u]}).get_json()["job_id"]
           for u in ("a", "b")]
    assert ids[0] != ids[1]

    assert client.post("/pause-fetch", json={"job_id": ids[1], "paused": True}).status_code == 200
    assert client.get(f"/fetch-progress?job_id={ids[1]}").get_json()["paused"] is True

    assert client.post("/stop-fetch", json={"job_id": ids[0]}).status_code == 200
    s0 = client.get(f"/fetch-progress?job_id={ids[0]}").get_json()
    s1 = client.get(f"/fetch-progress?job_id={ids[1]}").get_json()
    assert (s0["running"], s0["stopped"]) == (False, True)
    assert (s1["running"], s1["stopped"]) == (True, False)


def test_rate_limit(client):
    codes = [client.post("/validate-session", json={}).status_code for _ in range(12)]
    assert codes[:10] == [400] * 10
    assert codes[10:] == [429, 429]


def test_basic_auth(client, monkeypatch):
    monkeypatch.setenv("APP_USER", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    assert client.get("/").status_code == 401
    bad = base64.b64encode(b"u:wrong").decode()
    assert client.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"u:p").decode()
    assert client.get("/", headers={"Authorization": f"Basic {good}"}).status_code == 200


def test_prod_requires_credentials(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "1")
    monkeypatch.delenv("APP_USER", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        importlib.reload(appmod)
    monkeypatch.delenv("REQUIRE_AUTH")
    importlib.reload(appmod)


def test_security_headers(client):
    r = client.get("/")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_healthz_skips_auth(client, monkeypatch):
    monkeypatch.setenv("APP_USER", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 401
