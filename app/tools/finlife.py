"""금융감독원 금융상품통합비교공시 오픈API 공용 클라이언트."""

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

BASE_URL = "https://finlife.fss.or.kr/finlifeapi"

# 권역코드 (topFinGrpNo)
BANK = "020000"  # 은행
CREDIT_FINANCE = "030200"  # 여신전문금융
SAVING_BANK = "030300"  # 저축은행
INSURANCE = "050000"  # 보험
SECURITIES = "060000"  # 금융투자

# 카탈로그 색인이 훑는 전 권역
ALL_GROUPS = (BANK, CREDIT_FINANCE, SAVING_BANK, INSURANCE, SECURITIES)

# 같은 상품코드로 서로 다른 상품이 공시될 때 뒤엣것을 구분하는 접미사
DUP_MARK = "#"

# 상품 엔드포인트 — 도구·카탈로그가 공유하는 단일 정의
DEPOSIT_ENDPOINT = "depositProductsSearch.json"
SAVING_ENDPOINT = "savingProductsSearch.json"
MORTGAGE_ENDPOINT = "mortgageLoanProductsSearch.json"
RENT_ENDPOINT = "rentHouseLoanProductsSearch.json"
CREDIT_ENDPOINT = "creditLoanProductsSearch.json"

_OK = "000"


def base_product_code(product_code: str) -> str:
    """중복 공시 접미사를 뗀 원래 상품코드. 옵션 목록과 조인할 때 쓴다."""
    return product_code.split(DUP_MARK, 1)[0]


def to_float(value: object) -> float | None:
    """공시 응답의 금리 값을 안전하게 float으로 바꾼다. 빈 값·비숫자는 None."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def to_int(value: object) -> int | None:
    """공시 응답의 기간 값을 안전하게 int로 바꾼다. 빈 값·비숫자는 None."""
    number = to_float(value)
    return None if number is None else int(number)


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
            # 같은 (회사, 상품코드)로 서로 다른 상품이 공시되는 경우가 있다.
            # 그대로 덮어쓰면 상품이 조용히 사라지므로 접미사를 붙여 둘 다 남긴다.
            key = (base["fin_co_no"], base["fin_prdt_cd"])
            duplicate = 2
            while key in bases:
                if bases[key] == base:
                    break  # 페이지가 겹쳐 같은 행이 다시 온 것 — 새 키를 만들지 않는다
                key = (base["fin_co_no"], f"{base['fin_prdt_cd']}{DUP_MARK}{duplicate}")
                duplicate += 1
            bases[key] = base
        options.extend(result.get("optionList", []))
        if page_no >= int(result.get("max_page_no") or 1):
            break
        page_no += 1
    return bases, options


def fetch_all_groups(
    client: httpx.Client,
    endpoint: str,
    *,
    api_key: str,
    groups: Sequence[str] = ALL_GROUPS,
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    """여러 권역을 훑어 (상품 기본정보 맵, 옵션 목록)을 합쳐 반환한다.

    금융회사코드(fin_co_no)는 권역 간 고유하므로 기본정보 맵은 그대로 합쳐진다.
    옵션은 완전히 동일한 행이 두 번 담기지 않도록 걸러, 같은 상품이 중복
    계상되는 것을 막는다.
    """
    merged_bases: dict[tuple[str, str], dict[str, Any]] = {}
    merged_options: list[dict[str, Any]] = []
    seen_options: set[str] = set()

    # 권역은 서로 독립이라 동시에 훑는다. 순차로 돌면 권역 수만큼 응답이 느려진다.
    # 결과는 groups 순서대로 합쳐 호출마다 같은 순서가 나오게 한다.
    def fetch_group(
        group: str,
    ) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
        return fetch_all(client, endpoint, api_key=api_key, top_fin_grp_no=group)

    if len(groups) == 1:
        fetched = [fetch_group(groups[0])]
    else:
        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            fetched = list(pool.map(fetch_group, groups))

    for bases, options in fetched:
        merged_bases.update(bases)
        for option in options:
            fingerprint = json.dumps(option, sort_keys=True, ensure_ascii=False, default=str)
            if fingerprint in seen_options:
                continue
            seen_options.add(fingerprint)
            merged_options.append(option)

    return merged_bases, merged_options
