"""상품 카탈로그 동기화 계획 — 수집 결과와 기존 색인을 비교해 작업을 정한다."""

from dataclasses import dataclass, field

from app.tools.catalog import ProductDoc


@dataclass
class SyncPlan:
    """이번 동기화에서 무엇을 다시 색인하고 무엇을 지울지."""

    to_index: list[ProductDoc] = field(default_factory=list[ProductDoc])
    to_delete: list[str] = field(default_factory=list[str])
    unchanged: int = 0


# 한 권역 응답이 조용히 비어 오면 그 권역 상품 전체가 삭제 대상이 된다.
# 정상적인 월 단위 변동폭을 크게 넘는 삭제는 사고로 보고 막는다.
_MAX_DELETE_RATIO = 0.2


def is_mass_deletion(delete_count: int, *, existing_count: int) -> bool:
    """이번 삭제가 기존 색인 규모에 비해 비정상적으로 큰지."""
    if delete_count == 0 or existing_count == 0:
        return False
    return delete_count > existing_count * _MAX_DELETE_RATIO


def _slug(product_key: str) -> str:
    return product_key.split(":", 1)[0]


def plan_sync(docs: list[ProductDoc], existing: dict[str, str]) -> SyncPlan:
    """수집한 문서와 저장소의 (product_key → content_hash)를 비교해 작업을 정한다.

    - 본문이 그대로인 상품은 건너뛰어 임베딩 호출 비용을 아낀다.
    - 삭제는 **이번에 실제로 수집된 카테고리** 안에서 사라진 키만 대상으로 한다.
      일시 장애로 특정 카테고리가 0건으로 오거나 일부만 수집된 경우에
      기존 색인이 통째로 삭제되는 사고를 막기 위한 안전장치다.
    """
    plan = SyncPlan()
    seen: set[str] = set()
    collected_slugs: set[str] = set()

    for doc in docs:
        seen.add(doc.product_key)
        collected_slugs.add(_slug(doc.product_key))
        if existing.get(doc.product_key) == doc.content_hash:
            plan.unchanged += 1
        else:
            plan.to_index.append(doc)

    plan.to_delete = [key for key in existing if key not in seen and _slug(key) in collected_slugs]
    return plan
