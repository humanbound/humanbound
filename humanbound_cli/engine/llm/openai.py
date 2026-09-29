# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import time
from os import getenv

import requests

#
# Handle communications with LLM
#
ALLOWED_MAX_OUT_TOKENS = 4096  # max allowed tokens
DEFAULT_MAX_OUT_TOKENS = 2048  # max numbers of tokens each LLM ping can deliver
MAX_RETRY_COUNTER = 3  # how many times to retry an API call before returning error
LLM_PING_TIMEOUT = 90  # llm completion api request timeout (sec)

DEFAULT_TEMPERATURE = 0  # default temperature for LLM completion

OPENAI_CHAT_COMPLETION_ENDPOINT = "https://api.openai.com/v1/chat/completions"


def _chat_url(endpoint):
    """Chat completions URL for an OpenAI-compatible base URL (e.g. OpenRouter).

    ``endpoint`` follows the OpenAI SDK ``base_url`` convention
    (``https://openrouter.ai/api/v1``); a URL already ending in
    ``/chat/completions`` is used as-is. No endpoint means api.openai.com.
    """
    if not endpoint:
        return OPENAI_CHAT_COMPLETION_ENDPOINT
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/chat/completions"):
        return endpoint
    return f"{endpoint}/chat/completions"


class LLMStreamer:
    def __init__(self, model_provider=None):
        model_provider = (
            dict(
                integration=dict(
                    api_key=getenv("LLM_API_KEY"),
                    model=getenv("LLM_MODEL"),
                )
            )
            if model_provider is None
            else model_provider
        )
        # Lazy import: the OpenAI SDK is the optional [engine] extra and is only
        # needed for streaming. Importing it at module top made this submodule
        # (and the requests-based LLMPinger) un-importable without the extra.
        from openai import OpenAI

        self.__openai_client = OpenAI(
            api_key=model_provider["integration"]["api_key"],
        )
        self.model = model_provider["integration"]["model"]

    def ping(
        self,
        system_p,
        user_p,
        max_tokens=DEFAULT_MAX_OUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    ):
        max_tokens = min(max_tokens, ALLOWED_MAX_OUT_TOKENS)
        return self.__openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_p},
                {"role": "user", "content": user_p},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=LLM_PING_TIMEOUT,
            stream=True,
        )


class LLMPinger:
    def __init__(self, model_provider=None):
        self.model_provider = (
            dict(integration=dict(api_key=getenv("LLM_API_KEY"), model=getenv("LLM_MODEL")))
            if model_provider is None
            else model_provider
        )
        # Reasoning models reject "max_tokens" (they want "max_completion_tokens")
        # and any temperature but the default. Each is switched on the first 400
        # that says so, then kept for later calls.
        self.token_param = "max_tokens"
        self.send_temperature = True

    def __do_completion_api_call(self, system_p, user_p, max_tokens, temperature):
        payload = {
            "model": self.model_provider["integration"]["model"],
            "messages": [
                {"role": "system", "content": system_p},
                {"role": "user", "content": user_p},
            ],
            self.token_param: max_tokens,
        }
        if self.send_temperature:
            payload["temperature"] = temperature
        return requests.post(
            _chat_url(self.model_provider["integration"].get("endpoint")),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.model_provider['integration']['api_key']}",
            },
            json=payload,
            timeout=LLM_PING_TIMEOUT,
            allow_redirects=False,
        )

    def ping(
        self,
        system_p,
        user_p,
        max_tokens=DEFAULT_MAX_OUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    ):
        do_retry_counter = 0
        max_tokens = min(max_tokens, ALLOWED_MAX_OUT_TOKENS)
        while do_retry_counter <= MAX_RETRY_COUNTER:
            # api call to serverless LLM
            try:
                resp = self.__do_completion_api_call(system_p, user_p, max_tokens, temperature)
            except requests.exceptions.RequestException as e:
                # network error / timeout -> sleep and retry, same backoff as 429/5xx
                do_retry_counter = do_retry_counter + 1
                if do_retry_counter <= MAX_RETRY_COUNTER:
                    time.sleep(do_retry_counter)
                    continue
                raise Exception(f"502/Error while pinging the LLM - request failed: {e}")

            # handle response
            if resp.status_code == 200:
                # success -> return response
                result = resp.json()
                if "choices" not in result or not result["choices"]:
                    # OpenAI-compatible gateways (e.g. OpenRouter) can return 200
                    # with an error body; surface the provider's message.
                    if result.get("error"):
                        raise Exception(f"502/LLM provider error: {result['error']}")
                    raise Exception("502/Invalid LLM response format.")
                content = result["choices"][0]["message"].get("content")
                if content is None:
                    refusal = result["choices"][0]["message"].get("refusal", "")
                    return refusal or "[No content in LLM response]"
                return content
            elif resp.status_code == 429 or resp.status_code >= 500:
                # rate limit or transient server error -> sleep and retry
                # UNLESS all the trials are consumed -> fail
                do_retry_counter = do_retry_counter + 1
                if do_retry_counter <= MAX_RETRY_COUNTER:
                    time.sleep(do_retry_counter)  # linear backoff - sleep in sec
                    continue
                # eventually retrying failed -> error
                if resp.status_code == 429:
                    raise Exception("502/Rate limit error.")
                raise Exception(f"502/Error while pinging the LLM - {resp.status_code}/{resp.text}")
            elif resp.status_code == 400:
                if (
                    self.token_param == "max_tokens"
                    and "max_tokens" in resp.text
                    and "max_completion_tokens" in resp.text
                ):
                    self.token_param = "max_completion_tokens"
                    continue
                if (
                    self.send_temperature
                    and "Unsupported value" in resp.text
                    and "temperature" in resp.text
                ):
                    self.send_temperature = False
                    continue
                raise Exception(f"502/Inappropriate content ({resp.text}). Please try again.")
            else:
                # not sucess and also not rate limit error -> total error
                raise Exception(f"502/Error while pinging the LLM - {resp.status_code}/{resp.text}")
