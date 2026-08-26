"""LangChain 도구 바인딩 — 순수 함수(app.tools)를 에이전트가 호출할 수 있게 감싼다."""

import logging
from collections.abc import Callable

import httpx
from langchain_core.tools import tool
from openai import OpenAI

from app.core.auth_context import is_authenticated
from app.core.config import get_settings
from app.core.embeddings import embed_texts
from app.db.base import is_postgres
from app.db.session import get_session_factory
from app.db.vector_models import ProductEmbedding
from app.db.vector_repo import search_similar
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


_CATEGORIES = ("정기예금", "적금", "주택담보대출", "전세자금대출", "개인신용대출")
_DETAIL_LIMIT = 400
_TOP_K = 5


def _format_matches(matches: list[tuple[ProductEmbedding, float]]) -> str:
    if not matches:
        return "조건에 맞는 상품을 찾지 못했습니다."

    lines = ["조건과 가장 가까운 상품:"]
    for rank, (row, distance) in enumerate(matches, start=1):
        lines.append(
            f"{rank}. [{row.category}] {row.bank} {row.name}"
            f" (유사도 {1 - distance:.2f}, 공시월 {row.disclosure_month})"
        )
        detail = " / ".join(row.text.splitlines()[1:])
        if len(detail) > _DETAIL_LIMIT:
            detail = detail[:_DETAIL_LIMIT] + "…"
        if detail:
            lines.append(f"   {detail}")
    return "\n".join(lines)


@tool
def search_products_by_condition(query: str, category: str = "") -> str:
    """우대조건·가입대상·상환방식처럼 문장으로 된 조건으로 금융상품을 찾는다.

    금리 순위 비교가 아니라 "급여이체 우대가 있는 적금", "중도상환수수료 없는 대출",
    "청년만 가입할 수 있는 상품"처럼 조건을 말로 설명할 때 쓴다.

    Args:
        query: 찾고 싶은 조건을 담은 문장.
        category: 좁히고 싶을 때만 지정. 정기예금/적금/주택담보대출/전세자금대출/개인신용대출.
    """
    settings = get_settings()
    if not is_postgres(settings.database_url):
        return "조건 검색 색인이 아직 준비되지 않았습니다. 금리 비교 도구를 대신 사용하세요."
    if not settings.openai_api_key:
        return "조건 검색에 필요한 OpenAI 키가 설정되지 않았습니다."

    if category not in _CATEGORIES:
        category = ""

    try:
        vector = embed_texts(OpenAI(api_key=settings.openai_api_key), [query])[0]
        with get_session_factory()() as db:
            matches = search_similar(db, vector, top_k=_TOP_K, category=category or None)
    except Exception as exc:
        logging.exception("조건 검색 실패 (query=%s)", query)
        return f"조건 검색 중 오류가 발생했습니다: {exc}"

    return _format_matches(matches)
