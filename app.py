import hmac
import logging
import os

import requests as http
from flask import Flask, Response, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

import cache
import instagram
import jobs
from ratelimit import rate_limit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # solo recibe JSON con usernames

IS_PROD = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("REQUIRE_AUTH") == "1")

if IS_PROD:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)   # IP real detrás del proxy de Railway
    if not (os.environ.get("APP_USER") and os.environ.get("APP_PASSWORD")):
        raise RuntimeError("APP_USER y APP_PASSWORD son obligatorios en producción")

cache.import_legacy()


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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/validate-session", methods=["POST"])
@rate_limit(10)
def validate_session():
    """Valida un sessionid sin guardarlo — cada usuario gestiona el suyo."""
    data       = request.json or {}
    session_id = data.get("sessionid", "").strip()
    if not session_id:
        return jsonify({"error": "Pegá el valor del cookie sessionid"}), 400
    try:
        session = instagram.make_session(session_id)
        profile = instagram.fetch_profile(session, "instagram")
        if not profile or profile.get("followers", -1) == -1:
            return jsonify({"error": "Sesión inválida o expirada"}), 401
    except http.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code in (401, 403):
            return jsonify({"error": "Sesión inválida o expirada"}), 401
        return jsonify({"error": f"Error HTTP {code}"}), 500
    except Exception as e:
        app.logger.warning("validate-session falló: %s", type(e).__name__)
        return jsonify({"error": f"Error al validar: {e}"}), 500
    return jsonify({"ok": True})


@app.route("/fetch-counts", methods=["POST"])
@rate_limit(5)
def fetch_counts():
    data       = request.json or {}
    session_id = data.get("sessionid", "").strip()

    if not session_id:
        return jsonify({"error": "Falta el sessionid"}), 401
    if not isinstance(data.get("usernames"), list) or not data["usernames"]:
        return jsonify({"error": "Lista vacía"}), 400
    usernames = jobs.clean_usernames(data["usernames"])
    if not usernames:
        return jsonify({"error": "Ningún usuario válido"}), 400

    job_id, job = jobs.create(usernames)
    jobs.start(job, usernames, session_id)
    return jsonify({"ok": True, "total": len(usernames), "job_id": job_id})


@app.route("/fetch-progress")
def fetch_progress_route():
    snap = jobs.snapshot(request.args.get("job_id", ""))
    if snap is None:
        return jsonify({"error": "Job no encontrado"}), 404
    return jsonify(snap)


@app.route("/stop-fetch", methods=["POST"])
def stop_fetch():
    if not jobs.stop((request.json or {}).get("job_id", "")):
        return jsonify({"error": "Job no encontrado"}), 404
    return jsonify({"ok": True})


@app.route("/pause-fetch", methods=["POST"])
def pause_fetch():
    data = request.json or {}
    if not jobs.set_paused(data.get("job_id", ""), data.get("paused", True)):
        return jsonify({"error": "Job no encontrado"}), 404
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001, threaded=True)
