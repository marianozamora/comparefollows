"""Jobs en segundo plano para consultar perfiles (estado en memoria)."""
import logging
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime

import requests as http

import cache
import instagram

log = logging.getLogger("comparefollows.jobs")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{1,30}$")
MAX_JOBS    = 20   # jobs terminados que se conservan en memoria

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def clean_usernames(usernames) -> list[str]:
    """Deduplica y descarta lo que no parezca un username de Instagram."""
    if not isinstance(usernames, list):
        return []
    return [u for u in dict.fromkeys(usernames) if isinstance(u, str) and USERNAME_RE.match(u)]


def create(usernames: list[str]) -> tuple[str, dict]:
    job_id = uuid.uuid4().hex
    job = {
        "total": len(usernames), "done": 0, "results": {},
        "running": True, "paused": False, "stopped": False,
        "error": None, "last_error": None,
        "started_at": datetime.now().isoformat(),
    }
    with _lock:
        finished = [k for k, j in _jobs.items() if not j["running"]]
        for k in finished[:max(0, len(_jobs) - MAX_JOBS)]:
            del _jobs[k]
        _jobs[job_id] = job
    return job_id, job


def snapshot(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return None if job is None else {**job, "results": dict(job["results"])}


def stop(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return False
        job["running"] = False
        job["stopped"] = True
        job["paused"]  = False
    return True


def set_paused(job_id: str, paused: bool) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return False
        job["paused"] = bool(paused) and job["running"]
    return True


def start(job: dict, usernames: list[str], session_id: str):
    threading.Thread(target=run, args=(job, usernames, session_id), daemon=True).start()


def _sleep(job: dict, seconds: float):
    """Sleep interrumpible: corta apenas el job se detiene."""
    end = time.monotonic() + seconds
    while job["running"] and time.monotonic() < end:
        time.sleep(min(1, max(0, end - time.monotonic())))


def _wait_unpaused(job: dict):
    while job["paused"] and job["running"]:
        time.sleep(0.25)


def run(job: dict, usernames: list[str], session_id: str):
    session   = instagram.make_session(session_id)
    throttled = 0   # 429 consecutivos → backoff exponencial
    log.info("Job iniciado: %d usuarios", len(usernames))

    for username in usernames:
        _wait_unpaused(job)
        if not job["running"]:
            break

        try:
            profile = cache.get(username)
        except sqlite3.Error:
            log.warning("Caché ilegible", exc_info=True)
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
                profile = instagram.fetch_profile(session, username)
                try:
                    cache.put(username, profile)
                except sqlite3.Error:
                    log.warning("No se pudo guardar en caché", exc_info=True)
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
                    log.warning("429 de Instagram, backoff %ds", wait)
                    with _lock:
                        job["last_error"] = last_error
                    _sleep(job, wait)
                else:
                    last_error = f"HTTP {code}"
                    log.warning("HTTP %s consultando un perfil", code)
                    if attempt < 2:
                        _sleep(job, random.uniform(8, 15))
            except Exception as e:  # red, JSON inválido, etc.
                last_error = f"{type(e).__name__}: {e}"
                log.warning("Error consultando un perfil: %s", last_error)
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
    log.info("Job terminado: %d/%d (detenido=%s)", job["done"], job["total"], job["stopped"])
