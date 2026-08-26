from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def normalize_db_url(url: str) -> str:
    """Neon 등이 주는 postgresql:// 주소를 psycopg 드라이버용으로 바꾼다."""
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url.removeprefix(scheme)
    return url


def is_postgres(url: str) -> bool:
    return url.startswith(("postgresql://", "postgres://", "postgresql+"))


def make_engine(url: str) -> Engine:
    """SQLite 파일이면 폴더를 만들어주고, 메모리 DB면 커넥션을 공유하게 만든다."""
    if url in ("sqlite://", "sqlite:///:memory:"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    # Neon은 유휴 시 컴퓨트를 내리므로, 끊긴 커넥션을 미리 걸러낸다
    return create_engine(normalize_db_url(url), pool_pre_ping=True)
