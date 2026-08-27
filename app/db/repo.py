from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatMessage


def log_message(db: Session, session_id: str, role: str, content: str) -> None:
    db.add(ChatMessage(session_id=session_id, role=role, content=content))


def history_for_session(db: Session, session_id: str) -> list[ChatMessage]:
    statement = (
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    )
    return list(db.scalars(statement))
