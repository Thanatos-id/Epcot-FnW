from collections.abc import Iterator

from fastapi import Request
from posthog import Posthog
from sqlalchemy.orm import Session

from epcot_fw.db.base import SessionLocal


def get_posthog_client(request: Request) -> Posthog | None:
    # Not a plain attribute read: `main.py`'s lifespan is what sets this, to
    # either a real client or explicitly None, and lifespan only runs on a
    # real ASGI startup. TestClient(app) used without `with` - every
    # integration test in this project - never triggers it, so the attribute
    # is simply absent rather than None. getattr matches the same defensive
    # read main.py's own exception handler already uses for this reason.
    return getattr(request.app.state, "posthog_client", None)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
