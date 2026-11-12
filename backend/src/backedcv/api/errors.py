"""Errors as {"code", "title", "detail"} with stable codes the frontend can switch on."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.sse import ServerSentEvent

from backedcv.ingestion import IngestionError

NO_DETAIL = "No further detail is available."
MODEL_UNAVAILABLE = ("model_unavailable", "The AI model is not available right now.")
MODEL_BUSY = ("model_busy", "The AI model is busy right now.")
_REFUSED_STATUSES = frozenset({401, 403})  # a key the provider does not accept
_BUSY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})


class ApiError(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str = ""):
        super().__init__(f"{code}: {title}")
        self.status, self.code, self.title, self.detail = status, code, title, detail


def analysis_not_found() -> ApiError:
    return ApiError(404, "not_found", "This analysis does not exist or has expired.")


def _body(code: str, title: str, detail: str) -> dict:
    return {"code": code, "title": title, "detail": detail}


def error_detail(exc: Exception) -> str:
    """The exception message, cut to 200 characters."""
    return str(exc).strip()[:200] or NO_DETAIL


def model_problem(exc: BaseException) -> tuple[str, str] | None:
    """The (code, title) of a run that failed because the model provider refused the request or
    could not be reached, else None. A busy or unreachable provider is worth another try; a
    refused key or a used-up budget is not, until the operator fixes it."""
    error = _provider_error(exc)
    if error is None:
        return None
    status = getattr(error, "status_code", None)
    if status is None or status in _BUSY_STATUSES:  # no status: the connection failed
        return MODEL_BUSY
    if status in _REFUSED_STATUSES or "credit balance" in str(error).lower():
        return MODEL_UNAVAILABLE
    return None


def _provider_error(exc: BaseException | None) -> BaseException | None:
    """The Anthropic SDK error behind an exception, following its causes. It is found by its
    module name, so the SDK stays an indirect dependency."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__module__.split(".")[0] == "anthropic":
            return exc
        exc = exc.__cause__ or exc.__context__
    return None


def stream_error(code: str, title: str, exc: Exception) -> ServerSentEvent:
    """The `error` event that ends a stream which failed after it had started. A failure of the
    model provider gets its own code and no detail: the provider's message is not for users."""
    problem = model_problem(exc)
    if problem is not None:
        return ServerSentEvent(event="error", data=_body(*problem, ""))
    return ServerSentEvent(event="error", data=_body(code, title, error_detail(exc)))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.title, exc.detail), status_code=exc.status)

    @app.exception_handler(IngestionError)
    async def ingestion_error(_: Request, exc: IngestionError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.title, exc.detail), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        body = _body("invalid_request", "The request is not valid.", f"{where}: {first['msg']}")
        return JSONResponse(body, status_code=422)
