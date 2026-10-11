import base64
import json

import pytest

import app as appmod
from app import app, parse_file


@pytest.fixture
def client():
    return app.test_client()


# ── parse_file ────────────────────────────────────────────────────────────────

def test_parse_followers_json():
    data = [{"string_list_data": [{"value": "Alice"}]},
            {"string_list_data": [{"value": "bob"}]}]
    assert parse_file(json.dumps(data).encode(), "followers_1.json") == {"alice", "bob"}


def test_parse_following_json():
    data = {"relationships_following": [{"string_list_data": [{"value": "Carol"}]}]}
    assert parse_file(json.dumps(data).encode(), "following.json") == {"carol"}


def test_parse_html_u_links():
    html = '<a href="https://www.instagram.com/_u/dave.x">dave.x</a><a href="https://www.instagram.com/_u/Eve_1">e</a>'
    assert parse_file(html.encode(), "followers.html") == {"dave.x", "eve_1"}


def test_parse_plain_text():
    text = "# comentario\n@Frank\n\n  grace  \n"
    assert parse_file(text.encode(), "list.txt") == {"frank", "grace"}


# ── /compare ──────────────────────────────────────────────────────────────────

def _upload(client, followers, following):
    from io import BytesIO
    return client.post("/compare", data={
        "followers": (BytesIO(followers.encode()), "followers.txt"),
        "following": (BytesIO(following.encode()), "following.txt"),
    }, content_type="multipart/form-data")


def test_compare_diff(client):
    r = _upload(client, "a\nb", "b\nc")
    assert r.status_code == 200
    body = r.get_json()
    assert body["not_following_back"] == ["c"]
    assert body["not_followed_back"] == ["a"]


def test_compare_missing_files(client):
    assert client.post("/compare").status_code == 400


# ── fetch jobs ────────────────────────────────────────────────────────────────

def test_fetch_counts_rejects_invalid_usernames(client):
    r = client.post("/fetch-counts", json={"sessionid": "x", "usernames": ["bad name!"]})
    assert r.status_code == 400


def test_fetch_counts_requires_sessionid(client):
    assert client.post("/fetch-counts", json={"usernames": ["a"]}).status_code == 401


def test_progress_unknown_job(client):
    assert client.get("/fetch-progress?job_id=nope").status_code == 404
    assert client.post("/stop-fetch", json={"job_id": "nope"}).status_code == 404


def test_jobs_are_isolated(client, monkeypatch):
    monkeypatch.setattr(appmod, "_fetch_worker", lambda *a, **k: None)
    ids = [client.post("/fetch-counts", json={"sessionid": "x", "usernames": [u]}).get_json()["job_id"]
           for u in ("a", "b")]
    assert ids[0] != ids[1]
    assert client.post("/stop-fetch", json={"job_id": ids[0]}).status_code == 200
    assert client.get(f"/fetch-progress?job_id={ids[0]}").get_json()["running"] is False
    assert client.get(f"/fetch-progress?job_id={ids[1]}").get_json()["running"] is True


def test_test_session_route_removed(client):
    assert client.get("/test-session?sid=abc").status_code == 404


# ── auth ──────────────────────────────────────────────────────────────────────

def test_basic_auth(client, monkeypatch):
    monkeypatch.setenv("APP_USER", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    assert client.get("/").status_code == 401
    bad = base64.b64encode(b"u:wrong").decode()
    assert client.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"u:p").decode()
    assert client.get("/", headers={"Authorization": f"Basic {good}"}).status_code == 200


# ── cache SQLite ──────────────────────────────────────────────────────────────

def test_cache_roundtrip_and_ttl(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(appmod, "CACHE_DB", str(tmp_path / "c.db"))
    assert appmod._cache_get("zed") is None
    prof = {"followers": 10, "following": 5, "posts": 3, "verified": True}
    appmod._cache_put("zed", prof)
    assert appmod._cache_get("zed") == prof
    old = (datetime.now() - timedelta(days=8)).isoformat()
    with appmod._db() as conn:
        conn.execute("UPDATE profiles SET fetched_at=? WHERE username='zed'", (old,))
    assert appmod._cache_get("zed") is None


def test_legacy_json_import(tmp_path, monkeypatch):
    from datetime import datetime
    legacy = tmp_path / "old.json"
    legacy.write_text(json.dumps({"amy": {"followers": 1, "following": 2, "posts": 3,
                                          "verified": False,
                                          "fetched_at": datetime.now().isoformat()}}))
    monkeypatch.setattr(appmod, "CACHE_FILE", str(legacy))
    monkeypatch.setattr(appmod, "CACHE_DB", str(tmp_path / "c.db"))
    appmod._import_legacy_cache()
    assert appmod._cache_get("amy")["followers"] == 1


# ── rate limit ────────────────────────────────────────────────────────────────

def test_rate_limit(client):
    appmod._hits.clear()
    codes = [client.post("/validate-session", json={}).status_code for _ in range(12)]
    assert codes[:10] == [400] * 10
    assert codes[10:] == [429, 429]
    appmod._hits.clear()


# ── auth obligatoria en producción ────────────────────────────────────────────

def test_prod_requires_credentials(monkeypatch):
    import importlib
    monkeypatch.setenv("REQUIRE_AUTH", "1")
    monkeypatch.delenv("APP_USER", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        importlib.reload(appmod)
    monkeypatch.delenv("REQUIRE_AUTH")
    importlib.reload(appmod)


def test_static_assets_served(client):
    html = client.get("/").get_data(as_text=True)
    assert "/static/app.js" in html and "/static/style.css" in html
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
