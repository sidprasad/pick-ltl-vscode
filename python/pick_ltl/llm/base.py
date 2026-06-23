from __future__ import annotations

import abc
import json
import re
from dataclasses import dataclass
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderConfig:
    kind: str
    base_url: str
    model: str = ""
    api_key: str = ""
    timeout_seconds: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderConfig":
        return cls(
            kind=str(data.get("kind", "ollama")).strip() or "ollama",
            base_url=str(data.get("base_url", "")).strip(),
            model=str(data.get("model", "")).strip(),
            api_key=str(data.get("api_key", "")).strip(),
            timeout_seconds=int(data.get("timeout_seconds", 60) or 60),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
        }


class LLMProvider(abc.ABC):
    def __init__(self, config: ProviderConfig):
        self.config = config

    @abc.abstractmethod
    def list_models(self) -> list[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def test_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raise NotImplementedError

    def parse_json(self, raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        if text.startswith("```"):
            parts = [part for part in text.split("```") if part.strip()]
            text = parts[-1].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            text = json_match.group(0)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Model did not return valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Model returned JSON, but not a JSON object.")
        return payload
