import pytest

from app.db.vector_models import ProductEmbedding
from app.tools.condition import (
    MIN_SIMILARITY,
    drop_weak_matches,
    format_matches,
    infer_category,
)


def row(bank: str, distance: float, text: str = "") -> tuple[ProductEmbedding, float]:
    return (
        ProductEmbedding(
            product_key=f"deposit:{bank}:P",
            category="정기예금",
            bank=bank,
            name=f"{bank}예금",
            text=text or f"[정기예금] {bank} {bank}예금\n우대조건: 급여이체",
            content_hash="h",
            disclosure_month="202608",
            embedding=[0.0] * 1536,
        ),
        distance,
    )


def test_은행_카테고리_공시월_상세가_담긴다() -> None:
    text = format_matches([row("가은행", 0.2)])
    assert "가은행" in text
    assert "정기예금" in text
    assert "202608" in text
    assert "급여이체" in text


def test_유사도는_0에서_1_사이로_표시된다() -> None:
    text = format_matches([row("가은행", 1.4)])  # 코사인 거리 > 1
    assert "-" not in text.split("유사도")[1][:6]  # 음수 유사도 금지


def test_긴_상세는_잘라낸다() -> None:
    long_text = "[정기예금] 가은행 가예금\n" + ("우대조건 설명 " * 200)
    formatted = format_matches([row("가은행", 0.2, text=long_text)])
    assert len(formatted) < len(long_text)
    assert "…" in formatted


def test_빈_결과는_안내_문구를_반환한다() -> None:
    assert "찾지 못" in format_matches([])


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("급여이체 우대 있는 적금", "적금"),
        ("중도상환수수료 없는 주택담보대출", "주택담보대출"),
        ("주담대 금리 낮은 곳", "주택담보대출"),
        ("전세자금대출 중 한도 높은 것", "전세자금대출"),
        ("마이너스통장 만들 수 있는 곳", "개인신용대출"),
        ("1년 정기예금 우대조건", "정기예금"),
        ("버팀목 대출 자격 조건", "정책대출"),
        ("햇살론 받을 수 있어?", "정책대출"),
        ("신생아 특례 금리 얼마야", "정책대출"),
        ("디딤돌 소득 조건", "정책대출"),
        # 정책 적금·통장은 적금 카테고리에 색인된다 — 단서도 그쪽을 가리켜야 한다
        ("청년내일저축계좌 신청 방법", "적금"),
        ("희망두배 청년통장 자격", "적금"),
        ("청년미래적금 기여금", "적금"),
        ("청년도약계좌 가입 조건", "적금"),
        ("청년 자산형성 지원 뭐 있어?", "적금"),
        ("보조금 받을 수 있는 제도 알려줘", "정책지원"),
    ],
)
def test_질의에_카테고리_단서가_하나면_그_카테고리로_좁힌다(query: str, expected: str) -> None:
    assert infer_category(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "예금이랑 적금 중에 뭐가 나아?",  # 두 카테고리가 함께 언급되면 좁히면 안 된다
        "주택담보대출과 전세자금대출 비교해줘",
        "청년만 가입할 수 있는 상품",  # 단서 없음
        "우대금리 조건 알려줘",
        "버팀목 전세자금 조건",  # 전세(전세자금대출)와 버팀목(정책대출)이 겹친다 → 전체 검색
        "내일저축계좌랑 정기예금 중에 뭐가 나아?",  # 적금과 정기예금이 겹친다 → 전체 검색
    ],
)
def test_단서가_없거나_둘_이상이면_좁히지_않는다(query: str) -> None:
    assert infer_category(query) == ""


def at_similarity(bank: str, similarity: float) -> tuple[ProductEmbedding, float]:
    """유사도를 직접 지정한다 (코사인 거리 = 1 - 유사도)."""
    return row(bank, 1.0 - similarity)


def test_기준_미만_유사도는_버리고_기준_이상만_남긴다() -> None:
    kept = drop_weak_matches(
        [at_similarity("가은행", 0.8), at_similarity("나은행", 0.1)], min_similarity=0.5
    )
    assert [r.bank for r, _ in kept] == ["가은행"]


def test_기준값과_같은_유사도는_남긴다() -> None:
    kept = drop_weak_matches([at_similarity("가은행", 0.4)], min_similarity=0.4)
    assert len(kept) == 1


def test_거리순_정렬을_흐트러뜨리지_않는다() -> None:
    kept = drop_weak_matches(
        [at_similarity("가은행", 0.7), at_similarity("나은행", 0.6), at_similarity("다은행", 0.5)],
        min_similarity=0.4,
    )
    assert [r.bank for r, _ in kept] == ["가은행", "나은행", "다은행"]


def test_전부_기준_미만이면_빈_결과가_되어_못찾음_안내로_이어진다() -> None:
    kept = drop_weak_matches(
        [at_similarity("가은행", 0.2), at_similarity("나은행", 0.1)], min_similarity=0.5
    )
    assert kept == []
    assert "찾지 못" in format_matches(kept)


def test_기본_기준값은_실측_관련_질의_최저치를_남긴다() -> None:
    # 실측(색인 1042건): 관련 질의 80개 결과의 최저 유사도가 0.425였다.
    assert len(drop_weak_matches([at_similarity("가은행", 0.425)])) == 1


def test_기본_기준값은_명백한_무관을_거른다() -> None:
    # 실측: "오늘 날씨"·"파이썬 정렬"·"치킨 맛집" 질의의 상위 유사도가 0.20~0.33이었다.
    assert drop_weak_matches([at_similarity("가은행", 0.33)]) == []


def test_기본_기준값은_실측_구간_사이에_있다() -> None:
    assert 0.33 < MIN_SIMILARITY < 0.425
