"""조건 검색(시맨틱) 결과 포맷 — 순수 함수."""

from app.db.vector_models import ProductEmbedding

_DETAIL_LIMIT = 400


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
