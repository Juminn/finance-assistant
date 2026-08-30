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
from app.db.vector_models import ProductEmbedding
from app.db.vector_repo import ensure_vector_schema, existing_hashes, search_similar
from app.tools.condition import drop_weak_matches, infer_category

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


_RELEVANT = (
    "급여이체 우대금리를 주는 적금",
    "중도상환수수료 없는 주택담보대출",
    "청년 우대 정기예금",
    "마이너스통장 개설 가능한 신용대출",
    "카드 실적 있으면 우대해주는 예금",
)
_OFF_DOMAIN = (
    "오늘 서울 날씨 어때",
    "파이썬 리스트 정렬하는 법",
    "치킨 맛집 추천해줘",
)


def _search(db: Session, client: OpenAI, query: str) -> list[tuple[ProductEmbedding, float]]:
    vector = embed_texts(client, [query])[0]
    return search_similar(db, vector, top_k=5, category=infer_category(query) or None)


def test_도메인_밖_질의는_유사도_기준에서_전부_걸러진다() -> None:
    """임계값이 실제 색인에서 명백한 무관을 걸러내는지 — 회귀하면 억지 추천이 돌아온다."""
    settings = get_settings()
    if not is_postgres(settings.database_url) or not settings.openai_api_key:
        pytest.skip("Neon DATABASE_URL과 OPENAI_API_KEY 필요")

    engine = get_engine()
    ensure_vector_schema(engine)
    client = OpenAI(api_key=settings.openai_api_key)

    with Session(engine) as db:
        if not existing_hashes(db):
            pytest.skip("색인이 비어 있음")
        for query in _OFF_DOMAIN:
            matches = _search(db, client, query)
            assert matches, "검색 자체는 결과를 돌려준다 (임계값이 없으면 이게 그대로 답이 된다)"
            kept = drop_weak_matches(matches)
            sims = [round(1 - d, 3) for _, d in matches]
            assert kept == [], f"{query!r}가 걸러지지 않음 (유사도 {sims})"


def test_관련_질의는_유사도_기준을_통과한다() -> None:
    """임계값이 너무 높아 맞는 상품을 잃지 않는지 — 이쪽 회귀가 더 나쁘다."""
    settings = get_settings()
    if not is_postgres(settings.database_url) or not settings.openai_api_key:
        pytest.skip("Neon DATABASE_URL과 OPENAI_API_KEY 필요")

    engine = get_engine()
    ensure_vector_schema(engine)
    client = OpenAI(api_key=settings.openai_api_key)

    with Session(engine) as db:
        if not existing_hashes(db):
            pytest.skip("색인이 비어 있음")
        for query in _RELEVANT:
            matches = _search(db, client, query)
            kept = drop_weak_matches(matches)
            sims = [round(1 - d, 3) for _, d in matches]
            assert len(kept) == len(matches), f"{query!r}의 결과가 잘렸다 (유사도 {sims})"


def test_청년_적금_질의에_정책_적금이_함께_잡힌다() -> None:
    """정책 예·적금 재분류의 회귀 감시 — 상품명을 대지 않은 대상 계층 질의에서
    적금으로 좁혀 검색해도 정책 상품(보조금24 출처)이 도구의 top_k 안에 들어야 한다."""
    settings = get_settings()
    if not is_postgres(settings.database_url) or not settings.openai_api_key:
        pytest.skip("Neon DATABASE_URL과 OPENAI_API_KEY 필요")

    engine = get_engine()
    ensure_vector_schema(engine)
    client = OpenAI(api_key=settings.openai_api_key)

    with Session(engine) as db:
        if not existing_hashes(db):
            pytest.skip("색인이 비어 있음")
        query = "청년이 금리 좋게 받을 수 있는 적금 알려줘"
        assert infer_category(query) == "적금"
        vector = embed_texts(client, [query])[0]
        matches = search_similar(db, vector, top_k=10, category="적금")  # 도구와 같은 top_k
        kept = drop_weak_matches(matches)
        assert any(row.product_key.startswith("gov24:") for row, _ in kept), (
            f"정책 적금이 잘렸다: {[(row.bank, row.name) for row, _ in kept]}"
        )
