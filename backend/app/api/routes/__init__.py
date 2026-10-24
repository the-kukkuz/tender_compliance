"""Route module exports for Bid2Work AI."""

from app.api.routes.analysis import router as analysis_router
from app.api.routes.audit import router as audit_router
from app.api.routes.auth import router as auth_router
from app.api.routes.compliance import router as compliance_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.permit import router as permit_router
from app.api.routes.profile import router as profile_router
from app.api.routes.reports import router as reports_router
from app.api.routes.tenders import router as tenders_router

__all__ = [
    "health_router",
    "documents_router",
    "analysis_router",
    "compliance_router",
    "permit_router",
    "audit_router",
    "reports_router",
    "auth_router",
    "profile_router",
    "tenders_router",
]

