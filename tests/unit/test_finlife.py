from typing import Any

import httpx
import pytest
import respx

from app.tools.finlife import BANK, BASE_URL, FinlifeError, fetch_page

ENDPOINT = "depositProductsSearch.json"
URL = f"{BASE_URL}/{ENDPOINT}"


def ok_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "err_cd": "000",
        "err_msg": "정상",
        "total_count": 0,
        "max_page_no": 1,
        "now_page_no": 1,
        "baseList": [],
        "optionList": [],
    }
    result.update(overrides)
    return {"result": result}


@respx.mock
def test_정상_응답이면_result를_반환한다() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=ok_result(total_count=3)))
    with httpx.Client() as client:
        result = fetch_page(client, ENDPOINT, api_key="key", top_fin_grp_no=BANK)
    assert result["total_count"] == 3


@respx.mock
def test_요청에_인증키와_권역코드와_페이지가_실린다() -> None:
    route = respx.get(URL, params={"auth": "key", "topFinGrpNo": BANK, "pageNo": 2}).mock(
        return_value=httpx.Response(200, json=ok_result())
    )
    with httpx.Client() as client:
        fetch_page(client, ENDPOINT, api_key="key", top_fin_grp_no=BANK, page_no=2)
    assert route.called


@respx.mock
def test_에러코드_응답이면_FinlifeError를_던진다() -> None:
    payload = {"result": {"err_cd": "010", "err_msg": "미등록 인증키", "total_count": "0"}}
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
    with httpx.Client() as client, pytest.raises(FinlifeError, match="미등록 인증키"):
        fetch_page(client, ENDPOINT, api_key="bad", top_fin_grp_no=BANK)


@respx.mock
def test_HTTP_오류면_FinlifeError를_던진다() -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))
    with httpx.Client() as client, pytest.raises(FinlifeError):
        fetch_page(client, ENDPOINT, api_key="key", top_fin_grp_no=BANK)


@respx.mock
def test_타임아웃이면_FinlifeError를_던진다() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("연결 시간 초과"))
    with httpx.Client() as client, pytest.raises(FinlifeError):
        fetch_page(client, ENDPOINT, api_key="key", top_fin_grp_no=BANK)
