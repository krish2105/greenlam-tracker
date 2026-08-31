"""FastAPI application.

Everything is mounted under `/api` so a single origin can serve the PWA at `/`
and the API at `/api/*`. That is what makes a first-party httpOnly refresh
cookie possible, which is what keeps the session out of reach of JavaScript.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routers import (
    auth,
    exports,
    health,
    imports,
    impregnation,
    masters,
    people,
    production,
    qr,
    tickets,
)

settings = get_settings()
logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
log = logging.getLogger("gmt.api")

app = FastAPI(
    title="Greenlam Maintenance & Production Intelligence System",
    description=(
        "Offline-first maintenance breakdown and production tracking. "
        "Phase 1: health, PIN auth, role gates, masters CRUD."
    ),
    version="0.1.0",
    root_path="/api",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# Empty by default: the same-origin deployment does not need CORS at all.
# Populate CORS_ORIGINS only for a split-origin dev setup.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the refresh cookie
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers the API itself must send.

    The page-level CSP lives with the static site (see Caddyfile / render.yaml)
    because that is what serves HTML. These are the ones that matter for a JSON
    API: stop MIME sniffing, stop framing, and do not leak the URL on
    cross-origin navigation.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace to the floor. Log it, return something a person
    can act on."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong at our end. Try again."},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(masters.router)
app.include_router(tickets.router)
app.include_router(people.router)
app.include_router(production.router)
app.include_router(qr.router)
app.include_router(imports.router)
app.include_router(impregnation.router)
app.include_router(exports.router)
