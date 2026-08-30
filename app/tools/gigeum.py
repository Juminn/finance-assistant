"""주택도시기금 기금e든든 공공데이터(CSV) — 주택 정책대출 심층 카탈로그.

서민금융상품기본정보에는 없는 세부 변형 상품(신생아 특례·청년 주택드림·월세대출 등)과
소득·보증금·기간 구간별 기본금리를 수집한다.
연 1회 갱신되는 스냅샷이라, 파일이 교체되면 아래 URL·기준일 상수를 함께 갱신한다.
(다운로드 링크는 data.go.kr 15134235·15134239 페이지의 CSV 파일이다.)

같은 배포 묶음의 우대금리 CSV(15134241)는 쓰지 않는다: 어느 상품에 적용되는지
연결키가 없어 잘못된 상품 귀속 위험이 있고, 우대 항목이 검색 상위를 차지해
정작 상품 문서를 밀어냈다. 상품별 우대는 주택도시기금 포털 크롤로 보완할 것.
"""

import csv
import io

import httpx

from app.tools.catalog import ProductDoc
from app.tools.smfg import CATEGORY

_DOWNLOAD = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
BASE_INFO_URL = f"{_DOWNLOAD}?atchFileId=FILE_000000003508349&fileDetailSn=1"
RATE_URL = f"{_DOWNLOAD}?atchFileId=FILE_000000003511510&fileDetailSn=1"

# 데이터 기준일(공시월) — 파일 교체 시 URL과 함께 갱신
AS_OF = "202510"

_FUND = "주택도시기금"

Row = dict[str, str]


class GigeumError(Exception):
    """기금e든든 CSV 수집 실패."""


def _download_csv(client: httpx.Client, url: str, *, required_column: str) -> list[Row]:
    try:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise GigeumError(f"기금e든든 CSV 다운로드 실패: {exc}") from exc

    text = response.content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or required_column not in [c.strip() for c in reader.fieldnames]:
        raise GigeumError(f"기금e든든 응답이 기대한 CSV가 아닙니다: {text[:80]!r}")
    return [
        {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
        for row in reader
    ]


def fetch_gigeum_tables(client: httpx.Client) -> tuple[list[Row], list[Row]]:
    """(상품기본정보, 구간별 기본금리) 두 표를 내려받아 파싱한다."""
    base = _download_csv(client, BASE_INFO_URL, required_column="상품명")
    rates = _download_csv(client, RATE_URL, required_column="기본금리")
    return base, rates


def _to_int(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None


def _won_text(won: int) -> str:
    eok, remainder = divmod(won, 100_000_000)
    man = remainder // 10_000
    if eok and man:
        return f"{eok}억{man:,}만원"
    if eok:
        return f"{eok}억원"
    return f"{man:,}만원"


def _won_range(label: str, low: str, high: str) -> str:
    low_won, high_won = _to_int(low), _to_int(high)
    if not high_won:
        return ""
    if not low_won:
        return f"{label} {_won_text(high_won)} 이하"
    return f"{label} {_won_text(low_won)} 초과 {_won_text(high_won)} 이하"


def _months_text(months: int) -> str:
    years, remainder = divmod(months, 12)
    return f"{years}년" if years and not remainder else f"{months}개월"


def _months_range(low: str, high: str) -> str:
    low_m, high_m = _to_int(low), _to_int(high)
    if not high_m:
        return ""
    if not low_m:
        return f"기간 {_months_text(high_m)} 이하"
    return f"기간 {_months_text(low_m)} 초과 {_months_text(high_m)} 이하"


def _rate_line(row: Row) -> str | None:
    rate = row.get("기본금리", "")
    if not rate:
        return None
    parts = [
        part
        for part in (
            _won_range("소득", row.get("소득최소금액", ""), row.get("소득최대금액", "")),
            _won_range("보증금", row.get("보증금최소금액", ""), row.get("보증금최대금액", "")),
            _months_range(row.get("대출최소기간", ""), row.get("대출최대기간", "")),
        )
        if part
    ]
    condition = " · ".join(parts) if parts else "전 구간"
    return f"- {condition}: 연 {rate}%"


def gigeum_docs(base: list[Row], rates: list[Row]) -> list[ProductDoc]:
    """두 표를 상품당 한 건의 문서(구간별 금리표 포함)로 바꾼다."""
    rate_lines: dict[str, list[str]] = {}
    for row in rates:
        line = _rate_line(row)
        if line:
            rate_lines.setdefault(row.get("상품명", ""), []).append(line)

    period = f"{AS_OF[:4]}-{AS_OF[4:]}"
    docs: list[ProductDoc] = []
    seen: set[str] = set()

    for row in base:
        name = row.get("상품명", "")
        if not name:
            continue
        key = f"gigeum:{name}"[:128]
        if key in seen:
            continue
        seen.add(key)

        taxonomy = " > ".join(
            part
            for part in (
                row.get("상품대분류명", ""),
                row.get("상품중분류명", ""),
                row.get("상품소분류명", ""),
            )
            if part
        )
        lines = [f"[{CATEGORY}] {_FUND} {name}"]
        if taxonomy:
            lines.append(f"분류: {taxonomy}")
        description = row.get("상품설명", "")
        if description:
            lines.append(f"설명: {description}")
        if rate_lines.get(name):
            lines.append(f"기본금리(우대 적용 전, 기금e든든 {period} 기준):")
            lines.extend(rate_lines[name])

        docs.append(
            ProductDoc(
                product_key=key,
                category=CATEGORY,
                bank=_FUND,
                name=name[:200],
                text="\n".join(lines),
                disclosure_month=AS_OF,
            )
        )
    return docs
