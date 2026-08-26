from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.db import session as session_module
from app.db.base import make_engine


@pytest.fixture(autouse=True)
def reset_engine() -> Iterator[None]:
    session_module.set_engine(None)
    yield
    session_module.set_engine(None)


def test_set_engine으로_주입한_엔진을_전역이_사용한다() -> None:
    engine = make_engine("sqlite://")
    session_module.set_engine(engine)
    assert session_module.get_engine() is engine


def test_세션_팩토리는_주입된_엔진에_바인딩된다() -> None:
    engine = make_engine("sqlite://")
    session_module.set_engine(engine)
    with session_module.get_session_factory()() as db:
        assert db.get_bind() is engine
        assert db.scalar(text("select 1")) == 1


def test_엔진을_바꾸면_세션_팩토리도_따라온다() -> None:
    first = make_engine("sqlite://")
    second = make_engine("sqlite://")
    session_module.set_engine(first)
    session_module.get_session_factory()
    session_module.set_engine(second)
    with session_module.get_session_factory()() as db:
        assert db.get_bind() is second


def test_vector_search_enabled는_엔진_방언으로_판정한다() -> None:
    session_module.set_engine(make_engine("sqlite://"))
    assert session_module.vector_search_enabled() is False
