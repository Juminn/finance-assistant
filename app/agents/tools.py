"""LangChain 도구 바인딩 — 순수 함수(app.tools)를 에이전트가 호출할 수 있게 감싼다."""

import httpx
from langchain_core.tools import tool

from app.core.config import get_settings
from app.tools.deposit import format_deposit_products, search_deposit_products
from app.tools.finlife import FinlifeError


@tool
def compare_deposit_products(term_months: int = 12, top_n: int = 5) -> str:
    """은행 정기예금 상품을 최고우대금리 순으로 비교한다.

    Args:
        term_months: 저축 기간(개월). 6, 12, 24, 36 중 하나가 일반적이다.
        top_n: 상위 몇 개 상품을 보여줄지.
    """
    settings = get_settings()
    if not settings.finlife_api_key:
        return "정기예금 조회에 필요한 인증키가 설정되지 않았습니다. 관리자에게 문의하세요."

    try:
        with httpx.Client(timeout=10) as client:
            products = search_deposit_products(
                client,
                api_key=settings.finlife_api_key,
                term_months=term_months,
                top_n=top_n,
            )
    except FinlifeError as exc:
        return f"상품 조회 중 오류가 발생했습니다: {exc}"

    return format_deposit_products(products)
