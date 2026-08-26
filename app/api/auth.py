from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbDep
from app.db import repo

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


@router.post("/auth/login")
def login(body: LoginRequest, db: DbDep) -> LoginResponse:
    user = repo.authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다")
    return LoginResponse(token=repo.issue_token(db, user), username=user.username)
