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
