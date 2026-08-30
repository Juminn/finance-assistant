import httpx
import pytest
import respx

from app.tools.gigeum import (
    AS_OF,
    BASE_INFO_URL,
    RATE_URL,
    GigeumError,
    fetch_gigeum_tables,
    gigeum_docs,
)

BASE_CSV = (
    "﻿상품대분류명,상품중분류명,상품소분류명,상품명,"
    "상품설명,상품적용시작일,상품적용종료일,비대면신청 가능여부\r\n"
    "개인수요자대출,주택전세자금,버팀목전세자금,청년전용 버팀목전세자금,"
    "청년을 위한 저금리 전세자금대출,2019-01-01,9999-12-31,Y\r\n"
    "개인수요자대출,주택월세자금,주거안정월세대출,주거안정월세대출 일반,"
    "저소득 월세 지원 대출,2019-01-01,9999-12-31,Y\r\n"
)

RATE_CSV = (
    "﻿상품명,일련번호,소득최소금액,소득최대금액,"
    "보증금최소금액,보증금최대금액,대출최소기간,대출최대기간,기본금리\r\n"
    "청년전용 버팀목전세자금,1,0 ,20000000 ,0 ,100000000 ,0 ,24 ,2.2 \r\n"
    "청년전용 버팀목전세자금,2,20000000 ,40000000 ,0 ,100000000 ,0 ,24 ,2.5 \r\n"
)


def mock_tables() -> None:
    respx.get(BASE_INFO_URL).mock(return_value=httpx.Response(200, text=BASE_CSV))
    respx.get(RATE_URL).mock(return_value=httpx.Response(200, text=RATE_CSV))


@respx.mock
def test_CSV_두_벌을_받아_파싱하고_공백을_정리한다() -> None:
    mock_tables()
    with httpx.Client() as client:
        base, rates = fetch_gigeum_tables(client)
    assert [row["상품명"] for row in base] == ["청년전용 버팀목전세자금", "주거안정월세대출 일반"]
    assert rates[0]["기본금리"] == "2.2"  # 원본의 후행 공백이 정리된다


@respx.mock
def test_다운로드가_실패하면_GigeumError를_던진다() -> None:
    respx.get(BASE_INFO_URL).mock(return_value=httpx.Response(500))
    respx.get(RATE_URL).mock(return_value=httpx.Response(200, text=RATE_CSV))
    with httpx.Client() as client, pytest.raises(GigeumError):
        fetch_gigeum_tables(client)


@respx.mock
def test_응답이_CSV가_아니면_GigeumError를_던진다() -> None:
    # 파일이 교체되면 다운로드 링크가 HTML 오류 페이지를 줄 수 있다
    respx.get(BASE_INFO_URL).mock(return_value=httpx.Response(200, text="<html>없는 파일</html>"))
    respx.get(RATE_URL).mock(return_value=httpx.Response(200, text=RATE_CSV))
    with httpx.Client() as client, pytest.raises(GigeumError, match="CSV"):
        fetch_gigeum_tables(client)


def rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    base = [
        {
            "상품대분류명": "개인수요자대출",
            "상품중분류명": "주택전세자금",
            "상품소분류명": "버팀목전세자금",
            "상품명": "청년전용 버팀목전세자금",
            "상품설명": "청년을 위한 저금리 전세자금대출",
        },
        {
            "상품대분류명": "개인수요자대출",
            "상품중분류명": "주택월세자금",
            "상품소분류명": "주거안정월세대출",
            "상품명": "주거안정월세대출 일반",
            "상품설명": "저소득 월세 지원 대출",
        },
    ]
    rates = [
        {
            "상품명": "청년전용 버팀목전세자금",
            "소득최소금액": "0",
            "소득최대금액": "20000000",
            "보증금최소금액": "0",
            "보증금최대금액": "100000000",
            "대출최소기간": "0",
            "대출최대기간": "24",
            "기본금리": "2.2",
        },
        {
            "상품명": "청년전용 버팀목전세자금",
            "소득최소금액": "20000000",
            "소득최대금액": "40000000",
            "보증금최소금액": "0",
            "보증금최대금액": "100000000",
            "대출최소기간": "0",
            "대출최대기간": "24",
            "기본금리": "2.5",
        },
    ]
    return base, rates


def test_상품_문서에_분류와_금리표가_실린다() -> None:
    base, rates = rows()
    docs = gigeum_docs(base, rates)
    doc = next(d for d in docs if d.name == "청년전용 버팀목전세자금")
    assert doc.product_key == "gigeum:청년전용 버팀목전세자금"
    assert doc.category == "정책대출"
    assert doc.bank == "주택도시기금"
    assert doc.disclosure_month == AS_OF
    assert "분류: 개인수요자대출 > 주택전세자금 > 버팀목전세자금" in doc.text
    assert "소득 2,000만원 이하 · 보증금 1억원 이하 · 기간 2년 이하: 연 2.2%" in doc.text
    assert "소득 2,000만원 초과 4,000만원 이하" in doc.text


def test_금리표가_없는_상품은_금리_안내_없이_문서를_만든다() -> None:
    base, rates = rows()
    docs = gigeum_docs(base, rates)
    doc = next(d for d in docs if d.name == "주거안정월세대출 일반")
    assert "기본금리" not in doc.text
    assert "저소득 월세 지원 대출" in doc.text


def test_문서는_상품당_한_건이고_키는_고유하다() -> None:
    # 우대금리 표는 상품 연결키가 없어 문서로 만들지 않는다 —
    # 잘못된 상품 귀속 위험이 있고, 검색 상위를 우대 항목이 차지해 상품을 밀어낸다.
    base, rates = rows()
    docs = gigeum_docs(base, rates)
    keys = [d.product_key for d in docs]
    assert len(keys) == len(set(keys)) == 2
