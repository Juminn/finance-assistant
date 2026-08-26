from typing import Any

import httpx
import respx

from app.tools.finlife import BASE_URL
from app.tools.saving import SavingProduct, format_saving_products, search_saving_products

URL = f"{BASE_URL}/savingProductsSearch.json"


def payload(option_rows: list[dict[str, Any]], base_rows: list[dict[str, Any]]) -> dict[str, Any]:
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


def base(fin_co_no: str, cd: str, bank: str, name: str) -> dict[str, Any]:
    return {
        "dcls_month": "202608",
        "fin_co_no": fin_co_no,
        "fin_prdt_cd": cd,
        "kor_co_nm": bank,
        "fin_prdt_nm": name,
        "join_way": "스마트폰",
        "spcl_cnd": "급여이체 우대",
    }


def option(
    fin_co_no: str, cd: str, trm: str, rate: float | None, rate2: float | None, rsrv: str
) -> dict[str, Any]:
    return {
        "fin_co_no": fin_co_no,
        "fin_prdt_cd": cd,
        "save_trm": trm,
        "intr_rate": rate,
        "intr_rate2": rate2,
        "rsrv_type": rsrv,
        "rsrv_type_nm": "정액적립식" if rsrv == "S" else "자유적립식",
    }


@respx.mock
def test_기간을_필터하고_최고우대금리_내림차순으로_반환한다() -> None:
    data = payload(
        option_rows=[
            option("A", "P1", "12", 3.0, 4.0, "S"),
            option("B", "P2", "12", 3.5, 4.5, "F"),
            option("B", "P2", "24", 3.6, 4.8, "F"),  # 다른 기간 → 제외
        ],
        base_rows=[base("A", "P1", "가은행", "가적금"), base("B", "P2", "나은행", "나적금")],
    )
    respx.get(URL).mock(return_value=httpx.Response(200, json=data))

    with httpx.Client() as client:
        products = search_saving_products(client, api_key="key", term_months=12, top_n=5)

    assert [p.bank for p in products] == ["나은행", "가은행"]
    assert products[0].reserve_type == "자유적립식"
    assert products[0].max_rate == 4.5


def test_포맷에_은행과_금리와_적립방식이_들어간다() -> None:
    product = SavingProduct(
        bank="나은행",
        name="나적금",
        term_months=12,
        base_rate=3.5,
        max_rate=4.5,
        reserve_type="자유적립식",
        join_way="스마트폰",
        special_condition="급여이체 우대",
        disclosure_month="202608",
    )
    text = format_saving_products([product])
    assert "나은행" in text
    assert "4.50" in text
    assert "자유적립식" in text
    assert "202608" in text


def test_빈_목록은_없다는_안내를_반환한다() -> None:
    assert "없" in format_saving_products([])
