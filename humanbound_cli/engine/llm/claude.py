# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import time
from os import getenv

import anthropic

#
# Handle communications with LLM
#
ALLOWED_MAX_OUT_TOKENS = 4096  # max allowed tokens
DEFAULT_MAX_OUT_TOKENS = 2048  # max numbers of tokens each LLM ping can deliver
MAX_RETRY_COUNTER = 3  # how many times to retry an API call before returning error
LLM_PING_TIMEOUT = 90  # llm completion api request timeout (sec)

DEFAULT_TEMPERATURE = 0  # default temperature for LLM completion


class LLMStreamer:
    def __init__(self, model_provider=None):
        model_provider = model_provider or {
            "integration": {
                "api_key": getenv("LLM_API_KEY"),
                "model": getenv("LLM_MODEL"),
            }
        }
        self.client = anthropic.Anthropic(api_key=model_provider["integration"]["api_key"])
        self.model = model_provider["integration"]["model"]

    def ping(
        self,
        system_p,
        user_p,
        max_tokens=DEFAULT_MAX_OUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    ):
        max_tokens = min(max_tokens, ALLOWED_MAX_OUT_TOKENS)
        return self.client.messages.create(
            model=self.model,
            system=system_p,
            messages=[{"role": "user", "content": user_p}],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=LLM_PING_TIMEOUT,
            stream=True,
        )


class LLMPinger:
    def __init__(self, model_provider=None):
        self.model_provider = model_provider or {
            "integration": {
                "api_key": getenv("LLM_API_KEY"),
                "model": getenv("LLM_MODEL"),
            }
        }
        self.client = anthropic.Anthropic(api_key=self.model_provider["integration"]["api_key"])

    def __do_completion_api_call(self, system_p, user_p, max_tokens, temperature):
        return self.client.messages.create(
            model=self.model_provider["integration"]["model"],
            system=system_p,
            messages=[{"role": "user", "content": user_p}],
            max_tokens=max_tokens,
            temperature=temperature,
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
                response = self.__do_completion_api_call(system_p, user_p, max_tokens, temperature)
                return response.content[0].text
            except anthropic.RateLimitError:
                retry_counter += 1
                if retry_counter <= MAX_RETRY_COUNTER:
                    time.sleep(retry_counter)
                    continue
                raise Exception("502/Rate limit error.")
            except anthropic.AuthenticationError:
                raise Exception("502/Authentication error. Please check your API key.")
            except Exception as e:
                raise Exception(f"502/Error while pinging the LLM - {str(e)}")
