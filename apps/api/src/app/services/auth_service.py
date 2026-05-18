"""Local file-backed authentication for the MVP.

Reads sample credentials from ``policies/users.json``. Verification uses
constant-time comparison to avoid trivial timing leaks. Replace this
module with an Entra ID / OAuth integration before deploying anywhere
beyond localhost.
"""

from __future__ import annotations

import hmac
import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

USERS_FILE = Path(__file__).resolve().parent.parent / "policies" / "users.json"


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
    }


def issue_token() -> str:
    """Opaque session token. Not validated server-side in the MVP — the
    client just stores it for display. Replace with a real JWT once the
    auth flow upgrades to Entra ID."""
    return secrets.token_urlsafe(32)
