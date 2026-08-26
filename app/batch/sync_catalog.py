"""상품 카탈로그를 수집해 벡터 저장소에 색인하는 배치.

실행: uv run python -m app.batch.sync_catalog

- 본문이 바뀐 상품만 다시 임베딩하므로 반복 실행 비용이 거의 없다.
- 청크 단위로 임베딩→저장→커밋을 반복해, 중간에 실패해도 이미 커밋된
  청크는 보존되고 재실행 시 그 지점부터 이어서 진행된다.
"""

import sys

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from app.batch.sync import plan_sync
from app.core.config import get_settings
from app.core.embeddings import embed_texts
from app.db.session import get_engine, get_session_factory, vector_search_enabled
from app.db.vector_repo import delete_keys, ensure_vector_schema, existing_hashes, upsert_docs
from app.tools.catalog import collect_product_docs

_CHUNK = 200


def main() -> int:
    load_dotenv()
    settings = get_settings()

    if not settings.finlife_api_key:
        print("FINLIFE_API_KEY가 .env에 없습니다.")
        return 1
    if not settings.openai_api_key:
        print("OPENAI_API_KEY가 .env에 없습니다.")
        return 1
    if not vector_search_enabled():
        print("DATABASE_URL이 PostgreSQL이 아닙니다. Neon 연결 문자열을 .env에 넣어주세요.")
        return 1

    ensure_vector_schema(get_engine())

    with httpx.Client(timeout=20) as client:
        docs = collect_product_docs(client, api_key=settings.finlife_api_key)
    print(f"상품 수집: {len(docs)}건")

    session_factory = get_session_factory()
    with session_factory() as db:
        plan = plan_sync(docs, existing_hashes(db))
    print(
        f"신규·변경 {len(plan.to_index)}건 / 그대로 {plan.unchanged}건"
        f" / 삭제 {len(plan.to_delete)}건"
    )

    openai_client = OpenAI(api_key=settings.openai_api_key, timeout=60)
    for start in range(0, len(plan.to_index), _CHUNK):
        chunk = plan.to_index[start : start + _CHUNK]
        vectors = embed_texts(openai_client, [doc.text for doc in chunk])
        with session_factory() as db:
            upsert_docs(db, list(zip(chunk, vectors, strict=True)))
            db.commit()
        print(f"색인 진행: {min(start + _CHUNK, len(plan.to_index))}/{len(plan.to_index)}")

    if plan.to_delete:
        with session_factory() as db:
            delete_keys(db, plan.to_delete)
            db.commit()

    print("색인 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
