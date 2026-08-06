# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""LLM pinger factory — returns the right pinger for the configured provider."""

SUPPORTED_PROVIDERS = ["openai", "claude", "gemini", "grok", "azureopenai", "ollama"]

PROVIDER_ALIASES = {"anthropic": "claude"}


def resolve_provider_name(name) -> str:
    """Normalize a user-supplied provider name to its canonical form.

    Trims whitespace, lowercases (env vars like HB_PROVIDER=Anthropic are
    common), and maps aliases to canonical names. Unknown names pass through
    unchanged so the caller can raise with the original input visible.
    """
    name = (name or "").strip().lower()
    return PROVIDER_ALIASES.get(name, name)


def get_llm_pinger(model_provider):
    """Return an LLMPinger instance for the given provider.

    Args:
        model_provider: dict with "name" and "integration" keys.
            integration must contain "api_key" and optionally "model", "endpoint".

    Returns:
        LLMPinger instance with ping(system_p, user_p, max_tokens, temperature) method.
    """
    raw = model_provider["name"] if isinstance(model_provider, dict) else model_provider.name
    name = resolve_provider_name(raw)

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
        aliases = ", ".join(f"{a} -> {c}" for a, c in PROVIDER_ALIASES.items())
        raise ValueError(
            f"Unsupported LLM provider: {raw}. "
            f"Supported: {SUPPORTED_PROVIDERS} (aliases: {aliases})"
        )

    return LLMPinger(model_provider)
