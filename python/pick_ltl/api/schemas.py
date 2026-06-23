from __future__ import annotations

from .. import flask_compat  # noqa: F401

from typing import Any

from flask import jsonify, request


class ApiError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def require_json() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("Expected a JSON object.", status_code=400)
    return payload


def json_error(message: str, status_code: int = 400, **extra: Any):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status_code


def normalize_provider_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(payload.get("kind", "ollama")).strip() or "ollama",
        "base_url": str(payload.get("base_url", "")).strip(),
        "model": str(payload.get("model", "")).strip(),
        "api_key": str(payload.get("api_key", "")).strip(),
        "timeout_seconds": int(payload.get("timeout_seconds", 60) or 60),
    }
