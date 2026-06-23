from __future__ import annotations

from .base import ProviderConfig, ProviderError
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatibleProvider


def build_provider(config_dict: dict) -> object:
    config = ProviderConfig.from_dict(config_dict)
    if config.kind == "ollama":
        return OllamaProvider(config)
    if config.kind == "openai-compatible":
        return OpenAICompatibleProvider(config)
    raise ProviderError(f"Unknown provider kind: {config.kind}")

