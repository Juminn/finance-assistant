"""상품 카탈로그 동기화 — 수집 → 변경분만 임베딩 → 벡터 저장소 반영."""

from dataclasses import dataclass, field

from app.tools.catalog import ProductDoc


@dataclass
class SyncPlan:
    """이번 동기화에서 무엇을 다시 색인하고 무엇을 지울지."""

    to_index: list[ProductDoc] = field(default_factory=list[ProductDoc])
    to_delete: list[str] = field(default_factory=list[str])
    unchanged: int = 0


def plan_sync(docs: list[ProductDoc], existing: dict[str, str]) -> SyncPlan:
    """수집한 문서와 저장소의 (product_key → content_hash)를 비교해 작업을 정한다.

    본문이 그대로인 상품은 건너뛰어 임베딩 호출 비용을 아낀다.
    """
    plan = SyncPlan()
    seen: set[str] = set()

    for doc in docs:
        seen.add(doc.product_key)
        if existing.get(doc.product_key) == doc.content_hash:
            plan.unchanged += 1
        else:
            plan.to_index.append(doc)

    plan.to_delete = [key for key in existing if key not in seen]
    return plan
