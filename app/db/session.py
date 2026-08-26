"""앱 전역 DB 엔진의 단일 소유 지점.

API·에이전트 도구·배치가 전부 여기서 엔진을 얻으므로, 테스트나 앱이
set_engine()으로 주입하면 모든 경로가 같은 DB를 본다.
"""

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import make_engine

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def set_engine(engine: Engine | None) -> None:
    """엔진을 교체(또는 None으로 초기화)한다. 세션 팩토리도 함께 리셋된다."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory


def vector_search_enabled() -> bool:
    """벡터 검색(pgvector) 사용 가능 여부 — 판정 기준은 실제 엔진의 방언 하나뿐."""
    return get_engine().dialect.name == "postgresql"
