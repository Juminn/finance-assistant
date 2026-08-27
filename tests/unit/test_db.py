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


def test_대화를_저장하고_세션별로_순서대로_읽는다(db: Session) -> None:
    repo.log_message(db, "s1", "user", "안녕")
    repo.log_message(db, "s1", "assistant", "안녕하세요")
    repo.log_message(db, "s2", "user", "다른 세션")

    history = repo.history_for_session(db, "s1")
    assert [(m.role, m.content) for m in history] == [
        ("user", "안녕"),
        ("assistant", "안녕하세요"),
    ]
