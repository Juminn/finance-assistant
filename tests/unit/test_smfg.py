from typing import Any

import httpx
import pytest
import respx

from app.tools.smfg import (
    CATEGORY,
    URL,
    SmfgError,
    fetch_policy_loans,
    policy_loan_docs,
)


def row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "basYm": "202607",
        "snq": "1",
        "finPrdNm": "청년전용 버팀목전세자금",
        "irt": "2.2~3.3%",
        "irtCtg": "변동금리",
        "lnLmt": "15000만원",
        "maxTotLnTrm": "2년",
        "maxDfrmTrm": "-",
        "rdptMthd": "일시상환",
        "usge": "주거",
        "trgt": "청년",
        "suprTgtDtlCond": "부부합산 연소득 5천만원 이하 무주택 세대주",
        "age": "19세 이상 34세 이하",
        "incm": "합산 총소득 5천만원 이하",
        "rsdAreaPamtEqltIstm": "전국",
        "housHoldCnt": "무주택",
        "housAr": "85㎡",
        "lnTgtHous": "보증금 3억원 이하",
        "prftAddIrtCond": "없음",
        "jnMthd": "수탁은행 방문",
        "hdlInst": "주택도시기금 수탁은행",
        "grnInst": "주택도시보증공사",
        "cnpl": "1599-0001",
        "ofrInstNm": "주택도시기금",
        "prdExisYn": "Y",
    }
    base.update(overrides)
    return base


def ok_body(items: list[dict[str, Any]], *, total: int | None = None) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "numOfRows": len(items),
                "pageNo": 1,
                "totalCount": total if total is not None else len(items),
                "items": {"item": items},
            },
        }
    }


@respx.mock
def test_최신_공시월을_찾아_그_달만_수집한다() -> None:
    probe = respx.get(URL, params__contains={"numOfRows": "1"}).mock(
        return_value=httpx.Response(200, json=ok_body([row()], total=9999))
    )
    fetch = respx.get(URL, params__contains={"basYm": "202607"}).mock(
        return_value=httpx.Response(200, json=ok_body([row(), row(finPrdNm="햇살론일반")]))
    )
    with httpx.Client() as client:
        rows = fetch_policy_loans(client, api_key="key")
    assert probe.called and fetch.called
    assert [r["finPrdNm"] for r in rows] == ["청년전용 버팀목전세자금", "햇살론일반"]


@respx.mock
def test_폐지된_상품은_거른다() -> None:
    respx.get(URL, params__contains={"numOfRows": "1"}).mock(
        return_value=httpx.Response(200, json=ok_body([row()], total=2))
    )
    respx.get(URL, params__contains={"basYm": "202607"}).mock(
        return_value=httpx.Response(
            200, json=ok_body([row(), row(finPrdNm="사라진 상품", prdExisYn="N")])
        )
    )
    with httpx.Client() as client:
        rows = fetch_policy_loans(client, api_key="key")
    assert [r["finPrdNm"] for r in rows] == ["청년전용 버팀목전세자금"]


@respx.mock
def test_여러_페이지를_넘겨_전부_수집한다() -> None:
    respx.get(URL, params__contains={"numOfRows": "1"}).mock(
        return_value=httpx.Response(200, json=ok_body([row()], total=9999))
    )

    def page_response(request: httpx.Request) -> httpx.Response:
        page_no = request.url.params["pageNo"]
        items = [row(finPrdNm=f"상품{page_no}")]
        body = ok_body(items, total=2)
        body["response"]["body"]["pageNo"] = int(page_no)
        return httpx.Response(200, json=body)

    respx.get(URL, params__contains={"basYm": "202607"}).mock(side_effect=page_response)
    with httpx.Client() as client:
        rows = fetch_policy_loans(client, api_key="key")
    assert [r["finPrdNm"] for r in rows] == ["상품1", "상품2"]


@respx.mock
def test_오류코드_응답이면_SmfgError를_던진다() -> None:
    payload = {
        "response": {
            "header": {"resultCode": "30", "resultMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"},
            "body": {},
        }
    }
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
    with httpx.Client() as client, pytest.raises(SmfgError, match="SERVICE_KEY"):
        fetch_policy_loans(client, api_key="bad")


@respx.mock
def test_HTTP_오류면_SmfgError를_던진다() -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))
    with httpx.Client() as client, pytest.raises(SmfgError):
        fetch_policy_loans(client, api_key="key")


@respx.mock
def test_게이트웨이가_XML_에러를_주면_SmfgError를_던진다() -> None:
    # data.go.kr 게이트웨이는 키 오류를 JSON이 아닌 XML로 반환한다
    xml = "<OpenAPI_ServiceResponse><cmmMsgHeader></cmmMsgHeader></OpenAPI_ServiceResponse>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=xml))
    with httpx.Client() as client, pytest.raises(SmfgError):
        fetch_policy_loans(client, api_key="key")


def test_문서는_금리와_대상을_담고_결측은_뺀다() -> None:
    docs = policy_loan_docs([row()])
    assert len(docs) == 1
    doc = docs[0]
    assert doc.category == CATEGORY
    assert doc.bank == "주택도시기금"
    assert doc.name == "청년전용 버팀목전세자금"
    assert doc.disclosure_month == "202607"
    assert doc.product_key.startswith("smfg:")
    assert "금리: 2.2~3.3% (변동금리)" in doc.text
    assert "한도: 15000만원" in doc.text
    assert "지원대상: 청년 / 부부합산 연소득 5천만원 이하 무주택 세대주" in doc.text
    assert "거치" not in doc.text  # maxDfrmTrm이 "-"이면 표기하지 않는다


def test_같은_상품명이_겹치면_키에_접미사를_붙여_보존한다() -> None:
    docs = policy_loan_docs([row(), row(irt="3.0%")])
    keys = [d.product_key for d in docs]
    assert len(keys) == len(set(keys)) == 2


def test_지역과_주택조건이_문서에_실린다() -> None:
    doc = policy_loan_docs([row()])[0]
    assert "지역: 전국" in doc.text
    assert "주택조건: 무주택 / 면적 85㎡ / 보증금 3억원 이하" in doc.text
