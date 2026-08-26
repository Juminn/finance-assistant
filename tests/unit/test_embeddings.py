from types import SimpleNamespace
from typing import Any

import pytest

from app.core.embeddings import EMBEDDING_DIM, embed_texts


class FakeEmbeddingsAPI:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def create(self, *, model: str, input: list[str]) -> Any:
        """입력 텍스트 길이를 값으로 채운 벡터를 돌려준다 (순서 검증용)."""
        self.calls.append(list(input))
        items = [SimpleNamespace(embedding=[float(len(text))] * EMBEDDING_DIM) for text in input]
        return SimpleNamespace(data=items)


class FakeOpenAI:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddingsAPI()


def test_텍스트_순서대로_임베딩을_반환한다() -> None:
    client = FakeOpenAI()
    vectors = embed_texts(client, ["a", "bb", "ccc"], model="test-model")

    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


def test_배치_크기만큼_나눠서_호출한다() -> None:
    client = FakeOpenAI()
    embed_texts(client, [f"t{i}" for i in range(5)], model="test-model", batch_size=2)

    assert [len(call) for call in client.embeddings.calls] == [2, 2, 1]


def test_빈_입력이면_API를_호출하지_않는다() -> None:
    client = FakeOpenAI()
    assert embed_texts(client, [], model="test-model") == []
    assert client.embeddings.calls == []


def test_배치_크기가_0이하면_거부한다() -> None:
    client = FakeOpenAI()
    with pytest.raises(ValueError):
        embed_texts(client, ["a"], model="test-model", batch_size=0)
