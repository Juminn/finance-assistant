from sqlalchemy.orm import DeclarativeBase


class VectorBase(DeclarativeBase):
    """pgvector 전용 메타데이터.

    벡터 컬럼은 PostgreSQL에서만 만들 수 있으므로, 앱 기본 테이블(Base)과
    메타데이터를 분리해 SQLite 테스트 DB에서는 생성되지 않게 한다.
    """
