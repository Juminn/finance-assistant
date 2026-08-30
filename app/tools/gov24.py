"""행정안전부 대한민국 공공서비스(혜택) 오픈API(보조금24) — 정책 지원 카탈로그.

정책 적금·자산형성(청년미래적금·청년내일저축계좌·지자체 통장 등)과 각종 금융성
지원제도는 상품 공시가 없어, 정부24 운영 DB와 연동되는 이 통합 목록에서 가져온다.
전체 서비스(1만여 건) 중 금융 키워드에 걸리는 항목만 걸러 색인한다.
금리·한도 같은 정형 필드는 없고 지원내용 문장만 있으므로 시맨틱 검색 전용이다.

카테고리는 데이터 출처가 아니라 상품 성격으로 정한다: 융자는 정책대출,
예·적금·통장성 상품은 공시 상품과 같은 정기예금·적금 칸, 나머지
(이자·보증료 지원, 보조금 등 상품이 아닌 지원제도)만 정책지원에 남는다.
"""

import re
from typing import Any, cast

import httpx

from app.tools.catalog import ProductDoc
from app.tools.smfg import CATEGORY as POLICY_LOAN_CATEGORY

BASE_URL = "https://api.odcloud.kr/api/gov24/v3"
DETAIL_URL = f"{BASE_URL}/serviceDetail"

# 조건 검색 카테고리 어휘 — 예적금도 대출도 아닌 정책 지원제도만 묶는다.
# 카테고리로 좁힌 검색은 다른 카테고리를 보지 못하므로, 상품 성격이 같은 것은
# 한 칸에 있어야 한다: 융자 혜택은 정책대출로, 예·적금·통장성 상품은
# 공시 상품과 같은 정기예금·적금 카테고리로 보낸다. "청년 적금" 같은 질의가
# 적금으로 좁혀질 때 정책 적금이 함께 검색되게 하기 위함이다.
CATEGORY = "정책지원"

# app.tools.catalog의 공시 카테고리 어휘와 같아야 한다 (테스트로 고정)
DEPOSIT_CATEGORY = "정기예금"
SAVING_CATEGORY = "적금"

_PAGE_SIZE = 500
_FIELD_LIMIT = 800  # 지원내용이 수천 자인 항목이 있어 필드 단위로 자른다

# 서비스명에 있으면 금융 서비스로 본다 (상품명은 짧아 오탐이 적다)
_NAME_KEYWORDS = (
    "대출",
    "융자",
    "적금",
    "예금",
    "통장",
    "저축",
    "자산형성",
    "이차보전",
    "이자지원",
    "이자 지원",
    "보증료",
    "신용보증",
    "채움공제",
    "노란우산",
)
# 설명문에서는 더 강한 낱말만 쓴다 ("통장으로 지급" 같은 우연 일치를 피한다)
_CONTENT_KEYWORDS = (
    "대출",
    "융자",
    "이차보전",
    "이자지원",
    "이자 지원",
    "자산형성",
    "저축계좌",
    "적금",
    "보증료",
    "신용보증",
)


class Gov24Error(Exception):
    """공공서비스(혜택) API 호출 실패."""


def fetch_service_details(client: httpx.Client, *, api_key: str) -> list[dict[str, Any]]:
    """서비스 상세 목록 전체를 페이지 단위로 수집한다."""
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        try:
            response = client.get(
                DETAIL_URL,
                params={
                    "serviceKey": api_key,
                    "page": page,
                    "perPage": _PAGE_SIZE,
                    "returnType": "JSON",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise Gov24Error(f"공공서비스 API 호출 실패: {exc}") from exc
        except ValueError as exc:
            raise Gov24Error("공공서비스 API 응답이 JSON이 아닙니다.") from exc

        data = cast(list[dict[str, Any]], payload.get("data") or [])
        rows.extend(data)
        total = int(payload.get("totalCount") or 0)
        if not data or len(rows) >= total:
            break
        page += 1
    return rows


def _text_of(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return "" if text in ("-", "해당없음") else text


# 서비스명에 있으면 계좌(예·적금·통장)성 상품으로 본다 — 지원내용은 "통장으로
# 지급" 같은 우연 일치가 많아 상품명만 본다
_SAVING_NAME_KEYWORDS = ("적금", "통장", "저축", "계좌", "자산형성", "채움공제", "노란우산")


def _product_category(name: str) -> str:
    """서비스명이 계좌성 상품이면 그 상품 카테고리를, 아니면 빈 문자열을 반환한다."""
    text = name.replace("저축은행", "")  # "저축은행 ○○ 지원"의 저축은 예적금 단서가 아니다
    if "대출" in text or "융자" in text:  # 통장·계좌가 붙어도 대출 관련이면 상품이 아니다
        return ""
    if "예금" in text:
        return DEPOSIT_CATEGORY
    if any(keyword in text for keyword in _SAVING_NAME_KEYWORDS):
        return SAVING_CATEGORY
    return ""


def is_finance_service(row: dict[str, Any]) -> bool:
    """대출·적금·자산형성 등 금융 성격의 지원 서비스인지 판별한다."""
    if "융자" in _text_of(row, "지원유형"):
        return True
    name = _text_of(row, "서비스명")
    if any(keyword in name for keyword in _NAME_KEYWORDS):
        return True
    content = f"{_text_of(row, '서비스목적')} {_text_of(row, '지원내용')}"
    return any(keyword in content for keyword in _CONTENT_KEYWORDS)


def finance_services(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """금융 성격의 서비스만 남긴다."""
    return [row for row in rows if is_finance_service(row)]


def _norm_name(name: str) -> str:
    return "".join(name.split()).lower()


def exclude_known_products(
    rows: list[dict[str, Any]], known_names: list[str]
) -> list[dict[str, Any]]:
    """다른 소스에서 이미 수집한 상품명과 겹치는 서비스를 뺀다.

    서금원 정책대출(햇살론 등)은 보조금24에도 같은 이름으로 실리므로,
    상품 조건이 더 구조화된 정책대출 쪽을 정본으로 남긴다.
    """
    known = {_norm_name(name) for name in known_names}
    return [row for row in rows if _norm_name(_text_of(row, "서비스명")) not in known]


_DOC_FIELDS: tuple[tuple[str, str], ...] = (
    ("목적: ", "서비스목적"),
    ("지원대상: ", "지원대상"),
    ("선정기준: ", "선정기준"),
    ("지원내용: ", "지원내용"),
    ("지원유형: ", "지원유형"),
    ("신청방법: ", "신청방법"),
    ("신청기한: ", "신청기한"),
    ("접수기관: ", "접수기관명"),
    ("문의: ", "문의처"),
    ("신청: ", "온라인신청사이트URL"),
)


def _disclosure_month(row: dict[str, Any]) -> str:
    digits = re.sub(r"\D", "", _text_of(row, "수정일시"))
    return digits[:6] if len(digits) >= 6 else ""


def gov24_docs(rows: list[dict[str, Any]]) -> list[ProductDoc]:
    """서비스 상세를 임베딩용 문서로 바꾼다."""
    docs: list[ProductDoc] = []
    seen: set[str] = set()
    for row in rows:
        service_id = _text_of(row, "서비스ID")
        name = _text_of(row, "서비스명")
        if not service_id or not name:
            continue
        key = f"gov24:{service_id}"[:128]
        if key in seen:
            continue
        seen.add(key)

        if "융자" in _text_of(row, "지원유형"):
            category = POLICY_LOAN_CATEGORY
        else:
            category = _product_category(name) or CATEGORY
        organ = _text_of(row, "소관기관명")
        lines = [f"[{category}] {organ} {name}".strip()]
        for label, field in _DOC_FIELDS:
            value = _text_of(row, field)
            if not value:
                continue
            if len(value) > _FIELD_LIMIT:
                value = value[:_FIELD_LIMIT] + "…"
            lines.append(f"{label}{value}")

        docs.append(
            ProductDoc(
                product_key=key,
                category=category,
                bank=organ[:64],
                name=name[:200],
                text="\n".join(lines),
                disclosure_month=_disclosure_month(row),
            )
        )
    return docs
