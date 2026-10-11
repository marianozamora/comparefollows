from flask import Flask, render_template, request, jsonify, Response
import json
import re
import threading
import os
import time
import random
import hmac
import uuid
import sqlite3
import functools
from collections import defaultdict, deque
from datetime import datetime, timedelta
import requests as http
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

IS_PROD = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("REQUIRE_AUTH") == "1")

if IS_PROD:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)   # IP real detrás del proxy de Railway
    if not (os.environ.get("APP_USER") and os.environ.get("APP_PASSWORD")):
        raise RuntimeError("APP_USER y APP_PASSWORD son obligatorios en producción")


# ── Rate limit (en memoria, por IP) ───────────────────────────────────────────

_hits: dict[tuple, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def rate_limit(max_calls: int, per_seconds: int = 60):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__name__, request.remote_addr)
            now = time.monotonic()
            with _hits_lock:
                q = _hits[key]
                while q and now - q[0] > per_seconds:
                    q.popleft()
                if len(q) >= max_calls:
                    return jsonify({"error": "Demasiadas solicitudes, esperá un momento"}), 429
                q.append(now)
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ── Basic Auth ────────────────────────────────────────────────────────────────

@app.before_request
def _check_auth():
    user = os.environ.get("APP_USER", "")
    pwd  = os.environ.get("APP_PASSWORD", "")
    if not user or not pwd:
        return   # dev local sin restricción
    auth = request.authorization
    if (not auth
            or not hmac.compare_digest(auth.username.encode(), user.encode())
            or not hmac.compare_digest((auth.password or "").encode(), pwd.encode())):
        return Response(
            "Acceso no autorizado",
            401,
            {"WWW-Authenticate": 'Basic realm="CompareFollows"'},
        )


# ── Instagram API ─────────────────────────────────────────────────────────────

CACHE_FILE = "follower_cache.json"   # formato viejo, solo se importa una vez
CACHE_DB   = os.environ.get("CACHE_DB", "follower_cache.db")
CACHE_TTL  = timedelta(days=7)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{1,30}$")
MAX_JOBS = 20   # jobs terminados que se conservan en memoria

# Un job por usuario/sesión: job_id -> estado
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _prune_jobs():
    """Descarta los jobs terminados más viejos (llamar con _lock tomado)."""
    finished = [k for k, j in _jobs.items() if not j["running"]]
    for k in finished[:max(0, len(_jobs) - MAX_JOBS)]:
        del _jobs[k]


def _make_session(session_id: str) -> http.Session:
    s = http.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "x-ig-app-id":     "936619743392459",
        "Referer":         "https://www.instagram.com/",
        "Origin":          "https://www.instagram.com",
    })
    s.cookies.set("sessionid", session_id, domain=".instagram.com")
    return s


def _fetch_profile(session: http.Session, username: str) -> dict:
    resp = session.get(
        "https://i.instagram.com/api/v1/users/web_profile_info/",
        params={"username": username}, timeout=15,
    )
    if resp.status_code == 404:
        return {"followers": -1, "following": 0, "posts": 0, "verified": False}
    resp.raise_for_status()
    data = resp.json()
    user = data.get("data", {}).get("user")
    if not user:
        return {"followers": -1, "following": 0, "posts": 0, "verified": False}
    return {
        "followers": user.get("edge_followed_by", {}).get("count", 0),
        "following": user.get("edge_follow",      {}).get("count", 0),
        "posts":     user.get("edge_owner_to_timeline_media", {}).get("count", 0),
        "verified":  user.get("is_verified", False),
    }


# ── Cache (SQLite) ────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(CACHE_DB, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS profiles ("
        " username TEXT PRIMARY KEY, followers INTEGER, following INTEGER,"
        " posts INTEGER, verified INTEGER, fetched_at TEXT NOT NULL)"
    )
    return conn


def _import_legacy_cache():
    """Migra follower_cache.json a SQLite la primera vez (tabla vacía)."""
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE) as f:
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
    except (OSError, ValueError, AttributeError):
        app.logger.warning("No se pudo importar %s", CACHE_FILE, exc_info=True)


def _cache_get(username: str) -> dict | None:
    """Devuelve el perfil cacheado si es reciente, o None."""
    with _db() as conn:
        row = conn.execute(
            "SELECT followers, following, posts, verified, fetched_at"
            " FROM profiles WHERE username=?", (username,)
        ).fetchone()
    if not row or row[0] is None or row[1] is None:
        return None
    try:
        if datetime.fromisoformat(row[4]) <= datetime.now() - CACHE_TTL:
            return None
    except ValueError:
        return None
    return {"followers": row[0], "following": row[1], "posts": row[2], "verified": bool(row[3])}


def _cache_put(username: str, profile: dict):
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?,?)",
            (username, profile["followers"], profile["following"], profile["posts"],
             int(profile["verified"]), datetime.now().isoformat()),
        )


try:
    _import_legacy_cache()
except sqlite3.Error:
    app.logger.warning("Cache SQLite no disponible", exc_info=True)


# ── Background worker ─────────────────────────────────────────────────────────

def _sleep(job: dict, seconds: float):
    """Sleep interrumpible: corta apenas el job se detiene."""
    end = time.monotonic() + seconds
    while job["running"] and time.monotonic() < end:
        time.sleep(min(1, max(0, end - time.monotonic())))


def _fetch_worker(job: dict, usernames: list[str], session_id: str):
    session   = _make_session(session_id)
    throttled = 0   # 429 consecutivos → backoff exponencial

    for username in usernames:
        if not job["running"]:
            break

        try:
            profile = _cache_get(username)
        except sqlite3.Error:
            profile = None
        if profile:
            with _lock:
                job["results"][username] = profile
                job["done"] += 1
            continue

        last_error = None
        fetched    = False
        for attempt in range(3):
            if not job["running"]:
                break
            try:
                profile = _fetch_profile(session, username)
                try:
                    _cache_put(username, profile)
                except sqlite3.Error:
                    app.logger.warning("No se pudo guardar en caché", exc_info=True)
                with _lock:
                    job["results"][username] = profile
                    job["done"] += 1
                fetched   = True
                throttled = 0
                break
            except http.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code == 429:
                    wait = min(30 * 2 ** throttled, 480) * random.uniform(1, 1.3)
                    throttled += 1
                    last_error = f"Rate limit (429) — esperando {int(wait)}s…"
                    with _lock:
                        job["last_error"] = last_error
                    _sleep(job, wait)
                else:
                    last_error = f"HTTP {code}"
                    if attempt < 2:
                        _sleep(job, random.uniform(8, 15))
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < 2:
                    _sleep(job, random.uniform(8, 15))

        if not fetched and job["running"]:
            with _lock:
                job["results"][username] = None
                job["done"] += 1
                job["last_error"] = last_error

        _sleep(job, random.uniform(3, 7))

    with _lock:
        job["running"] = False


# ── File parser ───────────────────────────────────────────────────────────────

def parse_file(file_bytes: bytes, filename: str) -> set[str]:
    text = file_bytes.decode("utf-8", errors="ignore")

    if filename.endswith(".html") or "instagram.com" in text:
        users = re.findall(r'instagram\.com/_u/([A-Za-z0-9_.]+)', text)
        if not users:
            users = re.findall(r'instagram\.com/([A-Za-z0-9_.][A-Za-z0-9_.]*)["\'?]', text)
        if users:
            return {u.lower() for u in users}

    try:
        data = json.loads(text)
        users: set[str] = set()

        def extract(arr):
            if not isinstance(arr, list):
                return
            for item in arr:
                if isinstance(item, dict):
                    for entry in item.get("string_list_data", []):
                        if v := entry.get("value"):
                            users.add(v.lower())
                    if v := item.get("value"):
                        users.add(v.lower())

        if isinstance(data, list):
            extract(data)
        elif isinstance(data, dict):
            if "relationships_following" in data:
                extract(data["relationships_following"])
            else:
                for v in data.values():
                    extract(v)

        if users:
            return users
    except (json.JSONDecodeError, AttributeError):
        pass

    return {
        line.strip().lstrip("@").lower()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/compare", methods=["POST"])
@rate_limit(30)
def compare():
    if "followers" not in request.files or "following" not in request.files:
        return jsonify({"error": "Faltan archivos"}), 400
    followers_file = request.files["followers"]
    following_file = request.files["following"]
    followers = parse_file(followers_file.read(), followers_file.filename)
    following = parse_file(following_file.read(), following_file.filename)
    if not followers and not following:
        return jsonify({"error": "No se pudieron leer los archivos"}), 400
    return jsonify({
        "not_following_back": sorted(following - followers),
        "not_followed_back":  sorted(followers - following),
        "followers_count":    len(followers),
        "following_count":    len(following),
    })


@app.route("/validate-session", methods=["POST"])
@rate_limit(10)
def validate_session():
    """Valida un sessionid sin guardarlo — cada usuario gestiona el suyo."""
    data       = request.json or {}
    session_id = data.get("sessionid", "").strip()
    if not session_id:
        return jsonify({"error": "Pegá el valor del cookie sessionid"}), 400
    try:
        session = _make_session(session_id)
        profile = _fetch_profile(session, "instagram")
        if not profile or profile.get("followers", -1) == -1:
            return jsonify({"error": "Sesión inválida o expirada"}), 401
    except http.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code in (401, 403):
            return jsonify({"error": "Sesión inválida o expirada"}), 401
        return jsonify({"error": f"Error HTTP {code}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error al validar: {e}"}), 500
    return jsonify({"ok": True})


@app.route("/fetch-counts", methods=["POST"])
@rate_limit(5)
def fetch_counts():
    data       = request.json or {}
    session_id = data.get("sessionid", "").strip()
    usernames  = data.get("usernames", [])

    if not session_id:
        return jsonify({"error": "Falta el sessionid"}), 401
    if not isinstance(usernames, list) or not usernames:
        return jsonify({"error": "Lista vacía"}), 400
    usernames = [u for u in dict.fromkeys(usernames)
                 if isinstance(u, str) and USERNAME_RE.match(u)]
    if not usernames:
        return jsonify({"error": "Ningún usuario válido"}), 400

    job_id = uuid.uuid4().hex
    job = {
        "total": len(usernames), "done": 0, "results": {},
        "running": True, "error": None, "last_error": None,
        "started_at": datetime.now().isoformat(),
    }
    with _lock:
        _prune_jobs()
        _jobs[job_id] = job

    threading.Thread(target=_fetch_worker, args=(job, usernames, session_id), daemon=True).start()
    return jsonify({"ok": True, "total": len(usernames), "job_id": job_id})


@app.route("/fetch-progress")
def fetch_progress_route():
    with _lock:
        job = _jobs.get(request.args.get("job_id", ""))
        if job is None:
            return jsonify({"error": "Job no encontrado"}), 404
        return jsonify(job)


@app.route("/stop-fetch", methods=["POST"])
def stop_fetch():
    job_id = (request.json or {}).get("job_id", "")
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Job no encontrado"}), 404
        job["running"] = False
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001, threaded=True)
