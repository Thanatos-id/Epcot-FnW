from collections.abc import Iterator

from sqlalchemy.orm import Session

from epcot_fw.db.base import SessionLocal


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
