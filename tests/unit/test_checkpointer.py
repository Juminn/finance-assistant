from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

import app.db.checkpointer as checkpointer_module
from app.db.checkpointer import make_checkpointer


def test_postgres_url이면_영속_체크포인터를_만든다(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = MemorySaver()
    seen: list[str] = []

    def fake_postgres(url: str) -> Any:
        seen.append(url)
        return sentinel

    monkeypatch.setattr(checkpointer_module, "_postgres_checkpointer", fake_postgres)
    assert make_checkpointer("postgresql://u:p@host/db") is sentinel
    assert seen == ["postgresql://u:p@host/db"]


def test_sqlite_url이면_메모리_체크포인터로_폴백한다() -> None:
    # SQLite 환경은 개발·테스트 전용 — 재시작 시 멀티턴 문맥이 사라지는 걸 감수한다
    assert isinstance(make_checkpointer("sqlite://"), MemorySaver)
    assert isinstance(make_checkpointer("sqlite:///./data/app.db"), MemorySaver)
