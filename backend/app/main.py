"""FastAPI entrypoint for Bid2Work AI — Tender Compliance and Work-Permit Readiness Intelligence."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    analysis_router,
    audit_router,
    auth_router,
    compliance_router,
    documents_router,
    health_router,
    permit_router,
    profile_router,
    reports_router,
    tenders_router,
)
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger, set_request_id
from app.db.sqlite import init_sqlite_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle tasks."""
    settings = get_settings()
    configure_logging(settings.log_level)

    # Ensure temporary upload directory exists
    temp_dir = Path(settings.temp_upload_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Initialize lightweight SQLite audit table
    db_initialized = init_sqlite_db(settings.sqlite_db_path)
    logger.info(
        f"Starting {settings.app_name} v{settings.app_version} ({settings.app_env})",
        extra={
            "extra_fields": {
                "sqlite_ready": db_initialized,
                "llm_configured": settings.is_llm_configured,
                "max_upload_size_mb": settings.max_upload_size_mb,
            }
        },
    )
    yield
    logger.info(f"Shutting down {settings.app_name}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Decision-support intelligence for tender compliance analysis and "
            "post-award work-permit readiness verification."
        ),
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Environment-driven CORS configuration
    allowed_origins = settings.cors_allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins if allowed_origins else ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context_middleware(
        request: Request, call_next
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or f"REQ-{uuid.uuid4().hex[:10].upper()}"
        set_request_id(req_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

    register_exception_handlers(app)

    # Mount routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(tenders_router)
    app.include_router(documents_router)
    app.include_router(analysis_router)
    app.include_router(compliance_router)
    app.include_router(permit_router)
    app.include_router(audit_router)
    app.include_router(reports_router)

    # Mount compiled frontend static build (for single-service deployment)
    candidate_dist_dirs = [
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
        Path.cwd() / "dist",
    ]
    dist_dir = next((d for d in candidate_dist_dirs if d.is_dir()), None)

    if dist_dir:
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static_assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa_frontend(full_path: str):
            # Do not intercept API or documentation routes
            if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
                return Response(status_code=404)
            file_target = dist_dir / full_path
            if file_target.is_file():
                return FileResponse(file_target)
            return FileResponse(dist_dir / "index.html")

    return app


app = create_app()
