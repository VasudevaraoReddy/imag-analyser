import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.storage import next_arc_number


def _seed(tmp_path: Path, arcs: list[str]) -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    # Redirect storage to tmp via env override
    import os
    os.environ["DATA_DIR"] = str(tmp_path)
    s = get_settings()
    s.analyses_dir.mkdir(parents=True, exist_ok=True)
    for i, arc in enumerate(arcs):
        (s.analyses_dir / f"{i:08d}.json").write_text(json.dumps({"arc_number": arc}))


def test_first_arc_of_month_is_001(tmp_path: Path) -> None:
    _seed(tmp_path, [])
    n = next_arc_number(datetime(2026, 5, 17, tzinfo=timezone.utc))
    assert n == "ARC-202605-001"


def test_increments_within_month(tmp_path: Path) -> None:
    _seed(tmp_path, ["ARC-202605-001", "ARC-202605-002", "ARC-202605-007"])
    n = next_arc_number(datetime(2026, 5, 17, tzinfo=timezone.utc))
    assert n == "ARC-202605-008"


def test_resets_for_new_month(tmp_path: Path) -> None:
    _seed(tmp_path, ["ARC-202605-001", "ARC-202605-002"])
    n = next_arc_number(datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert n == "ARC-202606-001"


def test_ignores_malformed_arc_numbers(tmp_path: Path) -> None:
    _seed(tmp_path, ["ARC-202605-001", "not-an-arc", "ARC-xxxxxx-002", ""])
    n = next_arc_number(datetime(2026, 5, 17, tzinfo=timezone.utc))
    assert n == "ARC-202605-002"


def test_handles_three_digit_padding(tmp_path: Path) -> None:
    _seed(tmp_path, [f"ARC-202605-{i:03d}" for i in range(1, 1000)])
    n = next_arc_number(datetime(2026, 5, 17, tzinfo=timezone.utc))
    assert n == "ARC-202605-1000"
