"""Проверка JWT Supabase Auth (asymmetric, JWKS). Пользователь = claim `sub`."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None


class SupabaseJWTVerifier:
    def __init__(self, supabase_url: str, audience: str = "authenticated"):
        self.issuer = supabase_url.rstrip("/") + "/auth/v1"
        self.audience = audience
        self._jwks = jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", cache_keys=True, lifespan=600)

    def verify(self, token: str) -> CurrentUser:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, signing_key.key, algorithms=["ES256", "RS256", "EdDSA"],
                audience=self.audience, issuer=self.issuer, options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWKClientError as e:
            raise HTTPException(503, "Не удалось получить ключи Supabase Auth") from e
        except jwt.PyJWTError as e:
            raise HTTPException(401, f"Недействительный токен: {e.__class__.__name__}") from e
        return CurrentUser(id=claims["sub"], email=claims.get("email"))


def optional_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser | None:
    """Вход по желанию: без токена — None, с неверным токеном — 401."""
    if creds is None:
        return None
    return request.app.state.jwt_verifier.verify(creds.credentials)


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(401, "Нужен вход (Authorization: Bearer <supabase access token>)")
    return request.app.state.jwt_verifier.verify(creds.credentials)
