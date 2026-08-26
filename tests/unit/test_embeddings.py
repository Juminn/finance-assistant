from types import SimpleNamespace
from typing import Any

import pytest

from app.core.embeddings import EMBEDDING_DIM, embed_texts


class ClientWith:
    def __init__(self, api: Any) -> None:
        self.embeddings = api


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


class ShuffledEmbeddingsAPI:
    """응답을 index 필드와 함께 뒤섞어 반환한다 — 순서 계약 검증용."""

    def create(self, *, model: str, input: list[str]) -> Any:
        items = [
            SimpleNamespace(index=i, embedding=[float(len(text))] * EMBEDDING_DIM)
            for i, text in enumerate(input)
        ]
        return SimpleNamespace(data=list(reversed(items)))


def test_응답이_뒤섞여_와도_index로_원래_순서를_복원한다() -> None:
    client = ClientWith(ShuffledEmbeddingsAPI())
    vectors = embed_texts(client, ["a", "bb", "ccc"], model="test-model")
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]


class ShortEmbeddingsAPI:
    def create(self, *, model: str, input: list[str]) -> Any:
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0] * EMBEDDING_DIM)])


def test_응답_개수가_입력과_다르면_오류를_던진다() -> None:
    client = ClientWith(ShortEmbeddingsAPI())
    with pytest.raises(ValueError):
        embed_texts(client, ["a", "b"], model="test-model")


class WrongDimEmbeddingsAPI:
    def create(self, *, model: str, input: list[str]) -> Any:
        return SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=[1.0] * 8) for i in range(len(input))]
        )


def test_벡터_차원이_다르면_오류를_던진다() -> None:
    client = ClientWith(WrongDimEmbeddingsAPI())
    with pytest.raises(ValueError):
        embed_texts(client, ["a"], model="test-model")
