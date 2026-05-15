"""PlanaraError hierarchy: codes, status codes, details propagation."""

from __future__ import annotations

import pytest

from planara_engine.core.errors import (
    AuthenticationFailed,
    AuthorizationFailed,
    NotFound,
    PlanaraError,
    RuleEvaluationError,
    ValidationFailed,
)


@pytest.mark.parametrize(
    ("cls", "expected_code", "expected_status"),
    [
        (PlanaraError, "planara_error", 500),
        (ValidationFailed, "validation_failed", 422),
        (AuthenticationFailed, "authentication_failed", 401),
        (AuthorizationFailed, "authorization_failed", 403),
        (NotFound, "not_found", 404),
        (RuleEvaluationError, "rule_evaluation_error", 500),
    ],
)
def test_error_codes_and_status(
    cls: type[PlanaraError], expected_code: str, expected_status: int
) -> None:
    err = cls("something went wrong")
    assert err.code == expected_code
    assert err.http_status == expected_status
    assert err.message == "something went wrong"
    assert err.details == {}


def test_details_round_trip() -> None:
    err = ValidationFailed("bad input", details={"field": "plot.area_m2"})
    assert err.details == {"field": "plot.area_m2"}


def test_planara_error_is_a_real_exception() -> None:
    with pytest.raises(NotFound) as ei:
        raise NotFound("nope")
    assert str(ei.value) == "nope"
