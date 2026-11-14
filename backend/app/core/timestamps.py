"""Serialize UTC timestamps read from the business database."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def utc_isoformat(value: datetime) -> str:
    """Add an explicit offset to a database timestamp or serialize an aware value."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


UtcTimestamp = Annotated[datetime, PlainSerializer(utc_isoformat, return_type=str, when_used="json")]
