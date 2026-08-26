"""응답에 실릴 수 있는 개인정보(주민번호·카드번호·계좌번호) 마스킹."""

import re

_CARD = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b")
_RRN = re.compile(r"\b\d{6}-[1-4]\d{6}\b")
# 하이픈 포함 계좌번호 후보 또는 10자리 이상 연속 숫자 — 총 자릿수 10 미만이면 보존
_ACCOUNT = re.compile(r"\b\d[\d-]{8,18}\d\b")


def _mask_account(match: re.Match[str]) -> str:
    digits = sum(ch.isdigit() for ch in match.group())
    if digits < 10:
        return match.group()
    return "[계좌번호 마스킹]"


def mask_pii(text: str) -> str:
    text = _CARD.sub("[카드번호 마스킹]", text)
    text = _RRN.sub("[주민등록번호 마스킹]", text)
    return _ACCOUNT.sub(_mask_account, text)
