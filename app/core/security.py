"""비밀번호 해시와 토큰 발급 — 표준 라이브러리만 사용한다."""

import hashlib
import hmac
import secrets

_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    salt, _, expected = hashed.partition("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return hmac.compare_digest(digest.hex(), expected)


def new_token() -> str:
    return secrets.token_hex(32)
