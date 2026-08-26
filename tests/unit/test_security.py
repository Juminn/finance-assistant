from app.core.security import hash_password, new_token, verify_password


def test_해시는_원문과_다르고_검증에_성공한다() -> None:
    hashed = hash_password("secret-pw")
    assert hashed != "secret-pw"
    assert verify_password("secret-pw", hashed)


def test_같은_비밀번호라도_해시는_매번_다르다() -> None:
    assert hash_password("secret-pw") != hash_password("secret-pw")


def test_틀린_비밀번호는_검증에_실패한다() -> None:
    hashed = hash_password("secret-pw")
    assert not verify_password("wrong-pw", hashed)


def test_토큰은_충분히_길고_매번_다르다() -> None:
    token = new_token()
    assert len(token) >= 32
    assert token != new_token()
