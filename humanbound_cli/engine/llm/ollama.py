# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Ollama LLM pinger — talks to a local Ollama over its OpenAI-compatible API.

Ollama exposes an OpenAI-compatible endpoint at /v1/chat/completions.
No API key required. Full local isolation — zero external network calls.

This provider deliberately uses `httpx` (a core dependency) rather than the
`openai` SDK, so the air-gapped path works on a plain `pip install humanbound`
without the `[engine]` extra.

Usage:
    provider = {"name": "ollama", "integration": {"model": "llama3.1:8b"}}
    pinger = LLMPinger(provider)
    response = pinger.ping("You are a judge.", "Evaluate this conversation.")
"""

import time
from os import getenv

import httpx

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
        self._url = f"{self.endpoint.rstrip('/')}/v1/chat/completions"

    def ping(
        self,
        system_p,
        user_p,
        max_tokens=DEFAULT_MAX_OUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    ):
        retry_counter = 0
        max_tokens = min(max_tokens, ALLOWED_MAX_OUT_TOKENS)

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_p},
                {"role": "user", "content": user_p},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        while retry_counter <= MAX_RETRY_COUNTER:
            try:
                resp = httpx.post(self._url, json=body, timeout=LLM_PING_TIMEOUT)
                if resp.status_code == 429:
                    retry_counter += 1
                    if retry_counter <= MAX_RETRY_COUNTER:
                        time.sleep(retry_counter)
                        continue
                    raise Exception("502/Rate limit error.")
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"].get("content")
                if content is None:
                    return "[No content in LLM response]"
                return content
            except httpx.ConnectError:
                raise Exception(
                    f"Cannot connect to ollama at {self.endpoint}. "
                    f"Is ollama running? Start it with: ollama serve"
                )
            except httpx.HTTPStatusError as e:
                raise Exception(f"502/Error while pinging ollama - {e.response.status_code}")
            except Exception as e:
                if "rate" in str(e).lower() or "429" in str(e):
                    retry_counter += 1
                    if retry_counter <= MAX_RETRY_COUNTER:
                        time.sleep(retry_counter)
                        continue
                    raise Exception("502/Rate limit error.")
                raise Exception(f"502/Error while pinging ollama - {str(e)}")
