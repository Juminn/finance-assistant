from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.api import auth, chat
from app.core.config import get_settings
from app.db import repo
from app.db.base import Base, make_engine

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app(engine: Engine | None = None) -> FastAPI:
    # LANGSMITH_* 등 라이브러리가 환경변수로 읽는 값을 위해 .env를 프로세스 환경에 올린다
    load_dotenv()
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        db_engine = engine or make_engine(settings.database_url)
        Base.metadata.create_all(db_engine)
        app.state.session_factory = sessionmaker(bind=db_engine)
        with app.state.session_factory() as db:
            repo.ensure_user(db, settings.demo_username, settings.demo_password)
            db.commit()
        yield

    app = FastAPI(title="금융 통합 비서", lifespan=lifespan)
    app.include_router(auth.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    if _WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
    return app


app = create_app()
