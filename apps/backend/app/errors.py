from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .models.common import ErrorDetail, ErrorResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def error_payload(
    request: Request,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=get_request_id(request),
            details=details or {},
        )
    ).model_dump()


def json_error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(request, code, message, details),
        headers={"X-Request-ID": get_request_id(request)},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return json_error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "HTTP 请求错误"
    return json_error_response(
        request=request,
        status_code=exc.status_code,
        code="http_error",
        message=detail,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return json_error_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        message="请求参数校验失败",
        details={"errors": sanitize_validation_errors(exc.errors())},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return json_error_response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="服务器内部错误",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)  # type: ignore[arg-type]


ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        clean = {
            key: error[key]
            for key in ("type", "loc", "msg")
            if key in error
        }
        if "msg" in clean:
            clean["msg"] = localize_validation_message(str(clean["msg"]), str(clean.get("type", "")))
        sanitized.append(clean)
    return sanitized


def localize_validation_message(message: str, error_type: str) -> str:
    if error_type == "missing":
        return "缺少必填字段"
    if error_type.startswith(("string_", "too_", "greater_than", "less_than")):
        return "字段取值不符合要求"
    if error_type.startswith(("int_", "float_", "bool_", "list_", "dict_", "model_")):
        return "字段类型不正确"
    if error_type.startswith(("literal_error", "enum")):
        return "字段取值不在允许范围内"
    if message and not message.isascii():
        return message
    return "请求字段无效"
