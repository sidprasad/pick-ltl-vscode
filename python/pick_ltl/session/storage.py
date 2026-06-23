from __future__ import annotations

from .models import SessionState


def normalize_session_payload(payload: dict) -> SessionState:
    return SessionState.from_dict(payload)

