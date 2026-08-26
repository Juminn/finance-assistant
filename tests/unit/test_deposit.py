from typing import Any

import httpx
import respx

from app.tools.deposit import DepositProduct, format_deposit_products, search_deposit_products
from app.tools.finlife import BASE_URL

URL = f"{BASE_URL}/depositProductsSearch.json"


def base_item(fin_co_no: str, fin_prdt_cd: str, bank: str, name: str) -> dict[str, Any]:
    return {
        "dcls_month": "202608",
        "fin_co_no": fin_co_no,
        "fin_prdt_cd": fin_prdt_cd,
        "kor_co_nm": bank,
        "fin_prdt_nm": name,
        "join_way": "인터넷,스마트폰",
        "spcl_cnd": " 우대조건 없음 ",
    }


def option_item(
    fin_co_no: str,
    fin_prdt_cd: str,
    save_trm: str,
    intr_rate: float | None,
    intr_rate2: float | None,
) -> dict[str, Any]:
    return {
        "dcls_month": "202608",
        "fin_co_no": fin_co_no,
        "fin_prdt_cd": fin_prdt_cd,
        "intr_rate_type": "S",
        "save_trm": save_trm,
        "intr_rate": intr_rate,
        "intr_rate2": intr_rate2,
    }


def page(
    base_list: list[dict[str, Any]],
    option_list: list[dict[str, Any]],
    max_page_no: int = 1,
    now_page_no: int = 1,
) -> dict[str, Any]:
    return {
        "result": {
            "err_cd": "000",
            "err_msg": "정상",
            "total_count": len(base_list),
            "max_page_no": max_page_no,
            "now_page_no": now_page_no,
            "baseList": base_list,
            "optionList": option_list,
        }
    }


@respx.mock
def test_기간_필터와_최고우대금리_내림차순으로_top_n을_반환한다() -> None:
    payload = page(
        base_list=[
            base_item("A", "P1", "가은행", "가예금"),
            base_item("B", "P2", "나은행", "나예금"),
            base_item("C", "P3", "다은행", "다예금"),
        ],
        option_list=[
            option_item("A", "P1", "12", 2.0, 2.8),
            option_item("A", "P1", "6", 1.8, 2.0),  # 다른 기간 → 제외
            option_item("B", "P2", "12", 2.5, 3.5),
            option_item("C", "P3", "12", 2.2, 3.0),
        ],
    )
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    with httpx.Client() as client:
        products = search_deposit_products(client, api_key="key", term_months=12, top_n=2)

    assert [p.bank for p in products] == ["나은행", "다은행"]
    assert products[0].max_rate == 3.5
    assert products[0].base_rate == 2.5
    assert products[0].term_months == 12
    assert products[0].special_condition == "우대조건 없음"
    assert products[0].disclosure_month == "202608"


@respx.mock
def test_여러_페이지를_전부_수집한다() -> None:
    page1 = page(
        [base_item("A", "P1", "가은행", "가예금")],
        [option_item("A", "P1", "12", 2.0, 2.8)],
        max_page_no=2,
        now_page_no=1,
    )
    page2 = page(
        [base_item("B", "P2", "나은행", "나예금")],
        [option_item("B", "P2", "12", 2.5, 3.5)],
        max_page_no=2,
        now_page_no=2,
    )
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    with httpx.Client() as client:
        products = search_deposit_products(client, api_key="key", term_months=12, top_n=10)

    assert [p.bank for p in products] == ["나은행", "가은행"]


@respx.mock
def test_결과가_없으면_빈_리스트를_반환한다() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=page([], [])))
    with httpx.Client() as client:
        assert search_deposit_products(client, api_key="key") == []


@respx.mock
def test_우대금리가_없는_옵션은_제외하고_기본금리가_없으면_0으로_둔다() -> None:
    payload = page(
        base_list=[
            base_item("A", "P1", "가은행", "가예금"),
            base_item("B", "P2", "나은행", "나예금"),
        ],
        option_list=[
            option_item("A", "P1", "12", None, 2.8),  # 기본금리 null → 0.0
            option_item("B", "P2", "12", 2.5, None),  # 우대금리 null → 제외
        ],
    )
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    with httpx.Client() as client:
        products = search_deposit_products(client, api_key="key", term_months=12)

    assert len(products) == 1
    assert products[0].bank == "가은행"
    assert products[0].base_rate == 0.0


def test_상품_목록을_읽기_좋은_텍스트로_포맷한다() -> None:
    products = [
        DepositProduct(
            bank="나은행",
            name="나예금",
            term_months=12,
            base_rate=2.5,
            max_rate=3.5,
            join_way="인터넷,스마트폰",
            special_condition="첫 거래 우대",
            disclosure_month="202608",
        )
    ]
    text = format_deposit_products(products)
    assert "나은행" in text
    assert "3.50" in text
    assert "202608" in text
    assert "첫 거래 우대" in text


def test_빈_목록은_없다는_안내를_반환한다() -> None:
    assert "없" in format_deposit_products([])


@respx.mock
def test_기본정보가_없는_고아_옵션은_제외한다() -> None:
    payload = page(
        base_list=[base_item("A", "P1", "가은행", "가예금")],
        option_list=[
            option_item("A", "P1", "12", 2.0, 2.8),
            option_item("Z", "P9", "12", 9.9, 9.9),  # baseList에 없음 → 제외
        ],
    )
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    with httpx.Client() as client:
        products = search_deposit_products(client, api_key="key", term_months=12)

    assert [p.bank for p in products] == ["가은행"]
