"""OpenAI 임베딩 호출 — 클라이언트를 주입받아 테스트 가능하게 유지한다."""

from typing import Any, Protocol

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
_DEFAULT_BATCH_SIZE = 100


class EmbeddingsResource(Protocol):
    def create(self, *, model: str, input: list[str]) -> Any: ...


class EmbeddingClient(Protocol):
    """OpenAI 클라이언트와 테스트용 가짜 클라이언트가 모두 만족하는 최소 인터페이스."""

    @property
    def embeddings(self) -> EmbeddingsResource: ...


def embed_texts(
    client: EmbeddingClient,
    texts: list[str],
    *,
    model: str = EMBEDDING_MODEL,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> list[list[float]]:
    """텍스트 목록을 입력 순서 그대로의 벡터 목록으로 바꾼다.

    API 문서는 응답 배열의 순서를 보장하지 않으므로 index 필드로 재정렬하고,
    개수·차원이 어긋나면 조용히 오염되는 대신 즉시 실패시킨다.
    """
    if batch_size <= 0:
        raise ValueError("batch_size는 1 이상이어야 합니다")
    if not texts:
        return []

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        response = client.embeddings.create(model=model, input=chunk)
        items = sorted(response.data, key=lambda item: getattr(item, "index", 0))
        if len(items) != len(chunk):
            raise ValueError(
                f"임베딩 응답 개수가 다릅니다: 입력 {len(chunk)}건, 응답 {len(items)}건"
            )
        for item in items:
            vector = [float(value) for value in item.embedding]
            if len(vector) != EMBEDDING_DIM:
                raise ValueError(
                    f"임베딩 차원이 다릅니다: 기대 {EMBEDDING_DIM}, 실제 {len(vector)}"
                )
            vectors.append(vector)
    return vectors
