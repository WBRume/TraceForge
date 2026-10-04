"""asset.routers.assets.transport domain operations."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.core.offload import run_db_txn_with_bind
from app.domains.asset.services.review.errors import ReviewError


class ReviewRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request):
            try:
                return await handler(request)
            except ReviewError as error:
                raise HTTPException(status_code=error.status_code, detail=error.detail) from error

        return handle


async def _run_asset_route_db_txn(db: Session, db_bind: Any, body):
    """Use a worker-thread transaction without carrying the request Session."""
    if db_bind is None:
        return body(db)
    return await run_db_txn_with_bind(db_bind, body)


def _get_db_bind(db: Session) -> Any:
    getter = getattr(db, "get_bind", None)
    return getter() if callable(getter) else None
