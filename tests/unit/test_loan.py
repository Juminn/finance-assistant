from typing import Any

import httpx
import respx

from app.tools.finlife import BASE_URL
from app.tools.loan import (
    format_credit_loans,
    format_secured_loans,
    search_credit_loans,
    search_mortgage_loans,
    search_rent_loans,
)

MORTGAGE_URL = f"{BASE_URL}/mortgageLoanProductsSearch.json"
RENT_URL = f"{BASE_URL}/rentHouseLoanProductsSearch.json"
CREDIT_URL = f"{BASE_URL}/creditLoanProductsSearch.json"


def payload(base_rows: list[dict[str, Any]], option_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "result": {
            "err_cd": "000",
            "err_msg": "정상",
            "total_count": len(base_rows),
            "max_page_no": 1,
            "now_page_no": 1,
            "baseList": base_rows,
            "optionList": option_rows,
        }
    }


def loan_base(fin_co_no: str, cd: str, bank: str, name: str, **extra: Any) -> dict[str, Any]:
    return {
        "dcls_month": "202608",
        "fin_co_no": fin_co_no,
        "fin_prdt_cd": cd,
        "kor_co_nm": bank,
        "fin_prdt_nm": name,
        "join_way": "스마트폰",
        **extra,
    }


def mortgage_option(
    fin_co_no: str, cd: str, rate_min: float | None, rate_max: float | None, **extra: Any
) -> dict[str, Any]:
    return {
        "fin_co_no": fin_co_no,
        "fin_prdt_cd": cd,
        "mrtg_type_nm": "아파트",
        "rpay_type_nm": "분할상환방식",
        "lend_rate_type_nm": "변동금리",
        "lend_rate_min": rate_min,
        "lend_rate_max": rate_max,
        **extra,
    }


@respx.mock
def test_주담대는_상품별_최저금리_옵션만_남기고_오름차순_정렬한다() -> None:
    data = payload(
        base_rows=[
            loan_base("A", "P1", "가은행", "가주담대"),
            loan_base("B", "P2", "나은행", "나주담대"),
        ],
        option_rows=[
            mortgage_option("A", "P1", 4.2, 4.8),
            mortgage_option("A", "P1", 3.9, 4.5, lend_rate_type_nm="고정금리"),
            mortgage_option("B", "P2", 4.1, 4.9),
            mortgage_option("B", "P2", None, 5.0),  # 금리 없음 → 무시
        ],
    )
    respx.get(MORTGAGE_URL).mock(return_value=httpx.Response(200, json=data))

    with httpx.Client() as client:
        loans = search_mortgage_loans(client, api_key="key", top_n=5)

    assert [(loan.bank, loan.rate_min) for loan in loans] == [("가은행", 3.9), ("나은행", 4.1)]
    assert loans[0].rate_type == "고정금리"
    assert loans[0].mortgage_type == "아파트"


@respx.mock
def test_전세대출도_같은_방식으로_정렬한다() -> None:
    data = payload(
        base_rows=[loan_base("A", "P1", "가은행", "가전세대출")],
        option_rows=[
            {
                "fin_co_no": "A",
                "fin_prdt_cd": "P1",
                "rpay_type_nm": "만기일시상환방식",
                "lend_rate_type_nm": "변동금리",
                "lend_rate_min": 3.7,
                "lend_rate_max": 4.2,
            }
        ],
    )
    respx.get(RENT_URL).mock(return_value=httpx.Response(200, json=data))

    with httpx.Client() as client:
        loans = search_rent_loans(client, api_key="key")

    assert loans[0].bank == "가은행"
    assert loans[0].rate_min == 3.7
    assert loans[0].mortgage_type == ""


@respx.mock
def test_신용대출은_대출금리_유형만_쓰고_평균금리_오름차순이다() -> None:
    data = payload(
        base_rows=[
            loan_base("A", "P1", "가은행", "가신용대출", crdt_prdt_type_nm="일반신용대출"),
            loan_base("B", "P2", "나은행", "나신용대출", crdt_prdt_type_nm="마이너스한도대출"),
        ],
        option_rows=[
            {
                "fin_co_no": "A",
                "fin_prdt_cd": "P1",
                "crdt_lend_rate_type": "A",
                "crdt_lend_rate_type_nm": "대출금리",
                "crdt_grad_avg": 5.5,
                "crdt_grad_1": 4.2,
            },
            {
                "fin_co_no": "A",
                "fin_prdt_cd": "P1",
                "crdt_lend_rate_type": "B",  # 기준금리 → 제외
                "crdt_lend_rate_type_nm": "기준금리",
                "crdt_grad_avg": 3.0,
                "crdt_grad_1": 2.8,
            },
            {
                "fin_co_no": "B",
                "fin_prdt_cd": "P2",
                "crdt_lend_rate_type": "A",
                "crdt_lend_rate_type_nm": "대출금리",
                "crdt_grad_avg": 5.1,
                "crdt_grad_1": 4.5,
            },
        ],
    )
    respx.get(CREDIT_URL).mock(return_value=httpx.Response(200, json=data))

    with httpx.Client() as client:
        loans = search_credit_loans(client, api_key="key")

    assert [(loan.bank, loan.rate_avg) for loan in loans] == [("나은행", 5.1), ("가은행", 5.5)]
    assert loans[1].rate_best == 4.2
    assert loans[0].product_type == "마이너스한도대출"


def test_대출_포맷에_은행_금리범위_유형이_들어간다() -> None:
    with httpx.Client() as client, respx.mock:
        respx.get(MORTGAGE_URL).mock(
            return_value=httpx.Response(
                200,
                json=payload(
                    base_rows=[loan_base("A", "P1", "가은행", "가주담대")],
                    option_rows=[mortgage_option("A", "P1", 3.9, 4.5)],
                ),
            )
        )
        loans = search_mortgage_loans(client, api_key="key")
    text = format_secured_loans(loans, kind="주택담보대출")
    assert "가은행" in text
    assert "3.90" in text
    assert "4.50" in text
    assert "202608" in text
    assert "주택담보대출" in text


def test_신용대출_포맷과_빈_목록_안내() -> None:
    assert "없" in format_credit_loans([])
    assert "없" in format_secured_loans([], kind="전세자금대출")
