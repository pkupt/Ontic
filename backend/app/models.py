"""Pydantic 请求/响应模型。"""
from typing import Any, Optional
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    username: str
    role: str


class QueryRequest(BaseModel):
    where: Optional[Any] = None
    select: Optional[list[str]] = None
    orderBy: Optional[dict] = None
    limit: int = 100
    offset: int = 0


class QueryResponse(BaseModel):
    rows: list[dict]
    count: int


class ActionExecuteRequest(BaseModel):
    params: dict = {}


class ActionExecuteResponse(BaseModel):
    ok: bool = True
    detail: dict = {}
