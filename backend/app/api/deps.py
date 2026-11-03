"""Shared API dependencies."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..db.session import get_session

def db_session() -> Iterator[Session]:
    yield from get_session()
