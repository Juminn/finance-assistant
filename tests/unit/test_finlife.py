from typing import Any

import httpx
import pytest
import respx

from app.tools.finlife import (
    BANK,
    BASE_URL,
    SAVING_BANK,
    FinlifeError,
    fetch_all,
    fetch_all_groups,
    fetch_page,
)

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


@respx.mock
def test_같은_상품코드가_중복_공시돼도_두_건_모두_보존한다() -> None:
    # 실제 사례: 아이엠뱅크가 '마이너스한도대출'과 '장기카드대출'을
    # 같은 (fin_co_no, fin_prdt_cd)로 공시한다. dict 덮어쓰기로 유실되면 안 된다.
    body = ok_result(
        total_count=2,
        baseList=[
            {"fin_co_no": "0010016", "fin_prdt_cd": "WR0002F", "fin_prdt_nm": "마이너스한도대출"},
            {"fin_co_no": "0010016", "fin_prdt_cd": "WR0002F", "fin_prdt_nm": "장기카드대출"},
        ],
    )
    respx.get(URL).mock(return_value=httpx.Response(200, json=body))
    with httpx.Client() as client:
        bases, _ = fetch_all(client, ENDPOINT, api_key="key", top_fin_grp_no=BANK)

    assert len(bases) == 2
    names = {base["fin_prdt_nm"] for base in bases.values()}
    assert names == {"마이너스한도대출", "장기카드대출"}
    # 첫 건은 원래 코드를 유지하고, 중복분만 접미사로 구분한다
    assert bases[("0010016", "WR0002F")]["fin_prdt_nm"] == "마이너스한도대출"
    assert bases[("0010016", "WR0002F#2")]["fin_prdt_nm"] == "장기카드대출"


@respx.mock
def test_여러_권역을_합쳐_조회한다() -> None:
    respx.get(URL, params={"topFinGrpNo": BANK}).mock(
        return_value=httpx.Response(
            200,
            json=ok_result(
                baseList=[{"fin_co_no": "0010001", "fin_prdt_cd": "P1", "kor_co_nm": "가은행"}],
                optionList=[{"fin_co_no": "0010001", "fin_prdt_cd": "P1", "save_trm": "12"}],
            ),
        )
    )
    respx.get(URL, params={"topFinGrpNo": SAVING_BANK}).mock(
        return_value=httpx.Response(
            200,
            json=ok_result(
                baseList=[{"fin_co_no": "0020001", "fin_prdt_cd": "S1", "kor_co_nm": "가저축은행"}],
                optionList=[{"fin_co_no": "0020001", "fin_prdt_cd": "S1", "save_trm": "12"}],
            ),
        )
    )
    with httpx.Client() as client:
        bases, options = fetch_all_groups(
            client, ENDPOINT, api_key="key", groups=(BANK, SAVING_BANK)
        )

    assert set(bases) == {("0010001", "P1"), ("0020001", "S1")}
    assert len(options) == 2


@respx.mock
def test_권역_응답이_겹쳐도_같은_행을_두_번_담지_않는다() -> None:
    # 권역별 응답을 합칠 때 완전히 동일한 옵션 행이 중복 계상되면 안 된다
    body = ok_result(
        baseList=[{"fin_co_no": "0010001", "fin_prdt_cd": "P1", "kor_co_nm": "가은행"}],
        optionList=[{"fin_co_no": "0010001", "fin_prdt_cd": "P1", "save_trm": "12"}],
    )
    respx.get(URL).mock(return_value=httpx.Response(200, json=body))
    with httpx.Client() as client:
        bases, options = fetch_all_groups(
            client, ENDPOINT, api_key="key", groups=(BANK, SAVING_BANK)
        )

    assert len(bases) == 1
    assert len(options) == 1
