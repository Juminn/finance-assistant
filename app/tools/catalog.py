"""전 상품 카탈로그 수집 — 시맨틱 검색(RAG)에 넣을 문서를 만든다.

금리 같은 정형 조건은 기존 비교 도구가 정렬·필터로 처리하고,
이 모듈은 우대조건·가입대상·상환방식처럼 문장으로 된 정보를 검색하기 위한
문서를 만든다.
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from app.tools.finlife import (
    ALL_GROUPS,
    CREDIT_ENDPOINT,
    DEPOSIT_ENDPOINT,
    MORTGAGE_ENDPOINT,
    RENT_ENDPOINT,
    SAVING_ENDPOINT,
    base_product_code,
    fetch_all,
    to_float,
    to_int,
)

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
        """저장되는 모든 필드가 지문에 들어가야 변경이 감지된다 (공시월 포함)."""
        payload = "\n".join((self.category, self.bank, self.name, self.disclosure_month, self.text))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _savings_option_line(option: dict[str, Any]) -> str | None:
    """예금·적금 금리 옵션 한 줄."""
    term = to_int(option.get("save_trm"))
    if term is None:
        return None
    parts = [f"{term}개월"]
    base_rate = to_float(option.get("intr_rate"))
    if base_rate is not None:
        parts.append(f"기본 {base_rate:.2f}%")
    max_rate = to_float(option.get("intr_rate2"))
    if max_rate is not None:
        parts.append(f"최고 {max_rate:.2f}%")
    reserve_type = option.get("rsrv_type_nm")
    if reserve_type:
        parts.append(str(reserve_type))
    return " ".join(parts)


def _secured_option_line(option: dict[str, Any]) -> str | None:
    """주택담보·전세자금대출 금리 옵션 한 줄."""
    rate_min = to_float(option.get("lend_rate_min"))
    if rate_min is None:
        return None
    parts = [
        str(option[key])
        for key in ("mrtg_type_nm", "rpay_type_nm", "lend_rate_type_nm")
        if option.get(key)
    ]
    rate_max = to_float(option.get("lend_rate_max"))
    if rate_max is None:
        rate_max = rate_min
    parts.append(f"{rate_min:.2f}%~{rate_max:.2f}%")
    return " ".join(parts)


def _credit_option_line(option: dict[str, Any]) -> str | None:
    """개인신용대출 금리 옵션 한 줄 — 비교 도구와 동일하게 대출금리(A) 유형만 쓴다."""
    if option.get("crdt_lend_rate_type") != "A":
        return None
    average = to_float(option.get("crdt_grad_avg"))
    if average is None:
        return None
    label = option.get("crdt_lend_rate_type_nm") or "대출금리"
    line = f"{label} 평균 {average:.2f}%"
    best = to_float(option.get("crdt_grad_1"))
    if best is not None:
        line += f" (900점초과 {best:.2f}%)"
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
    _Source("deposit", "정기예금", DEPOSIT_ENDPOINT, _savings_option_line, _SAVINGS_FIELDS),
    _Source("saving", "적금", SAVING_ENDPOINT, _savings_option_line, _SAVINGS_FIELDS),
    _Source("mortgage", "주택담보대출", MORTGAGE_ENDPOINT, _secured_option_line, _LOAN_FIELDS),
    _Source("rent", "전세자금대출", RENT_ENDPOINT, _secured_option_line, _LOAN_FIELDS),
    _Source("credit", "개인신용대출", CREDIT_ENDPOINT, _credit_option_line, _CREDIT_FIELDS),
)

# 검색 필터 등에서 쓰는 카테고리 어휘의 단일 출처
CATEGORIES: tuple[str, ...] = tuple(source.category for source in _SOURCES)
CREDIT_CATEGORY = "개인신용대출"


def _clean(value: Any) -> str:
    """공시 원문의 앞뒤 공백·줄바꿈을 정리한다. 결측(None)은 빈 문자열."""
    if value is None:
        return ""
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
    client: httpx.Client, *, api_key: str, bank_groups: Sequence[str] = ALL_GROUPS
) -> list[ProductDoc]:
    """다섯 카테고리의 전 권역 상품을 수집해 임베딩용 문서 목록을 만든다."""
    docs: list[ProductDoc] = []
    seen: set[str] = set()
    for source in _SOURCES:
        for bank_group in bank_groups:
            bases, options = fetch_all(
                client, source.endpoint, api_key=api_key, top_fin_grp_no=bank_group
            )

            grouped: dict[_ProductKey, list[str]] = defaultdict(list)
            for option in options:
                line = source.option_line(option)
                if line is None:
                    continue
                grouped[(option["fin_co_no"], option["fin_prdt_cd"])].append(line)

            for key, base in bases.items():
                # 중복 공시분은 접미사가 붙어 있으므로 원래 코드로 금리를 찾는다
                option_key = (key[0], base_product_code(key[1]))
                doc = _build_doc(source, key, base, grouped.get(option_key, []))
                # product_key는 테이블 PK다 — 중복이 섞이면
                # upsert가 한 문에서 같은 행을 두 번 건드려 깨진다
                if doc.product_key in seen:
                    continue
                seen.add(doc.product_key)
                docs.append(doc)
    return docs
