import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _fixture_users(tmp_path: Path, monkeypatch):
    """Replace the live users.json with a fixed test fixture so these tests
    don't break when an operator edits the production JSON."""
    fake = tmp_path / "users.json"
    fake.write_text(json.dumps({
        "version": 1,
        "users": [
            {
                "employee_id": "TEST001",
                "password": "p@ssword1",
                "name": "Test User",
                "role": "tester",
                "email": "test@example.com",
            },
            {
                "employee_id": "TEST002",
                "password": "AnotherSecret!",
                "name": "Second User",
                "role": "viewer",
                "email": "second@example.com",
            },
        ],
    }))
    monkeypatch.setattr("app.services.auth_service.USERS_FILE", fake)
    from app.services.auth_service import _load_users_cached
    _load_users_cached.cache_clear()
    yield
    _load_users_cached.cache_clear()


def test_find_user_is_case_insensitive():
    from app.services.auth_service import find_user
    u = find_user("test001")
    assert u is not None
    assert u["employee_id"] == "TEST001"


def test_verify_accepts_valid_credentials():
    from app.services.auth_service import verify
    user = verify("TEST001", "p@ssword1")
    assert user is not None
    assert user["employee_id"] == "TEST001"
    assert "password" not in user
    assert user["name"] == "Test User"


def test_verify_rejects_bad_password():
    from app.services.auth_service import verify
    assert verify("TEST001", "wrong-password") is None


def test_verify_rejects_unknown_user():
    from app.services.auth_service import verify
    assert verify("TEST999", "anything") is None


def test_verify_handles_empty_inputs():
    from app.services.auth_service import verify
    assert verify("", "") is None
    assert verify("TEST001", "") is None
