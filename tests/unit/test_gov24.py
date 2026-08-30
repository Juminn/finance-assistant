from typing import Any

import httpx
import pytest
import respx

from app.tools.catalog import CATEGORIES
from app.tools.gov24 import (
    CATEGORY,
    DEPOSIT_CATEGORY,
    DETAIL_URL,
    SAVING_CATEGORY,
    Gov24Error,
    exclude_known_products,
    fetch_service_details,
    finance_services,
    gov24_docs,
    is_finance_service,
)


def service(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "서비스ID": "161300000076",
        "서비스명": "버팀목전세자금대출",
        "서비스목적": "근로자 및 서민의 주거안정을 위한 전세자금 대출",
        "소관기관명": "국토교통부",
        "지원대상": "만19세 이상 세대주, 무주택자",
        "선정기준": "부부합산 연 소득 5천만원 이하",
        "지원내용": "임차보증금 70% 이내 대출 지원, 대출금리 연 2.1%~2.9%",
        "지원유형": "현금(융자)",
        "신청방법": "기금e든든 웹사이트 신청",
        "신청기한": "접수기관 별 상이",
        "접수기관명": "주택도시보증공사",
        "문의처": "주택도시보증공사/1566-9009",
        "온라인신청사이트URL": "https://enhuf.molit.go.kr",
        "수정일시": "2026-05-08",
        "구비서류": "해당없음",
    }
    base.update(overrides)
    return base


def page_json(rows: list[dict[str, Any]], *, total: int) -> dict[str, Any]:
    return {
        "page": 1,
        "perPage": len(rows),
        "totalCount": total,
        "currentCount": len(rows),
        "data": rows,
    }


@respx.mock
def test_전체_페이지를_받아_합친다() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        rows = [service(서비스ID=f"SVC{page}")]
        return httpx.Response(200, json=page_json(rows, total=2))

    respx.get(DETAIL_URL).mock(side_effect=respond)
    with httpx.Client() as client:
        rows = fetch_service_details(client, api_key="key")
    assert [r["서비스ID"] for r in rows] == ["SVC1", "SVC2"]


@respx.mock
def test_인증_실패면_Gov24Error를_던진다() -> None:
    error = httpx.Response(401, json={"code": -4, "msg": "인증 실패"})
    respx.get(DETAIL_URL).mock(return_value=error)
    with httpx.Client() as client, pytest.raises(Gov24Error):
        fetch_service_details(client, api_key="bad")


def test_융자_유형이거나_금융_키워드가_있으면_금융_서비스다() -> None:
    assert is_finance_service(service()) is True  # 지원유형 융자
    assert is_finance_service(service(지원유형="현금", 서비스명="청년미래적금")) is True
    assert (
        is_finance_service(
            service(지원유형="현금", 서비스명="희망두배 청년통장", 지원내용="저축액 매칭 지원")
        )
        is True
    )
    assert (
        is_finance_service(
            service(
                지원유형="현금",
                서비스명="자산형성지원사업(청년내일저축계좌)",
                지원내용="저축계좌 매칭",
            )
        )
        is True
    )


def test_금융과_무관한_복지_서비스는_거른다() -> None:
    assert (
        is_finance_service(
            service(
                지원유형="현금",
                서비스명="산모신생아 건강관리 지원",
                서비스목적="산모의 건강관리",
                지원내용="건강관리사 파견 본인부담금 지원",
            )
        )
        is False
    )
    assert (
        is_finance_service(
            service(
                지원유형="현금",
                서비스명="청년 사회진입 활동비 지원",
                서비스목적="구직 청년 지원",
                지원내용="활동비 월 50만원 지급",
            )
        )
        is False
    )


def test_finance_services는_금융_항목만_남긴다() -> None:
    welfare = service(
        서비스ID="X",
        서비스명="산모신생아 건강관리",
        지원유형="현금",
        지원내용="파견 지원",
        서비스목적="건강",
    )
    assert [r["서비스ID"] for r in finance_services([service(), welfare])] == ["161300000076"]


def test_이미_수집된_상품명과_겹치는_서비스는_뺀다() -> None:
    # 서금원 상품(햇살론 등)은 보조금24에도 같은 이름으로 실린다 — 정책대출 쪽을 정본으로 삼는다
    rows = [
        service(서비스ID="A", 서비스명="햇살론유스"),
        service(서비스ID="B", 서비스명="버팀목전세자금대출"),
    ]
    kept = exclude_known_products(rows, ["햇살론 유스", "버팀목전세자금"])
    assert [r["서비스ID"] for r in kept] == ["B"]  # 공백 차이는 같은 상품으로 본다


def test_융자형_서비스는_정책대출_카테고리로_분류한다() -> None:
    # 카테고리로 좁혀 검색하면 다른 카테고리는 보이지 않는다 —
    # 빌리는 성격(융자)의 혜택은 정책대출과 같은 칸에 있어야 함께 검색된다.
    loan_doc = gov24_docs([service()])[0]  # 지원유형 "현금(융자)"
    assert loan_doc.category == "정책대출"


@pytest.mark.parametrize(
    "name",
    [
        "청년미래적금",
        "희망두배 청년통장",
        "자산형성지원사업(청년내일저축계좌)",
        "청년도약계좌",
    ],
)
def test_예적금성_서비스는_적금_카테고리로_분류한다(name: str) -> None:
    # "청년 적금" 같은 질의는 적금 카테고리로 좁혀 검색된다 —
    # 정책 적금·통장이 정책지원에 남아 있으면 그 검색에서 구조적으로 빠진다.
    doc = gov24_docs([service(지원유형="현금", 서비스명=name)])[0]
    assert doc.category == SAVING_CATEGORY


def test_예금성_서비스는_정기예금_카테고리로_분류한다() -> None:
    doc = gov24_docs([service(지원유형="현금", 서비스명="압류방지 전용 예금")])[0]
    assert doc.category == DEPOSIT_CATEGORY


@pytest.mark.parametrize(
    "name",
    [
        "전세보증금반환보증 보증료 지원",  # 상품이 아닌 지원제도
        "저축은행 신용보증 지원",  # "저축"은 저축은행의 일부 — 예적금 단서가 아니다
        "마이너스통장 대출이자 지원",  # 통장이 있어도 대출 관련 지원이면 상품이 아니다
    ],
)
def test_상품이_아닌_지원제도는_정책지원에_남는다(name: str) -> None:
    doc = gov24_docs([service(지원유형="현금", 서비스명=name)])[0]
    assert doc.category == CATEGORY


def test_상품_카테고리_상수는_공시_카테고리_어휘와_같다() -> None:
    # 재분류된 정책 상품은 공시 상품과 같은 칸에서 검색돼야 한다
    assert SAVING_CATEGORY in CATEGORIES
    assert DEPOSIT_CATEGORY in CATEGORIES


def test_문서는_지원내용과_신청정보를_담는다() -> None:
    docs = gov24_docs([service()])
    assert len(docs) == 1
    doc = docs[0]
    assert doc.product_key == "gov24:161300000076"
    assert doc.bank == "국토교통부"
    assert doc.name == "버팀목전세자금대출"
    assert doc.disclosure_month == "202605"
    assert "지원내용: 임차보증금 70% 이내 대출 지원" in doc.text
    assert "신청방법: 기금e든든 웹사이트 신청" in doc.text
    assert "신청: https://enhuf.molit.go.kr" in doc.text
    assert "구비서류" not in doc.text  # '해당없음'은 싣지 않는다


def test_긴_필드는_잘라서_싣는다() -> None:
    doc = gov24_docs([service(지원내용="가" * 2000)])[0]
    content_line = next(line for line in doc.text.splitlines() if line.startswith("지원내용:"))
    assert len(content_line) < 900
    assert content_line.endswith("…")


def test_수정일시가_없으면_공시월은_빈_값이다() -> None:
    doc = gov24_docs([service(수정일시="")])[0]
    assert doc.disclosure_month == ""
