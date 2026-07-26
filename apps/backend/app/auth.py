import secrets

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

    # 常量时间比较，避免逐字节短路比较泄露令牌前缀匹配长度（时序侧信道）。
    if not settings.session_token or not secrets.compare_digest(
        token.encode("utf-8"), settings.session_token.encode("utf-8")
    ):
        raise AppError(
            code="invalid_authorization",
            message="会话令牌无效",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
