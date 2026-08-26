from typing import Any

import httpx
import respx

from app.tools.catalog import collect_product_docs
from app.tools.finlife import BASE_URL

ENDPOINTS = {
    "deposit": f"{BASE_URL}/depositProductsSearch.json",
    "saving": f"{BASE_URL}/savingProductsSearch.json",
    "mortgage": f"{BASE_URL}/mortgageLoanProductsSearch.json",
    "rent": f"{BASE_URL}/rentHouseLoanProductsSearch.json",
    "credit": f"{BASE_URL}/creditLoanProductsSearch.json",
}


def page(base_rows: list[dict[str, Any]], option_rows: list[dict[str, Any]]) -> dict[str, Any]:
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


def empty() -> dict[str, Any]:
    return page([], [])


def mock_all(**overrides: dict[str, Any]) -> None:
    """5개 엔드포인트를 전부 mock하고, 지정한 것만 실제 데이터를 준다."""
    for name, url in ENDPOINTS.items():
        body = overrides.get(name, empty())
        respx.get(url).mock(return_value=httpx.Response(200, json=body))


@respx.mock
def test_정기예금_문서에_은행_상품명_우대조건_금리가_담긴다() -> None:
    mock_all(
        deposit=page(
            base_rows=[
                {
                    "dcls_month": "202608",
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "P1",
                    "kor_co_nm": "가은행",
                    "fin_prdt_nm": "가예금",
                    "join_way": "인터넷,스마트폰",
                    "spcl_cnd": " 첫 거래 우대 0.2%p ",
                }
            ],
            option_rows=[
                {
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "P1",
                    "save_trm": "12",
                    "intr_rate": 2.5,
                    "intr_rate2": 3.5,
                },
                {
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "P1",
                    "save_trm": "24",
                    "intr_rate": 2.6,
                    "intr_rate2": 3.6,
                },
            ],
        )
    )

    with httpx.Client() as client:
        docs = collect_product_docs(client, api_key="key")

    assert len(docs) == 1
    doc = docs[0]
    assert doc.category == "정기예금"
    assert doc.bank == "가은행"
    assert doc.name == "가예금"
    assert doc.disclosure_month == "202608"
    assert "첫 거래 우대 0.2%p" in doc.text
    assert "인터넷,스마트폰" in doc.text
    assert "12개월" in doc.text and "3.50" in doc.text
    assert "24개월" in doc.text  # 옵션이 여러 개면 모두 담긴다


@respx.mock
def test_product_key는_카테고리와_회사_상품코드로_만들어진다() -> None:
    mock_all(
        deposit=page(
            [
                {
                    "dcls_month": "202608",
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "P1",
                    "kor_co_nm": "가은행",
                    "fin_prdt_nm": "가예금",
                }
            ],
            [],
        ),
        saving=page(
            [
                {
                    "dcls_month": "202608",
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "P1",
                    "kor_co_nm": "가은행",
                    "fin_prdt_nm": "가적금",
                }
            ],
            [],
        ),
    )

    with httpx.Client() as client:
        docs = collect_product_docs(client, api_key="key")

    keys = {doc.product_key for doc in docs}
    # 회사·상품코드가 같아도 카테고리가 다르면 서로 다른 문서다
    assert keys == {"deposit:0010001:P1", "saving:0010001:P1"}


@respx.mock
def test_다섯_카테고리를_모두_수집한다() -> None:
    def one(name: str, **base_extra: Any) -> dict[str, Any]:
        return page(
            [
                {
                    "dcls_month": "202608",
                    "fin_co_no": "C",
                    "fin_prdt_cd": "P",
                    "kor_co_nm": "은행",
                    "fin_prdt_nm": name,
                    **base_extra,
                }
            ],
            [],
        )

    mock_all(
        deposit=one("예금상품"),
        saving=one("적금상품"),
        mortgage=one("주담대상품"),
        rent=one("전세상품"),
        credit=one("신용대출상품", crdt_prdt_type_nm="일반신용대출"),
    )

    with httpx.Client() as client:
        docs = collect_product_docs(client, api_key="key")

    assert {doc.category for doc in docs} == {
        "정기예금",
        "적금",
        "주택담보대출",
        "전세자금대출",
        "개인신용대출",
    }


@respx.mock
def test_대출_문서에는_금리유형과_금리범위가_담긴다() -> None:
    mock_all(
        mortgage=page(
            base_rows=[
                {
                    "dcls_month": "202608",
                    "fin_co_no": "C",
                    "fin_prdt_cd": "P",
                    "kor_co_nm": "가은행",
                    "fin_prdt_nm": "가주담대",
                    "loan_lmt": "LTV 70% 이내",
                }
            ],
            option_rows=[
                {
                    "fin_co_no": "C",
                    "fin_prdt_cd": "P",
                    "mrtg_type_nm": "아파트",
                    "rpay_type_nm": "분할상환방식",
                    "lend_rate_type_nm": "고정금리",
                    "lend_rate_min": 3.9,
                    "lend_rate_max": 4.5,
                }
            ],
        )
    )

    with httpx.Client() as client:
        docs = collect_product_docs(client, api_key="key")

    text = docs[0].text
    assert "아파트" in text
    assert "고정금리" in text
    assert "3.90" in text and "4.50" in text
    assert "LTV 70% 이내" in text


@respx.mock
def test_내용이_같으면_해시도_같고_다르면_달라진다() -> None:
    def build(spcl: str) -> str:
        mock_all(
            deposit=page(
                [
                    {
                        "dcls_month": "202608",
                        "fin_co_no": "C",
                        "fin_prdt_cd": "P",
                        "kor_co_nm": "가은행",
                        "fin_prdt_nm": "가예금",
                        "spcl_cnd": spcl,
                    }
                ],
                [],
            )
        )
        with httpx.Client() as client:
            return collect_product_docs(client, api_key="key")[0].content_hash

    assert build("우대조건 A") == build("우대조건 A")
    assert build("우대조건 A") != build("우대조건 B")


@respx.mock
def test_상품이_없으면_빈_목록을_반환한다() -> None:
    mock_all()
    with httpx.Client() as client:
        assert collect_product_docs(client, api_key="key") == []
