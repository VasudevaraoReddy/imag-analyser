"""Local file-backed authentication for the MVP.

Reads sample credentials from ``policies/users.json``. Verification uses
constant-time comparison to avoid trivial timing leaks.

Tokens are now **server-side validated**: when a user signs in we mint
an opaque token and remember which user it belongs to. Subsequent
requests pass the token via ``Authorization: Bearer <token>`` and we
look up the bound user. The in-memory token store is good enough for
the MVP; before any non-localhost deployment, replace this whole
module with Entra ID / OAuth.
"""

from __future__ import annotations

import hmac
import json
import secrets
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

USERS_FILE = Path(__file__).resolve().parent.parent / "policies" / "users.json"

# token → { user, issued_at }
_TOKEN_STORE: dict[str, dict[str, Any]] = {}
_TOKEN_TTL_SECONDS = 60 * 60 * 8  # 8 hours


@lru_cache(maxsize=1)
def _load_users_cached(mtime: float) -> list[dict[str, Any]]:  # noqa: ARG001
    raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return list(raw.get("users", []))


def _load_users() -> list[dict[str, Any]]:
    try:
        mtime = USERS_FILE.stat().st_mtime
    except OSError:
        return []
    return _load_users_cached(mtime)


def find_user(employee_id: str) -> dict[str, Any] | None:
    needle = (employee_id or "").strip().upper()
    for u in _load_users():
        if str(u.get("employee_id", "")).strip().upper() == needle:
            return u
    return None


def verify(employee_id: str, password: str) -> dict[str, Any] | None:
    """Return the public user record on success, ``None`` on failure."""
    user = find_user(employee_id)
    if user is None:
        # Run a dummy compare so timing is uniform on miss vs. hit.
        hmac.compare_digest("a", "b")
        return None
    stored = str(user.get("password", ""))
    if not stored:
        return None
    ok = hmac.compare_digest(stored.encode("utf-8"), password.encode("utf-8"))
    if not ok:
        return None
    return _public_view(user)


def _public_view(u: dict[str, Any]) -> dict[str, Any]:
    """Strip the password before sending back to the client."""
    return {
        "employee_id": u.get("employee_id"),
        "name": u.get("name", ""),
        "role": u.get("role", "viewer"),
        "email": u.get("email", ""),
        "is_admin": bool(u.get("is_admin", False)),
    }


def issue_token(user: dict[str, Any]) -> str:
    """Mint a token bound to the given user record."""
    token = secrets.token_urlsafe(32)
    _TOKEN_STORE[token] = {
        "user": user,
        "issued_at": time.time(),
    }
    return token


def user_for_token(token: str) -> dict[str, Any] | None:
    """Return the public user record for a token, or None if expired/invalid."""
    if not token:
        return None
    entry = _TOKEN_STORE.get(token)
    if entry is None:
        return None
    if time.time() - entry["issued_at"] > _TOKEN_TTL_SECONDS:
        _TOKEN_STORE.pop(token, None)
        return None
    return entry["user"]


def revoke_token(token: str) -> None:
    _TOKEN_STORE.pop(token, None)


def extract_bearer(authorization_header: str | None) -> str | None:
    """Pull the token out of an Authorization header."""
    if not authorization_header:
        return None
    parts = authorization_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
