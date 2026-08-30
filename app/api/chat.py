# langgraph 그래프의 제네릭이 부분적으로 Unknown이라 invoke 지점만 완화한다
# pyright: reportUnknownMemberType=false

import logging
import threading
import zlib
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.graph import get_agent
from app.api.deps import DbDep
from app.core.pii import mask_pii
from app.db import repo

router = APIRouter(tags=["chat"])

# 같은 세션의 동시 요청이 같은 체크포인트에서 갈라져 한쪽 턴이 사라지지 않게
# 세션 단위로 직렬화한다. 세션마다 락을 만들면 세션 수만큼 새므로 고정 개수
# 스트라이프를 쓴다 — 다른 세션끼리 드물게 같은 락을 기다리는 정도는 감수한다.
_LOCK_STRIPES = 64
_session_locks = [threading.Lock() for _ in range(_LOCK_STRIPES)]


def _session_lock(session_id: str) -> threading.Lock:
    return _session_locks[zlib.crc32(session_id.encode()) % _LOCK_STRIPES]


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


@router.post("/chat")
def chat(body: ChatRequest, db: DbDep) -> ChatResponse:
    session_id = body.session_id or uuid4().hex
    with _session_lock(session_id):
        # 실패한 턴도 체크포인터에는 남으므로, 화면 이력과 어긋나지 않게
        # 사용자 메시지는 호출 전에 먼저 기록·커밋한다
        repo.log_message(db, session_id, "user", body.message)
        db.commit()
        try:
            result = get_agent().invoke(
                {"messages": [HumanMessage(body.message)]},
                config={"configurable": {"thread_id": session_id}},
            )
        except Exception:
            # session_id는 그 대화를 여는 유일한 비밀이므로 로그에 전문을 남기지 않는다
            logging.exception("에이전트 호출 실패 (session=%s…)", session_id[:8])
            raise HTTPException(
                status_code=502, detail="답변 생성 중 오류가 발생했어요. 잠시 후 다시 시도해주세요."
            ) from None
        reply = mask_pii(str(result["messages"][-1].content))
        repo.log_message(db, session_id, "assistant", reply)
    return ChatResponse(session_id=session_id, reply=reply)


@router.get("/history/{session_id}")
def history(session_id: str, db: DbDep) -> HistoryResponse:
    rows = repo.history_for_session(db, session_id)
    messages = [HistoryMessage(role=m.role, content=m.content) for m in rows]
    return HistoryResponse(session_id=session_id, messages=messages)
