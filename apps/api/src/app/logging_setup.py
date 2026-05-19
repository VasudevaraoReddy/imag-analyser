"""Central structured-logging configuration.

Every API call, every LLM call, every Azure SDK call, and every service
function emits a JSON-line event to:

  1. stdout  — so `npm run dev` shows it inline
  2. data/logs/api-YYYY-MM-DD.log — rotated daily, 14-day retention

Each event carries a stable ``request_id`` (set by the FastAPI middleware
in main.py) so a single user request can be traced end-to-end through
every service hop.

Use:

    from .logging_setup import get_logger
    log = get_logger()
    log.info("event_name", key=value, ...)

For block timing:

    from .logging_setup import time_block
    with time_block(log, "vision_llm.extract", tile_id=tile.tile_id):
        ...

Output format (one JSON object per line):
    {
      "timestamp": "2026-05-19T04:26:39.482Z",
      "level": "info",
      "event": "vision_llm.call",
      "request_id": "abc123…",
      "mode": "strict_json",
      "payload_bytes": 47208,
      "duration_ms": 4218,
      ...
    }
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Iterator

import structlog

from .config import get_settings

_INITIALIZED = False


def _ensure_log_dir() -> Path:
    p = Path(get_settings().data_dir).resolve() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _build_file_handler() -> TimedRotatingFileHandler:
    """One log file per day, kept for 14 days."""
    path = _ensure_log_dir() / "api.log"
    h = TimedRotatingFileHandler(
        filename=str(path),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
        utc=True,
    )
    h.suffix = "%Y-%m-%d"
    # The file handler emits the pre-rendered JSON line from structlog.
    h.setFormatter(logging.Formatter("%(message)s"))
    return h


def configure_logging() -> None:
    """Idempotent setup. Safe to call multiple times."""
    global _INITIALIZED
    if _INITIALIZED:
        return

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Wipe any handlers configured by libraries (uvicorn etc.) so we own
    # the output format. We add our own stdout handler + file handler.
    for h in list(root.handlers):
        root.removeHandler(h)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stream)
    root.addHandler(_build_file_handler())

    # Quiet down libraries that spam DEBUG/INFO at every HTTP byte.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _INITIALIZED = True
    structlog.get_logger().info(
        "logging.configured",
        log_file=str(_ensure_log_dir() / "api.log"),
        backup_count=14,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger.

    Pass a short name (e.g. 'vision_llm') so events from that module are
    easy to filter with ``jq 'select(.logger == "vision_llm")'``.
    """
    log = structlog.get_logger()
    return log.bind(logger=name) if name else log


@contextmanager
def time_block(log: Any, event: str, **bind: Any) -> Iterator[dict[str, Any]]:
    """Context manager that emits begin/end log events and times the block.

    The yielded dict can be mutated inside the block to attach extra
    fields (e.g. response size) that will appear on the .end event.

    Usage:
        with time_block(log, "vision_llm.extract") as ctx:
            ctx["payload_bytes"] = len(body)
            ...
            ctx["response_chars"] = len(reply)
    """
    extra: dict[str, Any] = {}
    log.info(f"{event}.begin", **bind)
    started = time.perf_counter()
    try:
        yield extra
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log.error(
            f"{event}.error",
            duration_ms=elapsed_ms,
            error=str(exc),
            error_type=type(exc).__name__,
            **bind,
            **extra,
        )
        raise
    else:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            f"{event}.end",
            duration_ms=elapsed_ms,
            **bind,
            **extra,
        )


def safe_preview(text: str | None, limit: int = 2000) -> str:
    """Trim long strings so log lines stay readable."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [+{len(text) - limit} chars]"
