from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import repo
from app.db.models import User


def get_db(request: Request) -> Iterator[Session]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        yield session
        session.commit()


DbDep = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbDep, authorization: Annotated[str | None, Header()] = None
) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return repo.user_for_token(db, authorization.removeprefix("Bearer "))


OptionalUserDep = Annotated[User | None, Depends(get_current_user)]


def require_user(user: OptionalUserDep) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return user


UserDep = Annotated[User, Depends(require_user)]
