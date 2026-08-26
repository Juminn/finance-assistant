"""금융감독원 금융상품통합비교공시 오픈API 공용 클라이언트."""

from typing import Any

import httpx

BASE_URL = "https://finlife.fss.or.kr/finlifeapi"

# 권역코드 (topFinGrpNo)
BANK = "020000"  # 은행
SAVING_BANK = "030300"  # 저축은행

_OK = "000"


class FinlifeError(Exception):
    """금융상품통합비교공시 API 호출 실패."""


def fetch_page(
    client: httpx.Client,
    endpoint: str,
    *,
    api_key: str,
    top_fin_grp_no: str,
    page_no: int = 1,
) -> dict[str, Any]:
    """한 페이지를 조회해 result 본문을 반환한다. 실패 시 FinlifeError."""
    try:
        response = client.get(
            f"{BASE_URL}/{endpoint}",
            params={"auth": api_key, "topFinGrpNo": top_fin_grp_no, "pageNo": page_no},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FinlifeError(f"금융상품 API 호출 실패: {exc}") from exc

    result: dict[str, Any] = response.json().get("result", {})
    err_cd = result.get("err_cd")
    if err_cd != _OK:
        err_msg = result.get("err_msg", "알 수 없는 오류")
        raise FinlifeError(f"금융상품 API 오류 [{err_cd}]: {err_msg}")
    return result


def fetch_all(
    client: httpx.Client,
    endpoint: str,
    *,
    api_key: str,
    top_fin_grp_no: str,
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    """전 페이지를 수집해 (상품 기본정보 맵, 옵션 목록)을 반환한다.

    기본정보 맵의 키는 (금융회사코드, 상품코드)로, 옵션과 조인할 때 쓴다.
    """
    bases: dict[tuple[str, str], dict[str, Any]] = {}
    options: list[dict[str, Any]] = []
    page_no = 1
    while True:
        result = fetch_page(
            client, endpoint, api_key=api_key, top_fin_grp_no=top_fin_grp_no, page_no=page_no
        )
        for base in result.get("baseList", []):
            bases[(base["fin_co_no"], base["fin_prdt_cd"])] = base
        options.extend(result.get("optionList", []))
        if page_no >= int(result.get("max_page_no") or 1):
            break
        page_no += 1
    return bases, options
