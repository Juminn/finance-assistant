"""적금 상품 비교 도구."""

from collections.abc import Sequence

import httpx
from pydantic import BaseModel

from app.tools.finlife import ALL_GROUPS, fetch_all_groups
from app.tools.finlife import SAVING_ENDPOINT as _ENDPOINT


class SavingProduct(BaseModel):
    bank: str
    name: str
    term_months: int
    base_rate: float
    max_rate: float
    reserve_type: str  # 정액적립식 / 자유적립식
    join_way: str
    special_condition: str
    disclosure_month: str


def search_saving_products(
    client: httpx.Client,
    *,
    api_key: str,
    bank_groups: Sequence[str] = ALL_GROUPS,
    term_months: int = 12,
    top_n: int = 5,
) -> list[SavingProduct]:
    """적금 상품을 조회해 최고우대금리 내림차순 상위 top_n개를 반환한다."""
    bases, options = fetch_all_groups(client, _ENDPOINT, api_key=api_key, groups=bank_groups)

    # 같은 상품에 단리·복리 옵션이 따로 공시되므로 상품당 가장 높은 금리 한 건만 남긴다
    best: dict[tuple[str, str], SavingProduct] = {}
    for option in options:
        if int(option.get("save_trm") or 0) != term_months:
            continue
        if option.get("intr_rate2") is None:
            continue
        base = bases.get((option["fin_co_no"], option["fin_prdt_cd"]))
        if base is None:
            continue
        candidate = SavingProduct(
            bank=base["kor_co_nm"],
            name=base["fin_prdt_nm"],
            term_months=term_months,
            base_rate=float(option.get("intr_rate") or 0.0),
            max_rate=float(option["intr_rate2"]),
            reserve_type=option.get("rsrv_type_nm") or "",
            join_way=base.get("join_way") or "",
            special_condition=(base.get("spcl_cnd") or "").strip(),
            disclosure_month=base.get("dcls_month") or "",
        )
        key = (option["fin_co_no"], option["fin_prdt_cd"])
        if key not in best or candidate.max_rate > best[key].max_rate:
            best[key] = candidate

    products = sorted(best.values(), key=lambda p: p.max_rate, reverse=True)
    return products[:top_n]


def format_saving_products(products: list[SavingProduct]) -> str:
    """상품 목록을 LLM이 인용하기 좋은 한국어 텍스트로 만든다."""
    if not products:
        return "조회된 적금 상품이 없습니다."

    lines = [f"[공시월 {products[0].disclosure_month} 기준] 적금 최고우대금리 상위 상품:"]
    for rank, p in enumerate(products, start=1):
        lines.append(
            f"{rank}. {p.bank} {p.name} — 기본 {p.base_rate:.2f}% / 최고 {p.max_rate:.2f}%"
            f" ({p.term_months}개월, {p.reserve_type}, 가입경로: {p.join_way})"
        )
        if p.special_condition:
            lines.append(f"   우대조건: {p.special_condition}")
    return "\n".join(lines)
