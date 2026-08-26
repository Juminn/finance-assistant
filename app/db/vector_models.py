from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.embeddings import EMBEDDING_DIM
from app.db.vector_base import VectorBase


class ProductEmbedding(VectorBase):
    """상품 문서 한 건과 그 임베딩."""

    __tablename__ = "product_embeddings"

    product_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    bank: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(32))
    disclosure_month: Mapped[str] = mapped_column(String(6))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
