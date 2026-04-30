from flask import Flask, render_template, request, jsonify
import json
import re
import threading
import os
import time
import random
from datetime import datetime, timedelta
import requests as http

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

CACHE_FILE      = "follower_cache.json"
SESSION_ID_FILE = "ig_sessionid"

_session_id = None
_progress   = {"total": 0, "done": 0, "results": {}, "running": False,
                "error": None, "last_error": None, "started_at": None}
_lock       = threading.Lock()

# ── Instagram API ─────────────────────────────────────────────────────────────

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


def _fetch_profile(session: http.Session, username: str) -> dict | None:
    url  = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    resp = session.get(url, timeout=15)
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


def _load_session_id() -> str | None:
    if os.path.exists(SESSION_ID_FILE):
        with open(SESSION_ID_FILE) as f:
            v = f.read().strip()
            return v if v else None
    return None


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


# ── Background worker ─────────────────────────────────────────────────────────

def _fetch_worker(usernames: list[str]):
    global _progress
    sid = _session_id or _load_session_id()
    if not sid:
        with _lock:
            _progress["error"]   = "No hay sesión activa"
            _progress["running"] = False
        return

    session = _make_session(sid)
    cache   = _load_cache()
    cutoff  = datetime.now() - timedelta(days=7)

    for username in usernames:
        if not _progress["running"]:
            break

        # Serve from cache if fresh
        cached = cache.get(username)
        if cached and cached.get("followers") is not None and cached.get("following") is not None:
            try:
                if datetime.fromisoformat(cached["fetched_at"]) > cutoff:
                    profile = {k: cached[k] for k in ("followers", "following", "posts", "verified") if k in cached}
                    with _lock:
                        _progress["results"][username] = profile
                        _progress["done"] += 1
                    continue
            except Exception:
                pass

        last_error = None
        fetched    = False
        for attempt in range(3):
            try:
                profile = _fetch_profile(session, username)
                cache[username] = {**profile, "fetched_at": datetime.now().isoformat()}
                _save_cache(cache)
                with _lock:
                    _progress["results"][username] = profile
                    _progress["done"] += 1
                fetched = True
                break
            except http.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code == 429:
                    last_error = "Rate limit (429) — esperando…"
                    with _lock:
                        _progress["last_error"] = last_error
                    time.sleep(random.uniform(30, 60))
                else:
                    last_error = f"HTTP {code}"
                    if attempt < 2:
                        time.sleep(random.uniform(8, 15))
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < 2:
                    time.sleep(random.uniform(8, 15))

        if not fetched:
            with _lock:
                _progress["results"][username] = None
                _progress["done"] += 1
                _progress["last_error"] = last_error

        time.sleep(random.uniform(3, 7))

    with _lock:
        _progress["running"] = False


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


@app.route("/session-status")
def session_status():
    sid = _session_id or _load_session_id()
    return jsonify({"has_session": bool(sid)})


@app.route("/login", methods=["POST"])
def login_route():
    global _session_id
    data       = request.json or {}
    session_id = data.get("sessionid", "").strip()
    if not session_id:
        return jsonify({"error": "Pegá el valor del cookie sessionid"}), 400

    # Validate by fetching a known public profile
    try:
        session  = _make_session(session_id)
        profile  = _fetch_profile(session, "instagram")
        if not profile or profile.get("followers", -1) == -1:
            return jsonify({"error": "Sesión inválida o expirada"}), 401
    except http.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code in (401, 403):
            return jsonify({"error": "Sesión inválida o expirada"}), 401
        return jsonify({"error": f"Error HTTP {code} al validar la sesión"}), 500
    except Exception as e:
        return jsonify({"error": f"Error al validar: {e}"}), 500

    _session_id = session_id
    with open(SESSION_ID_FILE, "w") as f:
        f.write(session_id)
    return jsonify({"ok": True})


@app.route("/logout", methods=["POST"])
def logout_route():
    global _session_id
    _session_id = None
    if os.path.exists(SESSION_ID_FILE):
        os.remove(SESSION_ID_FILE)
    return jsonify({"ok": True})


@app.route("/fetch-counts", methods=["POST"])
def fetch_counts():
    global _progress
    if _progress["running"]:
        return jsonify({"error": "Ya hay un proceso en curso"}), 409
    sid = _session_id or _load_session_id()
    if not sid:
        return jsonify({"error": "No hay sesión activa"}), 401
    usernames = request.json.get("usernames", [])
    if not usernames:
        return jsonify({"error": "Lista vacía"}), 400
    with _lock:
        _progress = {
            "total": len(usernames), "done": 0, "results": {},
            "running": True, "error": None, "last_error": None,
            "started_at": datetime.now().isoformat(),
        }
    threading.Thread(target=_fetch_worker, args=(usernames,), daemon=True).start()
    return jsonify({"ok": True, "total": len(usernames)})


@app.route("/fetch-progress")
def fetch_progress_route():
    with _lock:
        return jsonify(_progress)


@app.route("/stop-fetch", methods=["POST"])
def stop_fetch():
    with _lock:
        _progress["running"] = False
    return jsonify({"ok": True})


@app.route("/test-session")
def test_session():
    sid = _session_id or _load_session_id()
    if not sid:
        return jsonify({"ok": False, "error": "Sin sesión"})
    try:
        session = _make_session(sid)
        profile = _fetch_profile(session, "instagram")
        return jsonify({"ok": True, **profile})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    app.run(debug=True, port=5001, threaded=True)
