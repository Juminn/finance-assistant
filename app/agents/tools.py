"""LangChain 도구 바인딩 — 순수 함수(app.tools)를 에이전트가 호출할 수 있게 감싼다."""

import logging
from collections.abc import Callable
from functools import lru_cache

import httpx
from langchain_core.tools import tool
from openai import OpenAI

from app.core.config import get_settings
from app.core.embeddings import embed_texts
from app.db.session import get_session_factory, vector_search_enabled
from app.db.vector_repo import index_ready, search_similar
from app.tools.catalog import CATEGORIES
from app.tools.condition import drop_weak_matches, format_matches, infer_category
from app.tools.deposit import format_deposit_products, search_deposit_products
from app.tools.finlife import FinlifeError
from app.tools.gov24 import CATEGORY as SUPPORT_CATEGORY
from app.tools.loan import (
    format_credit_loans,
    format_secured_loans,
    search_credit_loans,
    search_mortgage_loans,
    search_rent_loans,
)
from app.tools.saving import format_saving_products, search_saving_products
from app.tools.smfg import CATEGORY as POLICY_LOAN_CATEGORY


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
    """정기예금 상품을 최고우대금리 순으로 비교한다. 은행과 저축은행을 함께 본다.

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
    """적금 상품을 최고우대금리 순으로 비교한다. 은행과 저축은행을 함께 본다.

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
    """주택담보대출 상품을 최저금리 순으로 비교한다. 은행·저축은행·보험사를 함께 본다.

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
    """전세자금대출 상품을 최저금리 순으로 비교한다. 은행·저축은행·보험사를 함께 본다.

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
    """개인신용대출 상품을 평균금리가 낮은 순으로 비교한다. 은행·저축은행·카드사 등을 함께 본다.

    Args:
        top_n: 상위 몇 개 상품을 보여줄지.
    """
    return _with_client(
        lambda client, key: format_credit_loans(
            search_credit_loans(client, api_key=key, top_n=top_n)
        )
    )


_TOP_K = 5
_INDEX_NOT_READY = "조건 검색 색인이 아직 준비되지 않았습니다. 금리 비교 도구를 대신 사용하세요."

# 조건 검색이 받는 카테고리 어휘 — 금감원 공시 5종 + 정책상품 2종
SEARCH_CATEGORIES: tuple[str, ...] = (*CATEGORIES, POLICY_LOAN_CATEGORY, SUPPORT_CATEGORY)


@lru_cache
def _openai_client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key, timeout=10, max_retries=1)


@tool
def search_products_by_condition(query: str, category: str = "") -> str:
    """우대조건·가입대상·상환방식처럼 문장으로 된 조건으로 금융상품을 찾는다.

    금리 순위 비교가 아니라 "급여이체 우대가 있는 적금", "중도상환수수료 없는 대출",
    "청년만 가입할 수 있는 상품"처럼 조건을 말로 설명할 때 쓴다.

    정책금융상품도 여기서 찾는다: 정책대출(햇살론·디딤돌·버팀목·보금자리론과
    정부·지자체의 각종 융자 지원 등 빌리는 성격 전부)과 정책지원(청년미래적금·
    청년내일저축계좌 같은 정책 적금·자산형성, 융자가 아닌 금융 지원제도).

    Args:
        query: 찾고 싶은 조건을 담은 문장.
        category: 좁히고 싶을 때만 지정.
            정기예금/적금/주택담보대출/전세자금대출/개인신용대출/정책대출/정책지원.
    """
    settings = get_settings()
    if not vector_search_enabled():
        return _INDEX_NOT_READY
    if not settings.openai_api_key:
        return "조건 검색에 필요한 OpenAI 키가 설정되지 않았습니다."

    requested_category = category
    if category not in SEARCH_CATEGORIES:
        category = ""

    # 카테고리를 안 주면 질의문에서 추론한다. 색인이 커질수록 전체 검색은
    # 무관 카테고리에 상위를 빼앗기므로, 단서가 있으면 좁히는 편이 정확하다.
    inferred_category = infer_category(query) if not category else ""
    category = category or inferred_category

    try:
        with get_session_factory()() as db:
            if not index_ready(db):
                return _INDEX_NOT_READY
            vector = embed_texts(_openai_client(), [query])[0]
            matches = search_similar(
                db,
                vector,
                top_k=_TOP_K,
                category=category or None,
            )
    except Exception:
        # 예외 원문(호스트명·계정 등)이 사용자 응답에 실리지 않게 로그로만 남긴다
        logging.exception("조건 검색 실패 (query=%s)", query)
        return "조건 검색 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    note = ""
    if requested_category and requested_category not in SEARCH_CATEGORIES:
        note = f"[참고] '{requested_category}' 카테고리를 인식하지 못해 전체에서 검색했습니다.\n"
    elif inferred_category:
        note = f"[참고] 질의를 보고 '{inferred_category}' 카테고리로 좁혀 검색했습니다.\n"
    # 유사도가 낮은 결과는 버린다 — 무관한 질의에도 벡터 검색은 늘 top_k건을 돌려준다
    return note + format_matches(drop_weak_matches(matches))
