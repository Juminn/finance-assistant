"""vector_repo의 결정적 부분 — DB 없이 검증 가능한 계약."""

from app.db.vector_models import ProductEmbedding
from app.db.vector_repo import UPSERT_COLUMNS


def test_upsert_컬럼은_모델의_비PK_컬럼과_항상_일치한다() -> None:
    model_columns = {
        column.name for column in ProductEmbedding.__table__.columns if not column.primary_key
    }
    assert set(UPSERT_COLUMNS) == model_columns
