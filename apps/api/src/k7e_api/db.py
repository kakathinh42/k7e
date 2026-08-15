from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from k7e_api.config import get_settings

engine = create_engine(get_settings().database_url, future=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False, class_=Session)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
