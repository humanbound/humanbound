# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""LLM pinger factory — returns the right pinger for the configured provider."""


SUPPORTED_PROVIDERS = ["openai", "claude", "gemini", "grok", "azureopenai", "ollama"]


def get_llm_pinger(model_provider):
    """Return an LLMPinger instance for the given provider.

    Args:
        model_provider: dict with "name" and "integration" keys.
            integration must contain "api_key" and optionally "model", "endpoint".

    Returns:
        LLMPinger instance with ping(system_p, user_p, max_tokens, temperature) method.
    """
    name = (
        model_provider["name"]
        if isinstance(model_provider, dict)
        else model_provider.name
    )

    if name == "azureopenai":
        from .azureopenai import LLMPinger
    elif name == "openai":
        from .openai import LLMPinger
    elif name == "claude":
        from .claude import LLMPinger
    elif name == "gemini":
        from .gemini import LLMPinger
    elif name == "grok":
        from .grok import LLMPinger
    elif name == "ollama":
        from .ollama import LLMPinger
    else:
        raise ValueError(f"Unsupported LLM provider: {name}. Supported: {SUPPORTED_PROVIDERS}")

    return LLMPinger(model_provider)
