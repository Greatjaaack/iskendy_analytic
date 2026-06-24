"""Роутер авторизации: вход по логину/паролю (выдаёт JWT) и проверка текущей сессии."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import create_token, require_auth, verify_credentials

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str
    username: str


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn) -> TokenOut:
    """Проверить логин/пароль и выдать JWT сессии."""
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
