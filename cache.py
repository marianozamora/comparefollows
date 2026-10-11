"""Caché de perfiles en SQLite (cada operación abre su propia conexión)."""
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

log = logging.getLogger("comparefollows.cache")

LEGACY_JSON = "follower_cache.json"   # formato viejo, solo se importa una vez
TTL         = timedelta(days=7)


def _default_path() -> str:
    # Railway define esta variable cuando hay un volumen montado
    base = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "")
    return os.path.join(base, "follower_cache.db") if base else "follower_cache.db"


DB_PATH = os.environ.get("CACHE_DB") or _default_path()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS profiles ("
        " username TEXT PRIMARY KEY, followers INTEGER, following INTEGER,"
        " posts INTEGER, verified INTEGER, fetched_at TEXT NOT NULL)"
    )
    return conn


def import_legacy():
    """Migra follower_cache.json a SQLite la primera vez (tabla vacía)."""
    if not os.path.exists(LEGACY_JSON):
        return
    try:
        with open(LEGACY_JSON) as f:
            old = json.load(f)
        with _db() as conn:
            if conn.execute("SELECT 1 FROM profiles LIMIT 1").fetchone():
                return
            conn.executemany(
                "INSERT OR IGNORE INTO profiles VALUES (?,?,?,?,?,?)",
                [(u, d.get("followers"), d.get("following"), d.get("posts", 0),
                  int(bool(d.get("verified"))), d.get("fetched_at", ""))
                 for u, d in old.items() if d.get("fetched_at")],
            )
        log.info("Caché legacy importada desde %s", LEGACY_JSON)
    except (OSError, ValueError, AttributeError, sqlite3.Error):
        log.warning("No se pudo importar %s", LEGACY_JSON, exc_info=True)


def get(username: str) -> dict | None:
    """Perfil cacheado si es reciente, o None."""
    with _db() as conn:
        row = conn.execute(
            "SELECT followers, following, posts, verified, fetched_at"
            " FROM profiles WHERE username=?", (username,)
        ).fetchone()
    if not row or row[0] is None or row[1] is None:
        return None
    try:
        if datetime.fromisoformat(row[4]) <= datetime.now() - TTL:
            return None
    except ValueError:
        return None
    return {"followers": row[0], "following": row[1], "posts": row[2], "verified": bool(row[3])}


def put(username: str, profile: dict):
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?,?)",
            (username, profile["followers"], profile["following"], profile["posts"],
             int(profile["verified"]), datetime.now().isoformat()),
        )


def purge_old() -> int:
    """Borra perfiles vencidos (el TTL solo se aplica al leer). Devuelve cuántos."""
    cutoff = (datetime.now() - TTL).isoformat()
    with _db() as conn:
        n = conn.execute("DELETE FROM profiles WHERE fetched_at < ?", (cutoff,)).rowcount
    if n:
        log.info("Caché: %d perfiles vencidos eliminados", n)
    return n
