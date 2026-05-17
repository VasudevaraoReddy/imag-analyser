from __future__ import annotations

import logging
import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routers import analyze, chat, health


def _configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def create_app() -> FastAPI:
    _configure_logging()
    settings = get_settings()
    app = FastAPI(title="Bank Architecture Diagram Analyzer", version="0.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    log = structlog.get_logger()

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            log.exception("unhandled_error", error=str(exc), path=str(request.url))
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": str(exc),
                         "request_id": request_id},
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "request",
            method=request.method,
            path=str(request.url.path),
            status=response.status_code,
            duration_ms=elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id
        structlog.contextvars.clear_contextvars()
        return response

    @app.middleware("http")
    async def enforce_upload_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
        max_bytes = settings.max_upload_mb * 1024 * 1024
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "payload_too_large",
                            "message": f"Upload exceeds {settings.max_upload_mb} MB.",
                        },
                    )
            except ValueError:
                pass
        return await call_next(request)

    app.include_router(health.router, prefix="/api")
    app.include_router(analyze.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    # TODO(auth): add Entra ID / OAuth middleware here before exposing
    # this service to non-localhost traffic.

    return app


app = create_app()
