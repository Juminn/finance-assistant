from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.db import repo
from app.db.base import Base, make_engine


@pytest.fixture
def db() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_ensure_user는_중복_생성하지_않는다(db: Session) -> None:
    first = repo.ensure_user(db, "demo", "pw1234!")
    second = repo.ensure_user(db, "demo", "pw1234!")
    assert first.id == second.id


def test_올바른_자격증명으로_인증한다(db: Session) -> None:
    repo.ensure_user(db, "demo", "pw1234!")
    assert repo.authenticate(db, "demo", "pw1234!") is not None
    assert repo.authenticate(db, "demo", "wrong") is None
    assert repo.authenticate(db, "nobody", "pw1234!") is None


def test_토큰을_발급하고_사용자를_되찾는다(db: Session) -> None:
    user = repo.ensure_user(db, "demo", "pw1234!")
    token = repo.issue_token(db, user)
    found = repo.user_for_token(db, token)
    assert found is not None
    assert found.id == user.id
    assert repo.user_for_token(db, "no-such-token") is None


def test_대화를_저장하고_세션별로_순서대로_읽는다(db: Session) -> None:
    repo.log_message(db, "s1", "user", "안녕")
    repo.log_message(db, "s1", "assistant", "안녕하세요")
    repo.log_message(db, "s2", "user", "다른 세션")

    history = repo.history_for_session(db, "s1")
    assert [(m.role, m.content) for m in history] == [
        ("user", "안녕"),
        ("assistant", "안녕하세요"),
    ]
