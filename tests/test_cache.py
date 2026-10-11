import json
from datetime import datetime, timedelta

import pytest

import cache


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", str(tmp_path / "c.db"))
    monkeypatch.setattr(cache, "LEGACY_JSON", str(tmp_path / "old.json"))


def test_roundtrip_and_ttl():
    assert cache.get("zed") is None
    prof = {"followers": 10, "following": 5, "posts": 3, "verified": True}
    cache.put("zed", prof)
    assert cache.get("zed") == prof
    old = (datetime.now() - timedelta(days=8)).isoformat()
    with cache._db() as conn:
        conn.execute("UPDATE profiles SET fetched_at=? WHERE username='zed'", (old,))
    assert cache.get("zed") is None


def test_legacy_json_import(tmp_path):
    (tmp_path / "old.json").write_text(json.dumps({
        "amy": {"followers": 1, "following": 2, "posts": 3, "verified": False,
                "fetched_at": datetime.now().isoformat()}}))
    cache.import_legacy()
    assert cache.get("amy")["followers"] == 1


def test_default_path_uses_railway_volume(monkeypatch):
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
    assert cache._default_path() == "/data/follower_cache.db"
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH")
    assert cache._default_path() == "follower_cache.db"


def test_purge_old_removes_only_expired():
    prof = {"followers": 1, "following": 1, "posts": 1, "verified": False}
    cache.put("fresh", prof)
    cache.put("stale", prof)
    old = (datetime.now() - timedelta(days=30)).isoformat()
    with cache._db() as conn:
        conn.execute("UPDATE profiles SET fetched_at=? WHERE username='stale'", (old,))
    assert cache.purge_old() == 1
    assert cache.get("fresh") == prof
    with cache._db() as conn:
        assert conn.execute("SELECT username FROM profiles").fetchall() == [("fresh",)]
