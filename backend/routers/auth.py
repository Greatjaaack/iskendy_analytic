"""Роутер авторизации: вход по логину/паролю (выдаёт JWT) и проверка текущей сессии."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

import ratelimit
from auth import create_token, require_auth, verify_credentials

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    # Длины ограничены, чтобы мегабайтная «строка логина» не попадала в сверку и логи.
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class TokenOut(BaseModel):
    token: str
    username: str


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request) -> TokenOut:
    """Проверить логин/пароль и выдать JWT сессии.

    Попытки ограничены по адресу (`ratelimit.LOGIN_LIMIT` в минуту): дашборд открыт в
    интернет, пароль один общий, и без лимита его можно было перебирать со скоростью сети.
    """
    ratelimit.guard(request, ratelimit.LOGIN_LIMIT, "login")
    if not verify_credentials(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )
    return TokenOut(token=create_token(body.username), username=body.username)


@router.get("/me")
def me(user: dict = Depends(require_auth)) -> dict:
    """Вернуть субъект текущей сессии (для проверки токена фронтом)."""
    return {"username": user.get("sub")}
