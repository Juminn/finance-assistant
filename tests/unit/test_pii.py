from app.core.pii import mask_pii


def test_주민등록번호를_마스킹한다() -> None:
    masked = mask_pii("제 번호는 900101-1234567 입니다")
    assert "900101-1234567" not in masked
    assert "[주민등록번호 마스킹]" in masked


def test_카드번호를_마스킹한다() -> None:
    masked = mask_pii("카드 1234-5678-9012-3456 으로 결제")
    assert "1234-5678-9012-3456" not in masked
    assert "[카드번호 마스킹]" in masked


def test_계좌번호_형태의_긴_숫자를_마스킹한다() -> None:
    assert "110-234-567890" not in mask_pii("계좌는 110-234-567890 입니다")
    assert "9876543210123" not in mask_pii("계좌 9876543210123 으로 보내주세요")


def test_날짜와_금리와_짧은_숫자는_보존한다() -> None:
    text = "2026-08-27 기준 12개월 정기예금 최고금리는 3.50%입니다"
    assert mask_pii(text) == text
