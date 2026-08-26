"""정기예금 상품 비교 도구."""

from typing import Any

import httpx
from pydantic import BaseModel

from app.tools.finlife import BANK, fetch_page

_ENDPOINT = "depositProductsSearch.json"


class DepositProduct(BaseModel):
    bank: str
    name: str
    term_months: int
    base_rate: float
    max_rate: float
    join_way: str
    special_condition: str
    disclosure_month: str  # 공시월 (YYYYMM)


def search_deposit_products(
    client: httpx.Client,
    *,
    api_key: str,
    bank_group: str = BANK,
    term_months: int = 12,
    top_n: int = 5,
) -> list[DepositProduct]:
    """정기예금 상품을 조회해 최고우대금리 내림차순 상위 top_n개를 반환한다."""
    bases: dict[tuple[str, str], dict[str, Any]] = {}
    options: list[dict[str, Any]] = []

    page_no = 1
    while True:
        result = fetch_page(
            client, _ENDPOINT, api_key=api_key, top_fin_grp_no=bank_group, page_no=page_no
        )
        for base in result.get("baseList", []):
            bases[(base["fin_co_no"], base["fin_prdt_cd"])] = base
        options.extend(result.get("optionList", []))

        max_page_no = int(result.get("max_page_no") or 1)
        if page_no >= max_page_no:
            break
        page_no += 1

    products: list[DepositProduct] = []
    for option in options:
        if int(option.get("save_trm") or 0) != term_months:
            continue
        if option.get("intr_rate2") is None:
            continue
        base = bases.get((option["fin_co_no"], option["fin_prdt_cd"]))
        if base is None:
            continue
        products.append(
            DepositProduct(
                bank=base["kor_co_nm"],
                name=base["fin_prdt_nm"],
                term_months=term_months,
                base_rate=float(option.get("intr_rate") or 0.0),
                max_rate=float(option["intr_rate2"]),
                join_way=base.get("join_way") or "",
                special_condition=(base.get("spcl_cnd") or "").strip(),
                disclosure_month=base.get("dcls_month") or "",
            )
        )

    products.sort(key=lambda p: p.max_rate, reverse=True)
    return products[:top_n]
