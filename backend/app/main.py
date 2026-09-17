"""FIRETRACE FastAPI application."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import settings
from app.services.classifier import get_classifier
from app.services.snapshot import load_snapshot, snapshot_available
from app.store.db import get_store


def configure_logging() -> None:
    """Readable, tagged log lines: [FIRMS], [OSM], [ML], [PIPELINE], [FALLBACK]."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s %(name)-20s %(message)s", "%H:%M:%S")
    )
    # httpx logs the full request URL at INFO level, which for FIRMS would
    # print the MAP_KEY to the console. Silence it below WARNING.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root = logging.getLogger("firetrace")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    root.propagate = False


log = logging.getLogger("firetrace.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the expensive singletons once, at startup, not per request."""
    configure_logging()
    log.info("[STARTUP] %s v%s", settings.app_name, settings.app_version)

    store = get_store()
    log.info(
        "[STARTUP] store ready=%s events=%d facilities=%d",
        store.ready,
        store.event_count(),
        store.facility_count(),
    )

    classifier = get_classifier()
    log.info("[STARTUP] model loaded=%s (%s)", classifier.loaded, classifier.status_note)

    if snapshot_available():
        snap = load_snapshot()
        if snap:
            log.info(
                "[STARTUP] snapshot events=%d facilities=%d captured=%s",
                len(snap.events),
                len(snap.facilities),
                snap.captured_at,
            )
    else:
        log.warning("[STARTUP] no demo snapshot present; run `python -m ml.build_snapshot`")

    if settings.has_firms_key:
        log.info("[STARTUP] NASA FIRMS key configured (value never logged)")
    else:
        log.warning("[STARTUP] NASA FIRMS key NOT configured; live mode unavailable")

    yield
    log.info("[SHUTDOWN] FIRETRACE stopped")


app = FastAPI(
    title="FIRETRACE API",
    version=settings.app_version,
    description=(
        "AI-assisted detection and classification of industrial fires and persistent "
        "thermal sources from NASA FIRMS, OpenStreetMap and land-use data. "
        "Classifications are model-derived likelihoods, not confirmed ground truth."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace (or anything resembling a key) to a client."""
    log.exception("[API] unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "FIRETRACE hit an internal error handling this request. "
                "The server log has the details."
            ),
            "error_type": type(exc).__name__,
        },
    )


app.include_router(router)


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "Industrial thermal event monitoring — SIH 2026 PS 26162",
        "docs": "/docs",
        "health": "/health",
    }
