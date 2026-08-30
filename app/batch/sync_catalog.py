"""상품 카탈로그를 수집해 벡터 저장소에 색인하는 배치.

실행: uv run python -m app.batch.sync_catalog

- 소스: 금감원 공시(finlife) + 정책대출(서민금융·기금e든든) + 정책지원(보조금24).
  키가 없거나 수집에 실패한 소스는 건너뛰며, plan_sync가 수집된 소스 안에서만
  삭제를 계산하므로 건너뛴 소스의 기존 색인은 보존된다.
- 본문이 바뀐 상품만 다시 임베딩하므로 반복 실행 비용이 거의 없다.
- 청크 단위로 임베딩→저장→커밋을 반복해, 중간에 실패해도 이미 커밋된
  청크는 보존되고 재실행 시 그 지점부터 이어서 진행된다.
"""

import sys
from collections.abc import Callable

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from app.batch.sync import is_mass_deletion, plan_sync
from app.core.config import Settings, get_settings
from app.core.embeddings import embed_texts
from app.db.session import get_engine, get_session_factory, vector_search_enabled
from app.db.vector_repo import delete_keys, ensure_vector_schema, existing_hashes, upsert_docs
from app.tools.catalog import ProductDoc, collect_product_docs
from app.tools.gigeum import fetch_gigeum_tables, gigeum_docs
from app.tools.gov24 import exclude_known_products, fetch_service_details, finance_services
from app.tools.gov24 import gov24_docs as build_gov24_docs
from app.tools.smfg import fetch_policy_loans, policy_loan_docs

_CHUNK = 200


def _collect_docs(client: httpx.Client, settings: Settings) -> list[ProductDoc]:
    """소스별로 수집하되, 한 소스의 실패가 나머지를 막지 않게 한다."""

    def collect_smfg() -> list[ProductDoc]:
        rows = fetch_policy_loans(client, api_key=settings.data_go_kr_api_key)
        return policy_loan_docs(rows)

    def collect_gov24() -> list[ProductDoc]:
        rows = finance_services(fetch_service_details(client, api_key=settings.data_go_kr_api_key))
        # 정책대출 소스와 같은 이름의 서비스(햇살론 등)는 그쪽을 정본으로 남긴다
        known = [doc.name for doc in docs if doc.category == "정책대출"]
        return build_gov24_docs(exclude_known_products(rows, known))

    sources: list[tuple[str, Callable[[], list[ProductDoc]]]] = []
    if settings.finlife_api_key:
        sources.append(
            ("금감원 공시", lambda: collect_product_docs(client, api_key=settings.finlife_api_key))
        )
    else:
        print("FINLIFE_API_KEY가 없어 금감원 공시 수집을 건너뜁니다.")
    if settings.data_go_kr_api_key:
        sources.append(("정책대출(서민금융)", collect_smfg))
    else:
        print("DATA_GO_KR_API_KEY가 없어 정책대출·정책지원 수집을 건너뜁니다.")
    sources.append(("정책대출(기금e든든)", lambda: gigeum_docs(*fetch_gigeum_tables(client))))
    if settings.data_go_kr_api_key:
        # 정책대출 수집 뒤에 실행돼야 중복 상품명을 알 수 있다
        sources.append(("정책지원(보조금24)", collect_gov24))

    docs: list[ProductDoc] = []
    for name, collect in sources:
        try:
            collected = collect()
        except Exception as exc:  # 한 소스 장애로 배치 전체를 멈추지 않는다
            print(f"{name} 수집 실패 — 건너뜁니다: {exc}")
            continue
        print(f"{name}: {len(collected)}건")
        docs.extend(collected)
    return docs


def main() -> int:
    load_dotenv()
    settings = get_settings()

    if not settings.openai_api_key:
        print("OPENAI_API_KEY가 .env에 없습니다.")
        return 1
    if not vector_search_enabled():
        print("DATABASE_URL이 PostgreSQL이 아닙니다. Neon 연결 문자열을 .env에 넣어주세요.")
        return 1

    ensure_vector_schema(get_engine())

    with httpx.Client(timeout=30) as client:
        docs = _collect_docs(client, settings)
    if not docs:
        print("수집된 상품이 없습니다. 인증키와 네트워크를 확인하세요.")
        return 1
    print(f"상품 수집: {len(docs)}건")

    session_factory = get_session_factory()
    with session_factory() as db:
        existing = existing_hashes(db)
    existing_count = len(existing)
    plan = plan_sync(docs, existing)
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

    if plan.to_delete and is_mass_deletion(len(plan.to_delete), existing_count=existing_count):
        print(
            f"삭제 {len(plan.to_delete)}건은 기존 색인 {existing_count}건에 비해 과도합니다."
            " 수집이 일부만 된 것으로 보고 삭제를 건너뜁니다."
        )
    elif plan.to_delete:
        with session_factory() as db:
            delete_keys(db, plan.to_delete)
            db.commit()

    print("색인 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
