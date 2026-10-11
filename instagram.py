"""Cliente mínimo de la API web de Instagram."""
import requests as http


def make_session(session_id: str) -> http.Session:
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


def fetch_profile(session: http.Session, username: str) -> dict:
    """Perfil público. followers == -1 significa 'no disponible'."""
    resp = session.get(
        "https://i.instagram.com/api/v1/users/web_profile_info/",
        params={"username": username}, timeout=15,
    )
    if resp.status_code == 404:
        return {"followers": -1, "following": 0, "posts": 0, "verified": False}
    resp.raise_for_status()
    user = resp.json().get("data", {}).get("user")
    if not user:
        return {"followers": -1, "following": 0, "posts": 0, "verified": False}
    return {
        "followers": user.get("edge_followed_by", {}).get("count", 0),
        "following": user.get("edge_follow",      {}).get("count", 0),
        "posts":     user.get("edge_owner_to_timeline_media", {}).get("count", 0),
        "verified":  user.get("is_verified", False),
    }
