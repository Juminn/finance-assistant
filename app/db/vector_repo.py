"""pgvector 저장소 접근 — 상품 문서 색인과 유사도 검색."""

from sqlalchemy import Engine, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.vector_base import VectorBase
from app.db.vector_models import ProductEmbedding
from app.tools.catalog import ProductDoc

_UPSERT_COLUMNS = (
    "category",
    "bank",
    "name",
    "text",
    "content_hash",
    "disclosure_month",
    "embedding",
)
_CHUNK_SIZE = 200


def ensure_vector_schema(engine: Engine) -> None:
    """pgvector 확장과 테이블을 준비한다. PostgreSQL에서만 호출할 것."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    VectorBase.metadata.create_all(engine)


def existing_hashes(db: Session) -> dict[str, str]:
    """이미 색인된 (product_key → content_hash) 맵."""
    rows = db.execute(select(ProductEmbedding.product_key, ProductEmbedding.content_hash))
    return dict(rows.tuples())


def upsert_docs(db: Session, pairs: list[tuple[ProductDoc, list[float]]]) -> None:
    """문서와 임베딩을 색인한다. 이미 있는 product_key는 갱신한다."""
    rows = [
        {
            "product_key": doc.product_key,
            "category": doc.category,
            "bank": doc.bank,
            "name": doc.name,
            "text": doc.text,
            "content_hash": doc.content_hash,
            "disclosure_month": doc.disclosure_month,
            "embedding": vector,
        }
        for doc, vector in pairs
    ]

    for start in range(0, len(rows), _CHUNK_SIZE):
        statement = insert(ProductEmbedding).values(rows[start : start + _CHUNK_SIZE])
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["product_key"],
                set_={column: statement.excluded[column] for column in _UPSERT_COLUMNS},
            )
        )


def delete_keys(db: Session, keys: list[str]) -> None:
    if not keys:
        return
    db.execute(delete(ProductEmbedding).where(ProductEmbedding.product_key.in_(keys)))


def search_similar(
    db: Session,
    query_vector: list[float],
    *,
    top_k: int = 5,
    category: str | None = None,
) -> list[tuple[ProductEmbedding, float]]:
    """질의 벡터와 코사인 거리가 가까운 상품을 반환한다. (거리가 작을수록 유사)"""
    distance = ProductEmbedding.embedding.cosine_distance(query_vector)
    statement = select(ProductEmbedding, distance.label("distance"))
    if category:
        statement = statement.where(ProductEmbedding.category == category)
    statement = statement.order_by(distance).limit(top_k)
    return [(row[0], float(row[1])) for row in db.execute(statement)]
