"""조건 검색(시맨틱)의 카테고리 추론과 결과 포맷 — 순수 함수."""

from app.db.vector_models import ProductEmbedding

_DETAIL_LIMIT = 400

# 질의문에서 카테고리를 짚는 단서. 카테고리가 지정되지 않으면 이걸로 좁힌다.
# 색인이 커질수록 전체 검색은 무관 카테고리에 밀리므로, 단서가 있으면 쓰는 편이 낫다.
# "신용"·"대출"처럼 여러 카테고리에 걸치는 낱말은 오탐이 커서 단서로 쓰지 않는다.
_CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("정기예금", ("정기예금", "예금")),
    ("적금", ("적금",)),
    ("주택담보대출", ("주택담보", "주담대", "아파트담보", "담보대출")),
    ("전세자금대출", ("전세",)),
    ("개인신용대출", ("개인신용대출", "신용대출", "마이너스통장", "마이너스 통장")),
)


def infer_category(query: str) -> str:
    """질의문에서 카테고리를 하나만 확실히 짚을 수 있으면 그 이름을 반환한다.

    단서가 없거나 둘 이상 걸리면(예: "예금이랑 적금 중에") 좁히지 않고 빈 문자열을
    반환한다. 잘못 좁혀 맞는 상품을 통째로 잃는 쪽이 더 나쁘기 때문이다.
    """
    text = " ".join(query.split())
    hits = {category for category, words in _CATEGORY_HINTS if any(w in text for w in words)}
    return hits.pop() if len(hits) == 1 else ""


def format_matches(matches: list[tuple[ProductEmbedding, float]]) -> str:
    """(문서, 코사인 거리) 목록을 LLM이 인용하기 좋은 텍스트로 만든다."""
    if not matches:
        return "조건에 맞는 상품을 찾지 못했습니다."

    lines = ["조건과 가장 가까운 상품:"]
    for rank, (row, distance) in enumerate(matches, start=1):
        similarity = max(0.0, 1.0 - distance)  # 코사인 거리는 0~2 — 음수 유사도 방지
        lines.append(
            f"{rank}. [{row.category}] {row.bank} {row.name}"
            f" (유사도 {similarity:.2f}, 공시월 {row.disclosure_month})"
        )
        detail = " / ".join(row.text.splitlines()[1:])
        if len(detail) > _DETAIL_LIMIT:
            detail = detail[:_DETAIL_LIMIT] + "…"
        if detail:
            lines.append(f"   {detail}")
    return "\n".join(lines)
