"""조건 검색(시맨틱)의 카테고리 추론과 결과 포맷 — 순수 함수."""

from app.db.vector_models import ProductEmbedding

_DETAIL_LIMIT = 400

# 벡터 검색은 무관한 질의에도 늘 top_k건을 돌려준다. 그대로 넘기면 LLM이
# 상관없는 상품을 답으로 들이밀게 되므로, 명백히 먼 결과는 여기서 끊는다.
#
# 실측(색인 1042건, 관련 질의 16개 x 상위 5건 = 80건):
#   관련 결과 최저 유사도        0.425
#   도메인 밖 질의("오늘 날씨",
#   "파이썬 정렬", "치킨 맛집")  0.20 ~ 0.33
# 0.35는 그 사이에서 관련 결과를 하나도 잃지 않는 값이다. 더 올리면(0.45)
# 관련 결과 80건 중 14건이 잘려나간다 — 맞는 상품을 잃는 쪽이 더 나쁘다.
#
# 보험·퇴직연금처럼 금융에 인접한 질의는 0.41~0.47로 관련 구간과 겹쳐서
# 이 값으로는 못 거른다. 그쪽은 supervisor 라우팅과 워커 프롬프트가 맡는다.
MIN_SIMILARITY = 0.35

# 질의문에서 카테고리를 짚는 단서. 카테고리가 지정되지 않으면 이걸로 좁힌다.
# 색인이 커질수록 전체 검색은 무관 카테고리에 밀리므로, 단서가 있으면 쓰는 편이 낫다.
# "신용"·"대출"처럼 여러 카테고리에 걸치는 낱말은 오탐이 커서 단서로 쓰지 않는다.
_CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("정기예금", ("정기예금", "예금")),
    ("적금", ("적금",)),
    ("주택담보대출", ("주택담보", "주담대", "아파트담보", "담보대출")),
    ("전세자금대출", ("전세",)),
    ("개인신용대출", ("개인신용대출", "신용대출", "마이너스통장", "마이너스 통장")),
    # 정책상품은 상품명 자체가 강한 단서다. "버팀목 전세"처럼 기존 카테고리
    # 단서와 함께 나오면 둘 다 걸려 전체 검색으로 넘어간다 — 의도된 동작이다.
    (
        "정책대출",
        (
            "정책대출",
            "디딤돌",
            "버팀목",
            "햇살론",
            "보금자리",
            "미소금융",
            "사잇돌",
            "새희망홀씨",
            "신생아",
            "주택드림",
        ),
    ),
    (
        "정책지원",
        (
            "정책지원",
            "내일저축",
            "내일채움",
            "미래적금",
            "희망두배",
            "청년통장",
            "디딤씨앗",
            "자산형성",
            "보조금",
        ),
    ),
)


def infer_category(query: str) -> str:
    """질의문에서 카테고리를 하나만 확실히 짚을 수 있으면 그 이름을 반환한다.

    단서가 없거나 둘 이상 걸리면(예: "예금이랑 적금 중에") 좁히지 않고 빈 문자열을
    반환한다. 잘못 좁혀 맞는 상품을 통째로 잃는 쪽이 더 나쁘기 때문이다.
    """
    text = " ".join(query.split())
    hits = {category for category, words in _CATEGORY_HINTS if any(w in text for w in words)}
    return hits.pop() if len(hits) == 1 else ""


def similarity(distance: float) -> float:
    """코사인 거리(0~2)를 0~1 유사도로 바꾼다."""
    return max(0.0, 1.0 - distance)


def drop_weak_matches(
    matches: list[tuple[ProductEmbedding, float]],
    min_similarity: float = MIN_SIMILARITY,
) -> list[tuple[ProductEmbedding, float]]:
    """유사도가 기준에 못 미치는 결과를 버린다. 남은 것의 순서는 그대로 둔다.

    전부 걸러지면 빈 목록이 되고, format_matches가 "찾지 못했습니다"를 반환한다.
    """
    return [match for match in matches if similarity(match[1]) >= min_similarity]


def format_matches(matches: list[tuple[ProductEmbedding, float]]) -> str:
    """(문서, 코사인 거리) 목록을 LLM이 인용하기 좋은 텍스트로 만든다."""
    if not matches:
        return "조건에 맞는 상품을 찾지 못했습니다."

    lines = ["조건과 가장 가까운 상품:"]
    for rank, (row, distance) in enumerate(matches, start=1):
        lines.append(
            f"{rank}. [{row.category}] {row.bank} {row.name}"
            f" (유사도 {similarity(distance):.2f}, 공시월 {row.disclosure_month})"
        )
        detail = " / ".join(row.text.splitlines()[1:])
        if len(detail) > _DETAIL_LIMIT:
            detail = detail[:_DETAIL_LIMIT] + "…"
        if detail:
            lines.append(f"   {detail}")
    return "\n".join(lines)
