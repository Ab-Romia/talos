import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal, TypeVar, Type

from joserfc import jwe, jwt
from joserfc.errors import JoseError, ExpiredTokenError
from pydantic import BaseModel, Field

from backend.auth.utils import errors
from config import cfg
from model.utils import UUID, DATETIME


class BaseJWTClaims(BaseModel):
    sub: UUID | None = None
    jti: UUID = Field(default_factory=uuid.uuid4)
    exp: DATETIME

    iss: str = cfg().app_host
    # aud: str | list[str] | None = None
    # iat: datetime | None = None
    # nbf: datetime | None = None


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


class OAuthHandoffClaims(BaseJWTClaims):
    sub: UUID
    typ: Literal["oauth_handoff"] = "oauth_handoff"


@lru_cache
def _key():
    from joserfc import jwk

    secret = cfg().auth.jwe_secret
    key = jwk.import_key(secret, "oct")

    return key


@lru_cache
def _registry():
    return jwe.JWERegistry()


def create_token(claims: BaseJWTClaims) -> str:
    return jwt.encode(
        cfg().auth.jwt_header,
        claims.model_dump(exclude_none=True),
        _key(),
        registry=_registry(),
    )


def create_oauth_handoff_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    return create_token(
        OAuthHandoffClaims(
            sub=user_id,
            exp=now + timedelta(minutes=5),
        )
    )


def verify_oauth_handoff_token(jwe: str) -> OAuthHandoffClaims:
    if not jwe or not jwe.strip():
        raise errors.InvalidToken()
    return verify_token(jwe, return_model=OAuthHandoffClaims)


T = TypeVar("T", bound=BaseJWTClaims)


def verify_token(token: str, sub: uuid.UUID = None, return_model: Type[T] = BaseJWTClaims) -> T:
    claims_request = jwt.JWTClaimsRegistry(
        **{"sub": {"essential": True, "value": sub.hex}} if sub else {},
        iss={"essential": True, "value": cfg().app_host},
    )

    try:
        obj = jwt.decode(
            token,
            _key(),
            registry=_registry(),
        )
        claims = obj.claims

        claims_request.validate(claims)

        return return_model.model_validate(claims)
    except ExpiredTokenError as e:
        raise errors.ExpiredToken() from e
    except (JoseError, ValueError) as e:
        raise errors.InvalidCredentials() from e
