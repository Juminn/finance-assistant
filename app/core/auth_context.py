"""요청 단위 인증 컨텍스트 — 도구가 사용자 인증 여부를 확인할 때 쓴다.

에이전트 도구는 HTTP 요청 객체에 접근할 수 없으므로, 요청을 처리하는 동안
ContextVar에 인증 여부를 실어 도구 단위 권한 게이트를 건다.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

_authenticated: ContextVar[bool] = ContextVar("request_authenticated", default=False)


def is_authenticated() -> bool:
    return _authenticated.get()


@contextmanager
def authenticated_request(value: bool = True) -> Generator[None]:
    token = _authenticated.set(value)
    try:
        yield
    finally:
        _authenticated.reset(token)
