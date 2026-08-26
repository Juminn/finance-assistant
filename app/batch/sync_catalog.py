"""상품 카탈로그를 수집해 벡터 저장소에 색인하는 배치.

실행: uv run python -m app.batch.sync_catalog

본문이 바뀐 상품만 다시 임베딩하므로, 반복 실행해도 비용이 거의 들지 않는다.
"""

import sys

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from app.batch.sync import plan_sync
from app.core.config import get_settings
from app.core.embeddings import embed_texts
from app.db.base import is_postgres
from app.db.session import get_engine, get_session_factory
from app.db.vector_repo import (
    delete_keys,
    ensure_vector_schema,
    existing_hashes,
    upsert_docs,
)
from app.tools.catalog import collect_product_docs


def main() -> int:
    load_dotenv()
    settings = get_settings()

    if not settings.finlife_api_key:
        print("FINLIFE_API_KEY가 .env에 없습니다.")
        return 1
    if not settings.openai_api_key:
        print("OPENAI_API_KEY가 .env에 없습니다.")
        return 1
    if not is_postgres(settings.database_url):
        print("DATABASE_URL이 PostgreSQL이 아닙니다. Neon 연결 문자열을 .env에 넣어주세요.")
        return 1

    ensure_vector_schema(get_engine())

    with httpx.Client(timeout=20) as client:
        docs = collect_product_docs(client, api_key=settings.finlife_api_key)
    print(f"상품 수집: {len(docs)}건")

    with get_session_factory()() as db:
        plan = plan_sync(docs, existing_hashes(db))
        print(
            f"신규·변경 {len(plan.to_index)}건 / 그대로 {plan.unchanged}건"
            f" / 삭제 {len(plan.to_delete)}건"
        )

        if plan.to_index:
            vectors = embed_texts(
                OpenAI(api_key=settings.openai_api_key), [doc.text for doc in plan.to_index]
            )
            upsert_docs(db, list(zip(plan.to_index, vectors, strict=True)))
        delete_keys(db, plan.to_delete)
        db.commit()

    print("색인 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
