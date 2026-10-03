"""Compose the asset HTTP API from business-specific route groups."""

from fastapi import APIRouter

from app.domains.asset.routers.assets import catalog, documents, jobs, resolutions, threads

router = APIRouter(tags=["Assets"])
for routes in (catalog, documents, threads, jobs, resolutions):
    router.include_router(routes.router, prefix="/workspaces/{ws_id}/assets")
