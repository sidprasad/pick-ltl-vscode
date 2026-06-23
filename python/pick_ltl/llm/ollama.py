from __future__ import annotations

from typing import Any

import requests

from .base import LLMProvider, ProviderConfig, ProviderError


class OllamaProvider(LLMProvider):
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return self.config.base_url.rstrip("/") + path

    def list_models(self) -> list[str]:
        response = self.session.get(self._url("/api/tags"), timeout=self.config.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", [])
        return [item.get("name", "") for item in models if item.get("name")]

    def test_connection(self) -> dict[str, Any]:
        models = self.list_models()
        return {"ok": True, "models": models}

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        model = self.config.model or (self.list_models()[:1] or [""])[0]
        if not model:
            raise ProviderError("No Ollama model is configured and no local models were found.")

        response = self.session.post(
            self._url("/api/chat"),
            json={
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["message"]["content"]
        except Exception as exc:
            raise ProviderError("Ollama returned an unexpected response shape.") from exc
        return self.parse_json(content)

