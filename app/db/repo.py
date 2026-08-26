"""DB 접근 함수 모음 — 커밋은 호출자(요청 단위)가 담당한다."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, new_token, verify_password
from app.db.models import AuthToken, ChatMessage, User


def ensure_user(db: Session, username: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        return user
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def issue_token(db: Session, user: User) -> str:
    token = new_token()
    db.add(AuthToken(token=token, user_id=user.id))
    db.flush()
    return token


def user_for_token(db: Session, token: str) -> User | None:
    row = db.get(AuthToken, token)
    if row is None:
        return None
    return db.get(User, row.user_id)


def log_message(
    db: Session, session_id: str, role: str, content: str, user_id: int | None = None
) -> None:
    db.add(ChatMessage(session_id=session_id, role=role, content=content, user_id=user_id))
    db.flush()


def history_for_session(db: Session, session_id: str) -> list[ChatMessage]:
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    )
    return list(rows)
