from app.db.base import is_postgres, normalize_db_url


def test_neon이_주는_postgresql_주소를_psycopg_드라이버로_바꾼다() -> None:
    url = "postgresql://user:pw@ep-x.ap-southeast-1.aws.neon.tech/db?sslmode=require"
    assert normalize_db_url(url) == (
        "postgresql+psycopg://user:pw@ep-x.ap-southeast-1.aws.neon.tech/db?sslmode=require"
    )


def test_구형_postgres_스킴도_처리한다() -> None:
    assert normalize_db_url("postgres://u:p@host/db").startswith("postgresql+psycopg://")


def test_이미_psycopg_드라이버면_그대로_둔다() -> None:
    url = "postgresql+psycopg://u:p@host/db"
    assert normalize_db_url(url) == url


def test_다른_드라이버_지정도_psycopg로_통일한다() -> None:
    assert normalize_db_url("postgresql+asyncpg://u:p@host/db") == (
        "postgresql+psycopg://u:p@host/db"
    )
    assert normalize_db_url("postgresql+psycopg2://u:p@host/db") == (
        "postgresql+psycopg://u:p@host/db"
    )


def test_sqlite_주소는_건드리지_않는다() -> None:
    assert normalize_db_url("sqlite:///./data/app.db") == "sqlite:///./data/app.db"


def test_postgres_여부를_판별한다() -> None:
    assert is_postgres("postgresql://u:p@host/db") is True
    assert is_postgres("postgres://u:p@host/db") is True
    assert is_postgres("postgresql+psycopg://u:p@host/db") is True
    assert is_postgres("sqlite:///./data/app.db") is False
