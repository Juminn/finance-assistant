"""대화 체크포인트 저장소 선택 — DATABASE_URL이 PostgreSQL이면 DB에 영속한다.

체크포인트가 프로세스 메모리에만 있으면 배포·재시작마다 멀티턴 문맥이
사라지는데, 대화 원문은 DB에 남아 /history에는 전체 이력이 보이므로
에이전트만 첫 턴처럼 행동하는 어긋남이 생긴다. 앱 데이터와 같은 DB에
체크포인트를 두면 두 저장소가 함께 살고 함께 사라진다.
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.db.base import is_postgres, to_psycopg_conninfo


def _postgres_checkpointer(url: str) -> BaseCheckpointSaver[Any]:
    # psycopg 계열은 Postgres를 쓸 때만 필요하므로 지연 임포트한다
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # autocommit·dict_row·prepare_threshold=0은 PostgresSaver가 요구하는 커넥션 설정.
    # check는 make_engine의 pool_pre_ping과 같은 역할 — Neon이 유휴 시 컴퓨트를
    # 내려 끊어진 커넥션을 꺼내 쓰기 전에 걸러낸다.
    pool: ConnectionPool[Any] = ConnectionPool(
        to_psycopg_conninfo(url),
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        check=ConnectionPool.check_connection,
    )
    saver = PostgresSaver(pool)  # pyright: ignore[reportArgumentType]
    saver.setup()  # 체크포인트 테이블 생성·마이그레이션. 이미 있으면 그대로 지나간다.
    return saver


def make_checkpointer(url: str) -> BaseCheckpointSaver[Any]:
    """PostgreSQL이면 영속 체크포인터, 아니면 프로세스 메모리.

    메모리 폴백에서는 재시작 시 멀티턴 문맥이 사라진다 — SQLite 환경은
    개발·테스트 전용이라는 전제다.
    """
    if is_postgres(url):
        return _postgres_checkpointer(url)
    return MemorySaver()
