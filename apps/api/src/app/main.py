from __future__ import annotations

import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .logging_setup import configure_logging, get_logger
from .routers import admin, analyze, auth, chat, health
from .services.auth_service import extract_bearer, user_for_token


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title="Bank Architecture Diagram Analyzer", version="0.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    log = get_logger("http")

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Prefer client-supplied X-Request-ID so a frontend can correlate
        # its requests with backend logs. Otherwise mint a new uuid.
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        # Pull the bearer token and resolve the user — bind employee_id
        # to the log context so every downstream log line for THIS request
        # is attributable. Failure is silent (anonymous request).
        bound_user: dict | None = None
        try:
            token = extract_bearer(request.headers.get("authorization"))
            if token:
                bound_user = user_for_token(token)
        except Exception:  # noqa: BLE001
            bound_user = None
        ctx = {"request_id": request_id}
        if bound_user is not None:
            ctx["employee_id"] = bound_user.get("employee_id") or ""
            ctx["employee_name"] = bound_user.get("name") or ""
            ctx["is_admin"] = bool(bound_user.get("is_admin"))
        structlog.contextvars.bind_contextvars(**ctx)
        # Length is useful when diagnosing 413s vs payload-shape issues.
        content_length = request.headers.get("content-length", "")
        log.info(
            "http.request.begin",
            method=request.method,
            path=str(request.url.path),
            query=str(request.url.query) or None,
            client=f"{request.client.host}:{request.client.port}" if request.client else None,
            content_length=int(content_length) if content_length.isdigit() else None,
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            log.exception(
                "http.request.error",
                error=str(exc),
                error_type=type(exc).__name__,
                path=str(request.url.path),
                duration_ms=elapsed_ms,
            )
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": str(exc),
                         "request_id": request_id},
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "http.request.end",
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
    app.include_router(auth.router, prefix="/api")
    app.include_router(analyze.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    # TODO(auth): add Entra ID / OAuth middleware here before exposing
    # this service to non-localhost traffic.

    return app


app = create_app()
