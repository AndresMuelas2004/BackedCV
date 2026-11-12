"""A failure of the model provider gets its own error code, and its message stays private."""

import pytest

from backedcv.api.errors import MODEL_BUSY, model_problem, stream_error


def _provider_error(status: int | None, message: str = "boom") -> Exception:
    """An exception shaped like the Anthropic SDK's: its module, and a status when it has one."""
    cls = type("APIStatusError", (Exception,), {"__module__": "anthropic"})
    error = cls(message)
    if status is not None:
        error.status_code = status
    return error


@pytest.mark.parametrize(
    ("status", "message", "code"),
    [
        (401, "invalid x-api-key", "model_unavailable"),
        (403, "forbidden", "model_unavailable"),
        (400, "Your credit balance is too low to access the Anthropic API.", "model_unavailable"),
        (429, "rate limited", "model_busy"),
        (529, "overloaded", "model_busy"),
        (None, "connection error", "model_busy"),
    ],
)
def test_a_provider_failure_gets_its_own_code(status, message, code):
    assert model_problem(_provider_error(status, message))[0] == code


def test_other_failures_keep_the_generic_error():
    assert model_problem(ValueError("not the provider")) is None
    assert model_problem(_provider_error(400, "messages: prompt is too long")) is None


def test_the_provider_error_is_found_behind_a_wrapper():
    try:
        try:
            raise _provider_error(529)
        except Exception as inner:
            raise RuntimeError("node failed") from inner
    except RuntimeError as outer:
        assert model_problem(outer) == MODEL_BUSY


def test_the_stream_error_hides_the_provider_message():
    event = stream_error(
        "analysis_failed", "The analysis could not finish.", _provider_error(401, "key sk-123")
    )

    assert event.data == {
        "code": "model_unavailable",
        "title": "The AI model is not available right now.",
        "detail": "",
    }


def test_any_other_error_keeps_its_code_and_detail():
    event = stream_error("analysis_failed", "The analysis could not finish.", ValueError("bad"))

    assert event.data == {
        "code": "analysis_failed",
        "title": "The analysis could not finish.",
        "detail": "bad",
    }
