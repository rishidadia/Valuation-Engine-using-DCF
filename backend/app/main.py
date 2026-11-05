"""DCF labs — FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes_company import router as company_router
from .api.routes_valuation import router as valuation_router
from .core.config import settings
from .core.errors import AppError
from .core.security import PUBLIC_PATHS, configured_keys, set_tenant, tenant_for_key
from .db.session import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("dcf_labs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("DCF labs started (env=%s, db=%s)", settings.environment,
                settings.database_url.split("://")[0])
    yield


app = FastAPI(
    title="DCF labs",
    description="Computational Valuation Engine — agentic DCF valuation with full auditability.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    """Require X-API-Key when keys are configured; no-op for local use."""
    path = request.url.path
    if (not configured_keys() or not path.startswith("/api")
            or path in PUBLIC_PATHS or request.method == "OPTIONS"):
        set_tenant(None)
        return await call_next(request)

    tenant = tenant_for_key(request.headers.get("x-api-key", ""))
    if tenant is None:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized",
                     "detail": "Missing or invalid X-API-Key header."},
        )
    set_tenant(tenant)
    return await call_next(request)


# Registered after the auth middleware so CORS stays outermost and even 401
# responses carry the CORS headers a browser needs to read them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.get("/api/health", tags=["meta"])
def health():
    from .data.providers import _REGISTRY
    return {
        "status": "ok",
        "app": settings.app_name,
        "database": settings.database_url.split("://")[0],
        "providers": sorted(_REGISTRY),
    }


@app.get("/api/meta/source-types", tags=["meta"])
def source_types():
    from .schemas.common import SourceType
    return {"source_types": [s.value for s in SourceType]}


app.include_router(company_router)
app.include_router(valuation_router)
