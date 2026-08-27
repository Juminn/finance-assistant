"""pgvector 저장소 접근 — 상품 문서 색인과 유사도 검색."""

from sqlalchemy import Engine, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.vector_base import VectorBase
from app.db.vector_models import ProductEmbedding
from app.tools.catalog import ProductDoc

# 모델에서 파생 — 컬럼을 추가해도 upsert 갱신 목록이 자동으로 따라온다
UPSERT_COLUMNS: tuple[str, ...] = tuple(
    column.name for column in ProductEmbedding.__table__.columns if not column.primary_key
)
_CHUNK_SIZE = 200


def ensure_vector_schema(engine: Engine) -> None:
    """pgvector 확장·테이블·ANN 인덱스를 준비한다. PostgreSQL에서만 호출할 것."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    VectorBase.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_product_embeddings_embedding_hnsw "
                "ON product_embeddings USING hnsw (embedding vector_cosine_ops)"
            )
        )


def index_ready(db: Session) -> bool:
    """색인에 문서가 1건이라도 있는지 — 도구가 '미준비' 안내를 구분하는 기준."""
    return db.scalar(select(ProductEmbedding.product_key).limit(1)) is not None


def existing_hashes(db: Session) -> dict[str, str]:
    """이미 색인된 (product_key → content_hash) 맵."""
    rows = db.execute(select(ProductEmbedding.product_key, ProductEmbedding.content_hash))
    # dict(result)는 Result의 keys()를 매핑 프로토콜로 오인하므로 all()로 행 목록을 넘긴다
    return dict(rows.tuples().all())


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
                set_={column: statement.excluded[column] for column in UPSERT_COLUMNS},
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
