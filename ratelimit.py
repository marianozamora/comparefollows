"""Rate limit por IP, en memoria (ventana deslizante)."""
import functools
import threading
import time
from collections import defaultdict, deque

from flask import jsonify, request

hits: dict[tuple, deque] = defaultdict(deque)
_lock = threading.Lock()


def rate_limit(max_calls: int, per_seconds: int = 60):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__name__, request.remote_addr)
            now = time.monotonic()
            with _lock:
                q = hits[key]
                while q and now - q[0] > per_seconds:
                    q.popleft()
                if len(q) >= max_calls:
                    return jsonify({"error": "Demasiadas solicitudes, esperá un momento"}), 429
                q.append(now)
            return fn(*args, **kwargs)
        return wrapper
    return deco
