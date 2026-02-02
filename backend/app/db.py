from __future__ import annotations

from sqlmodel import SQLModel, Session, create_engine

from .config import settings


def get_engine():
    # check_same_thread=False enables SQLite access from FastAPI threads
    url = f"sqlite:///{settings.sqlite_path}"
    return create_engine(url, connect_args={"check_same_thread": False})


engine = get_engine()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
