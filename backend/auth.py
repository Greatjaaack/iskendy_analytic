"""Авторизация дашборда: один общий логин/пароль из `.env`, сессия — JWT в localStorage.

JWT (HS256) подписывается вручную через `hmac` — без внешних зависимостей. Токен кладётся
фронтом в заголовок `Authorization: Bearer <token>`; защищённые роутеры подключают зависимость
`require_auth`. Логин/пароль и секрет подписи — из `config.settings` (берутся из `.env`).
"""

import base64
import hashlib
import hmac
import json
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings

_bearer = HTTPBearer(auto_error=False)


def _secret() -> bytes:
    """Ключ подписи: явный `JWT_SECRET` либо производный от пароля (работает без настройки)."""
    return (settings.jwt_secret or f"iskendy:{settings.auth_password}").encode()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def create_token(sub: str) -> str:
    """Подписать JWT (HS256) с субъектом `sub` и сроком `jwt_ttl_hours`."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": sub, "exp": int(time.time()) + settings.jwt_ttl_hours * 3600}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    sig = hmac.new(_secret(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"


def verify_token(token: str) -> dict:
    """Проверить подпись и срок JWT, вернуть payload. Бросает ValueError при невалидном токене."""
    try:
        header_seg, payload_seg, sig_seg = token.split(".")
    except ValueError as exc:
        raise ValueError("malformed token") from exc
    signing_input = f"{header_seg}.{payload_seg}"
    expected = hmac.new(_secret(), signing_input.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig_seg)):
        raise ValueError("bad signature")
    payload = json.loads(_b64url_decode(payload_seg))
    if payload.get("exp", 0) < time.time():
        raise ValueError("token expired")
    return payload


def verify_credentials(username: str, password: str) -> bool:
    """Сверить логин/пароль с настройками (константное время). Пустой пароль = вход выключен."""
    if not settings.auth_password:
        return False
    ok_user = hmac.compare_digest(username, settings.auth_username)
    ok_pass = hmac.compare_digest(password, settings.auth_password)
    return ok_user and ok_pass


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Зависимость защищённых роутеров: требует валидный Bearer-JWT, иначе 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истёкший токен",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
