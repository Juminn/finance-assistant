"""대출 상품 비교 도구 — 주택담보·전세자금·개인신용."""

import httpx
from pydantic import BaseModel

from app.tools.finlife import BANK, fetch_all

_MORTGAGE_ENDPOINT = "mortgageLoanProductsSearch.json"
_RENT_ENDPOINT = "rentHouseLoanProductsSearch.json"
_CREDIT_ENDPOINT = "creditLoanProductsSearch.json"


class SecuredLoan(BaseModel):
    """담보가 있는 대출(주담대·전세) — 상품별 최저금리 옵션 기준."""

    bank: str
    name: str
    mortgage_type: str  # 담보 유형 (전세대출은 빈 문자열)
    repay_type: str
    rate_type: str  # 고정금리 / 변동금리
    rate_min: float
    rate_max: float
    disclosure_month: str


class CreditLoan(BaseModel):
    bank: str
    name: str
    product_type: str  # 일반신용대출 / 마이너스한도대출 등
    rate_avg: float
    rate_best: float  # 신용점수 900점 초과 구간 금리
    disclosure_month: str


def _search_secured(
    client: httpx.Client,
    endpoint: str,
    *,
    api_key: str,
    bank_group: str,
    top_n: int,
) -> list[SecuredLoan]:
    bases, options = fetch_all(client, endpoint, api_key=api_key, top_fin_grp_no=bank_group)

    best: dict[tuple[str, str], SecuredLoan] = {}
    for option in options:
        if option.get("lend_rate_min") is None:
            continue
        key = (option["fin_co_no"], option["fin_prdt_cd"])
        base = bases.get(key)
        if base is None:
            continue
        candidate = SecuredLoan(
            bank=base["kor_co_nm"],
            name=base["fin_prdt_nm"],
            mortgage_type=option.get("mrtg_type_nm") or "",
            repay_type=option.get("rpay_type_nm") or "",
            rate_type=option.get("lend_rate_type_nm") or "",
            rate_min=float(option["lend_rate_min"]),
            rate_max=float(option.get("lend_rate_max") or option["lend_rate_min"]),
            disclosure_month=base.get("dcls_month") or "",
        )
        if key not in best or candidate.rate_min < best[key].rate_min:
            best[key] = candidate

    loans = sorted(best.values(), key=lambda loan: loan.rate_min)
    return loans[:top_n]


def search_mortgage_loans(
    client: httpx.Client, *, api_key: str, bank_group: str = BANK, top_n: int = 5
) -> list[SecuredLoan]:
    """주택담보대출을 상품별 최저금리 기준 오름차순으로 반환한다."""
    return _search_secured(
        client, _MORTGAGE_ENDPOINT, api_key=api_key, bank_group=bank_group, top_n=top_n
    )


def search_rent_loans(
    client: httpx.Client, *, api_key: str, bank_group: str = BANK, top_n: int = 5
) -> list[SecuredLoan]:
    """전세자금대출을 상품별 최저금리 기준 오름차순으로 반환한다."""
    return _search_secured(
        client, _RENT_ENDPOINT, api_key=api_key, bank_group=bank_group, top_n=top_n
    )


def search_credit_loans(
    client: httpx.Client, *, api_key: str, bank_group: str = BANK, top_n: int = 5
) -> list[CreditLoan]:
    """개인신용대출을 평균금리 오름차순으로 반환한다. 대출금리 유형(A) 옵션만 사용한다."""
    bases, options = fetch_all(client, _CREDIT_ENDPOINT, api_key=api_key, top_fin_grp_no=bank_group)

    best: dict[tuple[str, str], CreditLoan] = {}
    for option in options:
        if option.get("crdt_lend_rate_type") != "A":
            continue
        if option.get("crdt_grad_avg") is None:
            continue
        key = (option["fin_co_no"], option["fin_prdt_cd"])
        base = bases.get(key)
        if base is None:
            continue
        candidate = CreditLoan(
            bank=base["kor_co_nm"],
            name=base["fin_prdt_nm"],
            product_type=base.get("crdt_prdt_type_nm") or "",
            rate_avg=float(option["crdt_grad_avg"]),
            rate_best=float(option.get("crdt_grad_1") or 0.0),
            disclosure_month=base.get("dcls_month") or "",
        )
        if key not in best or candidate.rate_avg < best[key].rate_avg:
            best[key] = candidate

    loans = sorted(best.values(), key=lambda loan: loan.rate_avg)
    return loans[:top_n]


def format_secured_loans(loans: list[SecuredLoan], *, kind: str) -> str:
    if not loans:
        return f"조회된 {kind} 상품이 없습니다."

    lines = [f"[공시월 {loans[0].disclosure_month} 기준] {kind} 최저금리 상위 상품:"]
    for rank, loan in enumerate(loans, start=1):
        detail = f"{loan.rate_type}, {loan.repay_type}"
        if loan.mortgage_type:
            detail += f", 담보: {loan.mortgage_type}"
        lines.append(
            f"{rank}. {loan.bank} {loan.name} — {loan.rate_min:.2f}% ~ {loan.rate_max:.2f}%"
            f" ({detail})"
        )
    return "\n".join(lines)


def format_credit_loans(loans: list[CreditLoan]) -> str:
    if not loans:
        return "조회된 개인신용대출 상품이 없습니다."

    lines = [f"[공시월 {loans[0].disclosure_month} 기준] 개인신용대출 평균금리 상위 상품:"]
    for rank, loan in enumerate(loans, start=1):
        lines.append(
            f"{rank}. {loan.bank} {loan.name} — 평균 {loan.rate_avg:.2f}%"
            f" / 900점 초과 {loan.rate_best:.2f}% ({loan.product_type})"
        )
    return "\n".join(lines)
