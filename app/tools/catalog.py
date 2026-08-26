"""전 상품 카탈로그 수집 — 시맨틱 검색(RAG)에 넣을 문서를 만든다.

금리 같은 정형 조건은 기존 비교 도구가 정렬·필터로 처리하고,
이 모듈은 우대조건·가입대상·상환방식처럼 문장으로 된 정보를 검색하기 위한
문서를 만든다.
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from app.tools.finlife import BANK, fetch_all

_ProductKey = tuple[str, str]


class ProductDoc(BaseModel):
    """임베딩 대상 문서 한 건 (상품 하나)."""

    product_key: str  # "<카테고리 슬러그>:<금융회사코드>:<상품코드>"
    category: str
    bank: str
    name: str
    text: str
    disclosure_month: str

    @property
    def content_hash(self) -> str:
        """본문이 바뀌었는지 판단하는 지문 — 바뀐 상품만 다시 임베딩한다."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:32]


def _savings_option_line(option: dict[str, Any]) -> str | None:
    """예금·적금 금리 옵션 한 줄."""
    term = option.get("save_trm")
    if not term:
        return None
    parts = [f"{int(term)}개월"]
    base_rate = option.get("intr_rate")
    if base_rate is not None:
        parts.append(f"기본 {float(base_rate):.2f}%")
    max_rate = option.get("intr_rate2")
    if max_rate is not None:
        parts.append(f"최고 {float(max_rate):.2f}%")
    reserve_type = option.get("rsrv_type_nm")
    if reserve_type:
        parts.append(str(reserve_type))
    return " ".join(parts)


def _secured_option_line(option: dict[str, Any]) -> str | None:
    """주택담보·전세자금대출 금리 옵션 한 줄."""
    rate_min = option.get("lend_rate_min")
    if rate_min is None:
        return None
    parts = [
        str(option[key])
        for key in ("mrtg_type_nm", "rpay_type_nm", "lend_rate_type_nm")
        if option.get(key)
    ]
    rate_max = option.get("lend_rate_max") or rate_min
    parts.append(f"{float(rate_min):.2f}%~{float(rate_max):.2f}%")
    return " ".join(parts)


def _credit_option_line(option: dict[str, Any]) -> str | None:
    """개인신용대출 금리 옵션 한 줄."""
    average = option.get("crdt_grad_avg")
    if average is None:
        return None
    label = option.get("crdt_lend_rate_type_nm") or "대출금리"
    line = f"{label} 평균 {float(average):.2f}%"
    best = option.get("crdt_grad_1")
    if best is not None:
        line += f" (900점초과 {float(best):.2f}%)"
    return line


_SAVINGS_FIELDS = (
    ("가입방법", "join_way"),
    ("가입대상", "join_member"),
    ("우대조건", "spcl_cnd"),
    ("만기후이자율", "mtrt_int"),
)
_LOAN_FIELDS = (
    ("가입방법", "join_way"),
    ("대출한도", "loan_lmt"),
    ("중도상환수수료", "erly_rpay_fee"),
    ("연체이자율", "dly_rate"),
    ("대출부대비용", "loan_inci_expn"),
)
_CREDIT_FIELDS = (
    ("가입방법", "join_way"),
    ("대출종류", "crdt_prdt_type_nm"),
    ("CB회사", "cb_name"),
)


@dataclass(frozen=True)
class _Source:
    slug: str
    category: str
    endpoint: str
    option_line: Callable[[dict[str, Any]], str | None]
    fields: tuple[tuple[str, str], ...]


_SOURCES = (
    _Source(
        "deposit", "정기예금", "depositProductsSearch.json", _savings_option_line, _SAVINGS_FIELDS
    ),
    _Source("saving", "적금", "savingProductsSearch.json", _savings_option_line, _SAVINGS_FIELDS),
    _Source(
        "mortgage",
        "주택담보대출",
        "mortgageLoanProductsSearch.json",
        _secured_option_line,
        _LOAN_FIELDS,
    ),
    _Source(
        "rent",
        "전세자금대출",
        "rentHouseLoanProductsSearch.json",
        _secured_option_line,
        _LOAN_FIELDS,
    ),
    _Source(
        "credit",
        "개인신용대출",
        "creditLoanProductsSearch.json",
        _credit_option_line,
        _CREDIT_FIELDS,
    ),
)


def _clean(value: Any) -> str:
    """공시 원문에 섞인 앞뒤 공백과 줄바꿈을 정리한다."""
    return " ".join(str(value).split())


def _build_doc(
    source: _Source, key: _ProductKey, base: dict[str, Any], option_lines: list[str]
) -> ProductDoc:
    bank = _clean(base.get("kor_co_nm"))
    name = _clean(base.get("fin_prdt_nm"))

    lines = [f"[{source.category}] {bank} {name}"]
    for label, field in source.fields:
        value = base.get(field)
        if value:
            lines.append(f"{label}: {_clean(value)}")
    if option_lines:
        lines.append(f"금리: {' | '.join(option_lines)}")

    return ProductDoc(
        product_key=f"{source.slug}:{key[0]}:{key[1]}",
        category=source.category,
        bank=bank,
        name=name,
        text="\n".join(lines),
        disclosure_month=_clean(base.get("dcls_month")),
    )


def collect_product_docs(
    client: httpx.Client, *, api_key: str, bank_group: str = BANK
) -> list[ProductDoc]:
    """다섯 카테고리의 전 상품을 수집해 임베딩용 문서 목록을 만든다."""
    docs: list[ProductDoc] = []
    for source in _SOURCES:
        bases, options = fetch_all(
            client, source.endpoint, api_key=api_key, top_fin_grp_no=bank_group
        )

        grouped: dict[_ProductKey, list[str]] = defaultdict(list)
        for option in options:
            line = source.option_line(option)
            if line is None:
                continue
            grouped[(option["fin_co_no"], option["fin_prdt_cd"])].append(line)

        docs.extend(
            _build_doc(source, key, base, grouped.get(key, [])) for key, base in bases.items()
        )
    return docs
