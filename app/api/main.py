from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from app.api import chat
from app.db.base import Base
from app.db.session import get_engine, get_session_factory, set_engine

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app(engine: Engine | None = None) -> FastAPI:
    # LANGSMITH_* 등 라이브러리가 환경변수로 읽는 값을 위해 .env를 프로세스 환경에 올린다
    load_dotenv()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # 주입된 엔진을 전역 소유 지점에 등록해 API·에이전트 도구·배치가
        # 전부 같은 DB를 보게 한다 (벡터 스키마는 색인 배치가 소유)
        if engine is not None:
            set_engine(engine)
        db_engine = get_engine()
        Base.metadata.create_all(db_engine)
        app.state.session_factory = get_session_factory()
        yield

    app = FastAPI(title="금융 통합 비서", lifespan=lifespan)
    app.include_router(chat.router, prefix="/api")
    if _WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
    return app


app = create_app()
