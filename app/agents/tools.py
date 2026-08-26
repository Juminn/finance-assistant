"""LangChain 도구 바인딩 — 순수 함수(app.tools)를 에이전트가 호출할 수 있게 감싼다."""

from collections.abc import Callable

import httpx
from langchain_core.tools import tool

from app.core.auth_context import is_authenticated
from app.core.config import get_settings
from app.tools.deposit import format_deposit_products, search_deposit_products
from app.tools.finlife import FinlifeError
from app.tools.loan import (
    format_credit_loans,
    format_secured_loans,
    search_credit_loans,
    search_mortgage_loans,
    search_rent_loans,
)
from app.tools.saving import format_saving_products, search_saving_products


def _with_client(run: Callable[[httpx.Client, str], str]) -> str:
    """인증키 확인 → 클라이언트 생성 → 조회 실행. API 실패는 안내 문자열로 바꾼다."""
    settings = get_settings()
    if not settings.finlife_api_key:
        return "상품 조회에 필요한 인증키가 설정되지 않았습니다. 관리자에게 문의하세요."
    try:
        with httpx.Client(timeout=10) as client:
            return run(client, settings.finlife_api_key)
    except FinlifeError as exc:
        return f"상품 조회 중 오류가 발생했습니다: {exc}"


@tool
def compare_deposit_products(term_months: int = 12, top_n: int = 5) -> str:
    """은행 정기예금 상품을 최고우대금리 순으로 비교한다.

    Args:
        term_months: 저축 기간(개월). 6, 12, 24, 36 중 하나가 일반적이다.
        top_n: 상위 몇 개 상품을 보여줄지.
    """
    return _with_client(
        lambda client, key: format_deposit_products(
            search_deposit_products(client, api_key=key, term_months=term_months, top_n=top_n)
        )
    )


@tool
def compare_saving_products(term_months: int = 12, top_n: int = 5) -> str:
    """은행 적금 상품을 최고우대금리 순으로 비교한다.

    Args:
        term_months: 적립 기간(개월). 6, 12, 24, 36 중 하나가 일반적이다.
        top_n: 상위 몇 개 상품을 보여줄지.
    """
    return _with_client(
        lambda client, key: format_saving_products(
            search_saving_products(client, api_key=key, term_months=term_months, top_n=top_n)
        )
    )


@tool
def compare_mortgage_loans(top_n: int = 5) -> str:
    """은행 주택담보대출 상품을 최저금리 순으로 비교한다.

    Args:
        top_n: 상위 몇 개 상품을 보여줄지.
    """
    return _with_client(
        lambda client, key: format_secured_loans(
            search_mortgage_loans(client, api_key=key, top_n=top_n), kind="주택담보대출"
        )
    )


@tool
def compare_rent_loans(top_n: int = 5) -> str:
    """은행 전세자금대출 상품을 최저금리 순으로 비교한다.

    Args:
        top_n: 상위 몇 개 상품을 보여줄지.
    """
    return _with_client(
        lambda client, key: format_secured_loans(
            search_rent_loans(client, api_key=key, top_n=top_n), kind="전세자금대출"
        )
    )


@tool
def compare_credit_loans(top_n: int = 5) -> str:
    """은행 개인신용대출 상품을 평균금리가 낮은 순으로 비교한다. 로그인한 사용자만 쓸 수 있다.

    Args:
        top_n: 상위 몇 개 상품을 보여줄지.
    """
    if not is_authenticated():
        return (
            "[권한 안내] 개인신용대출 정보는 로그인 후 제공됩니다. "
            "사용자에게 화면 우측 상단에서 로그인한 뒤 다시 물어봐 달라고 짧게 안내하라."
        )
    return _with_client(
        lambda client, key: format_credit_loans(
            search_credit_loans(client, api_key=key, top_n=top_n)
        )
    )
