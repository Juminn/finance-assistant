from app.db.vector_models import ProductEmbedding
from app.tools.condition import format_matches


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
