"""금융위원회 서민금융상품기본정보 오픈API — 정책대출 카탈로그 수집.

금감원 공시(finlife)에 없는 정책금융상품(햇살론·디딤돌·버팀목·보금자리론 등)을
서민금융진흥원 '서민금융 한눈에' 데이터로 보충한다. 월별 스냅샷(basYm) 구조라
최신 공시월 한 달치만 수집하고, 폐지 상품(prdExisYn=N)은 거른다.
"""

from typing import Any, cast

import httpx

from app.tools.catalog import ProductDoc

BASE_URL = "https://apis.data.go.kr/1160100/service/GetSmallLoanFinanceInstituteInfoService"
URL = f"{BASE_URL}/getOrdinaryFinanceInfo"

# 조건 검색 카테고리 어휘 — 정책 서민금융·주택기금 대출을 한 범주로 묶는다
CATEGORY = "정책대출"

_OK = "00"
_PAGE_SIZE = 500
_KEY_LIMIT = 128  # ProductEmbedding.product_key 컬럼 길이


class SmfgError(Exception):
    """서민금융상품기본정보 API 호출 실패."""


def _clean(value: Any) -> str:
    """원문의 공백·줄바꿈을 정리한다. 결측(None·'-')은 빈 문자열."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return "" if text == "-" else text


def _fetch_body(
    client: httpx.Client, *, api_key: str, page_no: int, num_of_rows: int, bas_ym: str | None
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "serviceKey": api_key,
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "resultType": "json",
    }
    if bas_ym:
        params["basYm"] = bas_ym
    try:
        response = client.get(URL, params=params)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SmfgError(f"서민금융상품 API 호출 실패: {exc}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        # data.go.kr 게이트웨이는 키 오류를 XML로 반환한다
        raise SmfgError(f"서민금융상품 API 응답이 JSON이 아닙니다: {response.text[:120]}") from exc

    header = payload.get("response", {}).get("header", {})
    if header.get("resultCode") != _OK:
        raise SmfgError(
            f"서민금융상품 API 오류 [{header.get('resultCode')}]: {header.get('resultMsg')}"
        )
    body: dict[str, Any] = payload.get("response", {}).get("body", {})
    return body


def _items(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = body.get("items") or {}
    if isinstance(raw, dict):
        raw = cast(dict[str, Any], raw).get("item") or []
    if isinstance(raw, dict):  # 한 건이면 객체로 오는 공공API 관례 방어
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [cast(dict[str, Any], item) for item in cast(list[Any], raw) if isinstance(item, dict)]


def fetch_policy_loans(client: httpx.Client, *, api_key: str) -> list[dict[str, Any]]:
    """최신 공시월의 판매 중 정책대출 전체를 수집한다."""
    probe = _fetch_body(client, api_key=api_key, page_no=1, num_of_rows=1, bas_ym=None)
    probe_items = _items(probe)
    if not probe_items:
        raise SmfgError("서민금융상품 API가 빈 목록을 반환했습니다.")
    latest = str(probe_items[0].get("basYm") or "")
    if not latest:
        raise SmfgError("서민금융상품 응답에 공시월(basYm)이 없습니다.")

    rows: list[dict[str, Any]] = []
    page_no = 1
    while True:
        body = _fetch_body(
            client, api_key=api_key, page_no=page_no, num_of_rows=_PAGE_SIZE, bas_ym=latest
        )
        page_items = _items(body)
        rows.extend(page_items)
        total = int(body.get("totalCount") or 0)
        if not page_items or len(rows) >= total:
            break
        page_no += 1
    return [row for row in rows if row.get("prdExisYn") == "Y"]


# (라벨, 필드) — 값이 있을 때만 문서에 한 줄씩 싣는다
_LINE_FIELDS: tuple[tuple[str, str], ...] = (
    ("연령: ", "age"),
    ("소득조건: ", "incm"),
    ("한도: ", "lnLmt"),
    ("상환방식: ", "rdptMthd"),
    ("용도: ", "usge"),
    ("지역: ", "rsdAreaPamtEqltIstm"),
    ("우대조건: ", "prftAddIrtCond"),
    ("가입방법: ", "jnMthd"),
    ("취급기관: ", "hdlInst"),
    ("보증기관: ", "grnInst"),
    ("문의: ", "cnpl"),
)


def _doc_text(row: dict[str, Any]) -> str:
    bank = _clean(row.get("ofrInstNm"))
    name = _clean(row.get("finPrdNm"))
    lines = [f"[{CATEGORY}] {bank} {name}".strip()]

    target_parts = (_clean(row.get("trgt")), _clean(row.get("suprTgtDtlCond")))
    target = " / ".join(part for part in target_parts if part)
    if target:
        lines.append(f"지원대상: {target}")

    rate = _clean(row.get("irt"))
    if rate:
        rate_type = _clean(row.get("irtCtg"))
        lines.append(f"금리: {rate} ({rate_type})" if rate_type else f"금리: {rate}")

    term = _clean(row.get("maxTotLnTrm"))
    defer = _clean(row.get("maxDfrmTrm"))
    if term:
        lines.append(f"기간: 총 {term}" + (f" (거치 {defer})" if defer else ""))

    housing = " / ".join(
        part
        for part in (
            _clean(row.get("housHoldCnt")),
            (f"면적 {_clean(row.get('housAr'))}" if _clean(row.get("housAr")) else ""),
            _clean(row.get("lnTgtHous")),
        )
        if part
    )
    if housing:
        lines.append(f"주택조건: {housing}")

    for label, field in _LINE_FIELDS:
        value = _clean(row.get(field))
        if value:
            lines.append(f"{label}{value}")
    return "\n".join(lines)


def _product_key(row: dict[str, Any], seen: set[str]) -> str:
    base = f"smfg:{_clean(row.get('finPrdNm'))}:{_clean(row.get('ofrInstNm'))}"[:_KEY_LIMIT]
    key = base
    suffix = 2
    while key in seen:
        tail = f"#{suffix}"
        key = base[: _KEY_LIMIT - len(tail)] + tail
        suffix += 1
    return key


def policy_loan_docs(rows: list[dict[str, Any]]) -> list[ProductDoc]:
    """수집한 정책대출 행을 임베딩용 문서로 바꾼다."""
    docs: list[ProductDoc] = []
    seen: set[str] = set()
    for row in rows:
        name = _clean(row.get("finPrdNm"))
        if not name:
            continue
        key = _product_key(row, seen)
        seen.add(key)
        docs.append(
            ProductDoc(
                product_key=key,
                category=CATEGORY,
                bank=_clean(row.get("ofrInstNm"))[:64],
                name=name[:200],
                text=_doc_text(row),
                disclosure_month=_clean(row.get("basYm"))[:6],
            )
        )
    return docs
