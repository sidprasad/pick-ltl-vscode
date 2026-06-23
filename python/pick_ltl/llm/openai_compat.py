from __future__ import annotations

from typing import Any

import requests

from .base import LLMProvider, ProviderConfig, ProviderError


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.session = requests.Session()
        if config.api_key:
            self.session.headers["Authorization"] = f"Bearer {config.api_key}"

    def _url(self, path: str) -> str:
        return self.config.base_url.rstrip("/") + path

    def list_models(self) -> list[str]:
        response = self.session.get(self._url("/models"), timeout=self.config.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        return [item.get("id", "") for item in payload.get("data", []) if item.get("id")]

    def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "models": self.list_models()}

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        model = self.config.model or (self.list_models()[:1] or [""])[0]
        if not model:
            raise ProviderError("No OpenAI-compatible model is configured and none were listed by the server.")

        response = self.session.post(
            self._url("/chat/completions"),
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderError("The OpenAI-compatible server returned an unexpected response shape.") from exc
        return self.parse_json(content)

