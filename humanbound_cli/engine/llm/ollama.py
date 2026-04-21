# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Ollama LLM pinger — OpenAI-compatible client for local ollama.

Ollama exposes an OpenAI-compatible API at /v1/chat/completions.
No API key required. Full local isolation — zero external network calls.

Usage:
    provider = {"name": "ollama", "integration": {"model": "llama3.1:8b"}}
    pinger = LLMPinger(provider)
    response = pinger.ping("You are a judge.", "Evaluate this conversation.")
"""

import time
from os import getenv

ALLOWED_MAX_OUT_TOKENS = 4096
DEFAULT_MAX_OUT_TOKENS = 2048
MAX_RETRY_COUNTER = 3
LLM_PING_TIMEOUT = 120  # ollama can be slow on first load
DEFAULT_TEMPERATURE = 0
DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"


class LLMPinger:
    def __init__(self, model_provider=None):
        model_provider = model_provider or {
            "integration": {
                "model": getenv("HB_MODEL", "llama3.1:8b"),
                "endpoint": getenv("HB_ENDPOINT", DEFAULT_OLLAMA_ENDPOINT),
            }
        }
        integration = model_provider.get("integration", {})
        self.model = integration.get("model", getenv("HB_MODEL", "llama3.1:8b"))
        self.endpoint = integration.get("endpoint", getenv("HB_ENDPOINT", DEFAULT_OLLAMA_ENDPOINT))

        from openai import OpenAI
        self._client = OpenAI(
            base_url=f"{self.endpoint}/v1",
            api_key="ollama",  # ollama doesn't need a key but the SDK requires one
        )

    def ping(
        self,
        system_p,
        user_p,
        max_tokens=DEFAULT_MAX_OUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    ):
        retry_counter = 0
        max_tokens = min(max_tokens, ALLOWED_MAX_OUT_TOKENS)

        while retry_counter <= MAX_RETRY_COUNTER:
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_p},
                        {"role": "user", "content": user_p},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=LLM_PING_TIMEOUT,
                )
                content = response.choices[0].message.content
                if content is None:
                    return "[No content in LLM response]"
                return content
            except Exception as e:
                if "rate" in str(e).lower() or "429" in str(e):
                    retry_counter += 1
                    if retry_counter <= MAX_RETRY_COUNTER:
                        time.sleep(retry_counter)
                        continue
                    raise Exception("502/Rate limit error.")
                if "connection" in str(e).lower():
                    raise Exception(
                        f"Cannot connect to ollama at {self.endpoint}. "
                        f"Is ollama running? Start it with: ollama serve"
                    )
                raise Exception(f"502/Error while pinging ollama - {str(e)}")
