from fastapi import Request, status
from fastapi.security.utils import get_authorization_scheme_param

from .config import get_settings
from .errors import AppError


async def require_bearer_token(request: Request) -> None:
    settings = get_settings()
    authorization = request.headers.get("Authorization")
    scheme, token = get_authorization_scheme_param(authorization)
    if scheme.lower() != "bearer" or not token:
        raise AppError(
            code="missing_authorization",
            message="缺少会话令牌",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not settings.session_token or token != settings.session_token:
        raise AppError(
            code="invalid_authorization",
            message="会话令牌无效",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
