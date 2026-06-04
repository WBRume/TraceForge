"""
API MOCK Collab Service.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.domains.api_mock.models.api_mock import ApiMockCollabEventType, SddApiMockCollabEvent, SddApiMockProject
from .endpoint_service import get_endpoint


def list_collab_events(
    db: Session,
    project: SddApiMockProject,
    *,
    limit: int = 100,
) -> List[SddApiMockCollabEvent]:
    return (
        db.query(SddApiMockCollabEvent)
        .filter(SddApiMockCollabEvent.project_id == project.id)
        .order_by(SddApiMockCollabEvent.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def create_collab_event(
    db: Session,
    project: SddApiMockProject,
    *,
    user_id: str,
    event_type: ApiMockCollabEventType,
    endpoint_id: Optional[str],
    payload: Optional[Dict[str, Any]],
) -> SddApiMockCollabEvent:
    if endpoint_id:
        endpoint = get_endpoint(db, project, endpoint_id)
        if not endpoint:
            raise ValueError("Endpoint not found")

    event = SddApiMockCollabEvent(
        project_id=project.id,
        endpoint_id=endpoint_id,
        user_id=user_id,
        event_type=event_type,
        payload_json=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
