"""End-to-end smoke test for the health endpoint.

Boots the FastAPI app via TestClient (which exercises lifespan
startup and shutdown), hits /health, and asserts the contract the
Ruby supervisor depends on.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from planara_engine import __version__
from planara_engine.api.middleware import REQUEST_ID_HEADER


def test_health_returns_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    # ISO timestamp present and parseable
    assert "T" in body["time"]


def test_request_id_is_echoed(client: TestClient) -> None:
    rid = uuid.uuid4().hex
    resp = client.get("/health", headers={REQUEST_ID_HEADER: rid})
    assert resp.status_code == 200
    assert resp.headers[REQUEST_ID_HEADER] == rid


def test_request_id_generated_when_absent(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert REQUEST_ID_HEADER in resp.headers
    assert len(resp.headers[REQUEST_ID_HEADER]) >= 16


def test_planara_error_envelope(client: TestClient) -> None:
    """A registered PlanaraError must come back as the canonical envelope.

    Registers an ad-hoc route that raises NotFound, then asserts the
    handler shape. Lives as an integration test (not unit) because
    the envelope is owned by api/errors.py + the app wiring.
    """

    from fastapi import FastAPI
    from planara_engine.api.errors import register_error_handlers
    from planara_engine.core.errors import NotFound

    probe = FastAPI()
    register_error_handlers(probe)

    @probe.get("/boom")
    async def _boom() -> None:
        raise NotFound("missing thing", details={"id": "abc"})

    with TestClient(probe) as c:
        resp = c.get("/boom")

    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "not_found",
            "message": "missing thing",
            "details": {"id": "abc"},
        }
    }
