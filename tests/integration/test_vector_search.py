"""pgvector 조건 검색 통합 테스트.

DATABASE_URL이 PostgreSQL(Neon)이고 색인이 채워져 있을 때만 실행된다.
실행: uv run pytest -m integration -s
"""

import pytest
from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.embeddings import embed_texts
from app.db.base import is_postgres
from app.db.session import get_engine
from app.db.vector_repo import ensure_vector_schema, existing_hashes, search_similar

pytestmark = pytest.mark.integration


def test_조건_문장으로_유사한_상품을_찾는다() -> None:
    settings = get_settings()
    if not is_postgres(settings.database_url):
        pytest.skip("DATABASE_URL이 PostgreSQL이 아님 — Neon 연결 문자열 필요")
    if not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY 없음")

    engine = get_engine()
    ensure_vector_schema(engine)

    with Session(engine) as db:
        if not existing_hashes(db):
            pytest.skip("색인이 비어 있음 — uv run python -m app.batch.sync_catalog 먼저 실행")

        query = "급여이체 우대금리를 주는 적금"
        vector = embed_texts(OpenAI(api_key=settings.openai_api_key), [query])[0]
        matches = search_similar(db, vector, top_k=3)

        assert matches, "유사 상품이 최소 1건은 나와야 한다"
        distances = [distance for _, distance in matches]
        assert distances == sorted(distances), "가까운 순으로 정렬되어야 한다"

        top, distance = matches[0]
        print(f"\n질의: {query}\n1위: [{top.category}] {top.bank} {top.name} (거리 {distance:.3f})")


def test_카테고리로_검색_범위를_좁힌다() -> None:
    settings = get_settings()
    if not is_postgres(settings.database_url) or not settings.openai_api_key:
        pytest.skip("Neon DATABASE_URL과 OPENAI_API_KEY 필요")

    engine = get_engine()
    ensure_vector_schema(engine)

    with Session(engine) as db:
        if not existing_hashes(db):
            pytest.skip("색인이 비어 있음")

        vector = embed_texts(OpenAI(api_key=settings.openai_api_key), ["중도상환수수료 없는"])[0]
        matches = search_similar(db, vector, top_k=3, category="주택담보대출")

        assert all(row.category == "주택담보대출" for row, _ in matches)
