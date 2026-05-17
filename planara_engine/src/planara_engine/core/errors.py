"""Domain-level exceptions.

Routers translate these to HTTP responses in api/errors.py. Code
inside the engine should raise these — never raise HTTPException
from compliance/engine/domain modules; that would couple business
logic to the transport layer.
"""

from __future__ import annotations


class PlanaraError(Exception):
    """Root of all engine-defined exceptions.

    Carries a stable ``code`` so clients can switch on it without
    parsing English message text.
    """

    code: str = "planara_error"
    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationFailed(PlanaraError):
    """Input shape is wrong (e.g. malformed snapshot)."""

    code = "validation_failed"
    http_status = 422


class AuthenticationFailed(PlanaraError):
    """Bad credentials, missing token, or invalid signature."""

    code = "authentication_failed"
    http_status = 401


class AuthorizationFailed(PlanaraError):
    """Authenticated but not allowed."""

    code = "authorization_failed"
    http_status = 403


class NotFound(PlanaraError):
    """Resource lookup failed."""

    code = "not_found"
    http_status = 404


class Conflict(PlanaraError):
    """Request collides with existing state (eg duplicate name)."""

    code = "conflict"
    http_status = 409


class RuleEvaluationError(PlanaraError):
    """An evaluator raised. Treated as a server-side bug — the rule
    schema should have caught it earlier."""

    code = "rule_evaluation_error"
    http_status = 500
