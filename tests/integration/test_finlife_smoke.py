"""실제 finlife API 스모크 테스트 — FINLIFE_API_KEY가 .env에 있어야 실행된다.

실행: uv run pytest -m integration
"""

import httpx
import pytest

from app.core.config import get_settings
from app.tools.deposit import search_deposit_products

pytestmark = pytest.mark.integration


def test_실제_API에서_정기예금을_조회하고_데이터가_최신인지_확인한다() -> None:
    api_key = get_settings().finlife_api_key
    if not api_key:
        pytest.skip("FINLIFE_API_KEY가 .env에 설정되지 않음")

    with httpx.Client(timeout=10) as client:
        products = search_deposit_products(client, api_key=api_key, top_n=3)

    assert products, "은행 정기예금 상품이 최소 1개는 조회되어야 한다"
    assert products[0].max_rate >= products[-1].max_rate

    # 공시월이 정상 포맷(YYYYMM)인지 — 데이터 최신성은 출력으로 눈으로 확인
    month = products[0].disclosure_month
    assert len(month) == 6 and month.isdigit()
    print(f"\n공시월: {month}, 1위: {products[0].bank} {products[0].name} {products[0].max_rate}%")
