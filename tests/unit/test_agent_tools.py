"""에이전트 도구 바인딩의 권한 게이트 검증."""

from typing import Any

import httpx
import pytest
import respx
from pydantic_settings import SettingsConfigDict

from app.agents.tools import compare_credit_loans
from app.core.auth_context import authenticated_request, is_authenticated
from app.core.config import Settings
from app.tools.finlife import BASE_URL

CREDIT_URL = f"{BASE_URL}/creditLoanProductsSearch.json"


class KeyedSettings(Settings):
    model_config = SettingsConfigDict(env_file=None)


@pytest.fixture
def keyed_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.tools.get_settings", lambda: KeyedSettings(finlife_api_key="key")
    )


def test_기본값은_비인증_상태다() -> None:
    assert is_authenticated() is False


def test_컨텍스트_안에서만_인증_상태가_된다() -> None:
    with authenticated_request(True):
        assert is_authenticated() is True
    assert is_authenticated() is False


@respx.mock
def test_비로그인이면_신용대출_도구는_로그인_안내만_반환한다(keyed_settings: None) -> None:
    route = respx.get(CREDIT_URL).mock(return_value=httpx.Response(500))
    result = compare_credit_loans.invoke({})
    assert "로그인" in result
    assert not route.called


@respx.mock
def test_로그인_상태면_신용대출을_조회한다(keyed_settings: None) -> None:
    payload: dict[str, Any] = {
        "result": {
            "err_cd": "000",
            "err_msg": "정상",
            "total_count": 1,
            "max_page_no": 1,
            "now_page_no": 1,
            "baseList": [
                {
                    "dcls_month": "202608",
                    "fin_co_no": "A",
                    "fin_prdt_cd": "P1",
                    "kor_co_nm": "가은행",
                    "fin_prdt_nm": "가신용대출",
                    "crdt_prdt_type_nm": "일반신용대출",
                }
            ],
            "optionList": [
                {
                    "fin_co_no": "A",
                    "fin_prdt_cd": "P1",
                    "crdt_lend_rate_type": "A",
                    "crdt_grad_avg": 5.5,
                    "crdt_grad_1": 4.2,
                }
            ],
        }
    }
    respx.get(CREDIT_URL).mock(return_value=httpx.Response(200, json=payload))

    with authenticated_request(True):
        result = compare_credit_loans.invoke({})

    assert "가은행" in result
    assert "5.50" in result
