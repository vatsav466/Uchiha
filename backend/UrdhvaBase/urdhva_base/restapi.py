"""
restapi.py — FastAPI application factory for urdhva_base services.

How it works:
  • Launched by `python -m urdhva_base` from a service working directory
    (e.g. api_manager/, vendor_ingestion_api/, …).
  • On startup it walks every *.py file in the CWD and imports modules that
    contain a `router` attribute (fastapi.APIRouter), auto-registering them
    under the /api prefix.
  • CORS, session middleware (Redis-backed, Fernet-encrypted cookie), and
    SlowAPI rate-limiting are configured from .alg_env settings.
"""

import os
import sys
import json
import base64
import types
import inspect
import asyncio
import logging
import importlib
import importlib.util
import traceback

import fastapi
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import slowapi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import urdhva_base
import urdhva_base.settings
import urdhva_base.redispool
import urdhva_base.postgresmodel

logger = logging.getLogger("urdhva_base.restapi")

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["1000/minute"])

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title=urdhva_base.settings.app_name,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    # Present API tags (group names) and operations alphabetically so the
    # docs are readable instead of showing router-registration order.
    swagger_ui_parameters={
        "tagsSorter": "alpha",
        "operationsSorter": "alpha",
    },
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allow all origins; in production nginx is the actual gateway so this is safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Session middleware ────────────────────────────────────────────────────────
class SessionMiddleware(BaseHTTPMiddleware):
    """
    Reads the session cookie, decrypts it with Fernet, resolves the full session
    payload (user data) from Redis by cookie_id, and stores it in
    request.state.session. Downstream handlers can read session data via
    request.state.session and urdhva_base.ctx / context['rpt'].
    """

    async def _resolve_session(self, cookie_value: str) -> dict:
        from cryptography.fernet import Fernet, InvalidToken

        try:
            f = Fernet(urdhva_base.settings.fernet_key)
            decrypted = f.decrypt(cookie_value.encode()).decode()
            cookie_payload = json.loads(decrypted)
            cookie_id = cookie_payload.get("cookie_id")
            if not cookie_id:
                return {}

            # The cookie only carries {"entity_id","cookie_id"}; the full user
            # payload lives in Redis under Novex_SessionData_<cookie_id>.
            rkey = f"Novex_SessionData_{cookie_id}"
            redis_ins = await urdhva_base.redispool.get_redis_connection()
            if not await redis_ins.exists(rkey):
                return {}
            raw = await redis_ins.get(rkey)
            session_data = json.loads(base64.urlsafe_b64decode(raw).decode())
            session_data["cookie_id"] = cookie_id
            session_data["entity_id"] = cookie_payload.get("entity_id", "Novex")
            return session_data
        except (InvalidToken, Exception):
            # Invalid / expired session — treat as anonymous
            return {}

    async def dispatch(self, request: Request, call_next):
        session_data = {}
        cookie_value = request.cookies.get(urdhva_base.settings.cookie_name)

        if cookie_value:
            session_data = await self._resolve_session(cookie_value)

        request.state.session = session_data

        # Inject entity context used by ACL helpers
        if session_data:
            try:
                urdhva_base.ctx.set(session_data)
            except Exception:
                pass

        response = await call_next(request)
        return response


app.add_middleware(SessionMiddleware)


# ── /api/session/me ──────────────────────────────────────────────────────────
@app.get("/api/session/me", tags=["Session"])
async def session_me(request: Request):
    """
    Returns the resolved session payload (full user info) if a valid session
    cookie is present, or is_authenticated: false otherwise.
    """
    session = getattr(request.state, "session", {})
    if not session or not session.get("employee_id"):
        return JSONResponse({"is_authenticated": False}, status_code=200)
    return JSONResponse({**session, "is_authenticated": True}, status_code=200)


# ── /api/logout ───────────────────────────────────────────────────────────────
@app.get("/api/logout", tags=["Session"])
async def logout(request: Request):
    """Clear the session cookie."""
    response = JSONResponse({"status": True, "msg": "Logged out"})
    response.delete_cookie(urdhva_base.settings.cookie_name)
    return response


# ── /api/health ───────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["Health"])
async def health():
    """Quick liveness probe — returns 200 if the process is up."""
    return {"status": "ok"}


# ── Router auto-discovery ────────────────────────────────────────────────────
def _load_routers(app: FastAPI):
    """
    Walk every .py file in the current working directory (i.e. the service
    folder) and include any fastapi.APIRouter found as `router` or nested
    inside sub-modules.
    """
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    loaded = 0
    errors = 0

    for filename in sorted(os.listdir(cwd)):
        if not filename.endswith(".py"):
            continue
        if filename.startswith("_"):
            continue

        module_name = filename[:-3]

        try:
            # IMPORTANT: use the normal import machinery (importlib.import_module),
            # not a hand-rolled spec_from_file_location + exec_module. Many of these
            # files (e.g. hpcl_ceg_model.py) are ALSO imported normally by other
            # action files via `from hpcl_ceg_model import *`. If we re-exec them
            # here with a fresh module object, they run a second time, which
            # re-registers SQLAlchemy tables against the same shared metadata
            # ("Table 'x' is already defined for this MetaData instance") and can
            # leave a half-initialized module in sys.modules for anyone who
            # imports it afterwards — causing unrelated NameErrors elsewhere.
            # importlib.import_module() respects sys.modules, so each file is
            # only ever executed once no matter how many times it's referenced.
            mod = importlib.import_module(module_name)

            # Include top-level router attribute
            symbol = getattr(mod, "router", None)
            if isinstance(symbol, fastapi.routing.APIRouter):
                app.include_router(symbol, prefix="/api")
                logger.info(f"  ✓ router from {filename}")
                loaded += 1
                continue

            # Also scan sub-attributes for routers (some modules nest them)
            for attr_name in dir(mod):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(mod, attr_name, None)
                if isinstance(attr, fastapi.routing.APIRouter):
                    app.include_router(attr, prefix="/api")
                    logger.info(f"  ✓ router '{attr_name}' from {filename}")
                    loaded += 1

        except Exception as exc:
            errors += 1
            logger.warning(f"  ✗ failed to load {filename}: {exc}")
            if True:  # always log tracebacks for router load failures
                traceback.print_exc()

    logger.info(f"Router discovery: {loaded} loaded, {errors} skipped")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    logger.info(f"Starting {urdhva_base.settings.app_name} …")

    # Ensure DB tables exist
    try:
        await urdhva_base.postgresmodel.create_tables()
        logger.info("DB tables verified/created")
    except Exception as exc:
        logger.warning(f"DB table creation failed (non-fatal): {exc}")

    # Warm up Redis connection pool
    try:
        redis = await urdhva_base.redispool.get_redis_connection()
        await redis.ping()
        logger.info("Redis connection pool warmed up")
    except Exception as exc:
        logger.warning(f"Redis warm-up failed (non-fatal): {exc}")

    logger.info("Startup complete")


# ── Load routers at import time ───────────────────────────────────────────────
# (Runs when uvicorn imports this module, which is after sys.path is set.)
_load_routers(app)
