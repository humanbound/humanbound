# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import requests, time
from os import getenv
from openai import AzureOpenAI

#
# Handle communications with LLM
#
# NOTE: Token parameter compatibility
# - Older models: use "max_tokens"
# - Newer models: use "max_completion_tokens"
# The code auto-detects based on model name and retries with correct parameter if needed
#
ALLOWED_MAX_OUT_TOKENS = 4096  # max allowed tokens
DEFAULT_MAX_OUT_TOKENS = 2048  # max numbers of tokens each LLM ping can deliver
MAX_RETRY_COUNTER = 3  # how many times to retry an API call before returning error
LLM_PING_TIMEOUT = 90  # llm completion api request timeout (sec)

DEFAULT_TEMPERATURE = 1  # default temperature for LLM completion


class LLMStreamer:
    def __init__(self, model_provider=None):
        model_provider = (
            dict(
                integration=dict(
                    api_key=getenv("LLM_API_KEY"),
                    api_version=getenv("LLM_API_VERSION"),
                    endpoint=getenv("LLM_ENDPOINT"),
                    model=getenv("LLM_MODEL"),
                )
            )
            if model_provider is None
            else model_provider
        )

        self.__azure_ai_client = AzureOpenAI(
            api_key=model_provider["integration"]["api_key"],
            api_version=model_provider["integration"]["api_version"],
            azure_endpoint=model_provider["integration"]["endpoint"],
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

        # Build parameters
        params = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_p},
                {"role": "user", "content": user_p},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": LLM_PING_TIMEOUT,
            "stream": True,
        }
        return self.__azure_ai_client.chat.completions.create(**params)


class LLMPinger:
    def __init__(self, model_provider=None):
        self.model_provider = (
            dict(
                integration=dict(
                    api_key=getenv("LLM_API_KEY"),
                    api_version=getenv("LLM_API_VERSION"),
                    endpoint=getenv("LLM_ENDPOINT"),
                    model=getenv("LLM_MODEL"),
                )
            )
            if model_provider is None
            else model_provider
        )
        # Auto-extract api_version from endpoint URL if not provided separately
        integration = self.model_provider.get("integration", {})
        if not integration.get("api_version") and integration.get("endpoint"):
            endpoint = integration["endpoint"]
            if "api-version=" in endpoint:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(endpoint).query)
                if "api-version" in qs:
                    integration["api_version"] = qs["api-version"][0]
        self.last_usage = None

    def ping(
        self,
        system_p,
        user_p,
        max_tokens=DEFAULT_MAX_OUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    ):
        do_retry_counter = 0
        max_tokens = min(max_tokens, ALLOWED_MAX_OUT_TOKENS)

        # Determine which token parameter to use based on model
        model_name = self.model_provider["integration"]["model"]

        # Build request payload with appropriate token parameter
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_p},
                {"role": "user", "content": user_p},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,  # default, may be overridden below
        }
        while do_retry_counter <= MAX_RETRY_COUNTER:
            # api call to serverless LLM
            headers = {
                "Content-Type": "application/json",
                "Api-Key": self.model_provider["integration"]["api_key"],
            }
            internal_secret = self.model_provider["integration"].get("internal_secret")
            if internal_secret:
                headers["x-hb-key-internal"] = internal_secret
            resp = requests.post(
                self.model_provider["integration"]["endpoint"],
                headers=headers,
                json=payload,
                timeout=LLM_PING_TIMEOUT,
            )

            # handle response
            if resp.status_code == 200:
                # success -> return response
                result = resp.json()
                if "choices" not in result or not result["choices"]:
                    raise Exception("502/Invalid LLM response format.")
                self.last_usage = result.get("usage")
                content = result["choices"][0]["message"].get("content")
                if content is None:
                    # Refusal or tool_calls-only response — no text content
                    refusal = result["choices"][0]["message"].get("refusal", "")
                    return refusal or "[No content in LLM response]"
                return content
            elif resp.status_code == 429:
                # rate limit hit -> sleep and retry
                # UNLESS all the trials are consumed -> fail
                do_retry_counter = do_retry_counter + 1
                if do_retry_counter <= MAX_RETRY_COUNTER:
                    time.sleep(do_retry_counter)  # exponential backoff - sleep in sec
                    continue
                # eventually retrying failed -> error
                raise Exception("502/Rate limit error.")
            elif resp.status_code == 400:
                error_text = resp.text
                # Check if error is about unsupported max_tokens parameter
                if "max_tokens" in error_text and "max_completion_tokens" in error_text:
                    # Retry with max_completion_tokens
                    del payload["max_tokens"]
                    payload["max_completion_tokens"] = max_tokens
                    continue

                # Other 400 errors
                raise Exception(
                    f"502/Inappropriate content ({error_text}). Please try again."
                )
            else:
                # not sucess and also not rate limit error -> total error
                raise Exception(
                    f"502/Error while pinging the LLM - {resp.status_code}/{resp.text}"
                )


class EmbeddingsExtractor:
    def __init__(self, model_provider=None):
        self.model_provider = (
            dict(
                integration=dict(
                    api_key=getenv("EMBEDDINGS_API_KEY"),
                    endpoint=getenv("EMBEDDINGS_ENDPOINT"),
                )
            )
            if model_provider is None
            else model_provider
        )

    #
    # Embeddings Extraction
    #
    def __do_embeddings_api_call(self, data):
        endpoint = self.model_provider["integration"]["endpoint"]
        api_key = self.model_provider["integration"]["api_key"]
        if not endpoint or not api_key:
            raise Exception(
                f"Embeddings not configured: endpoint={'set' if endpoint else 'MISSING'}, "
                f"api_key={'set' if api_key else 'MISSING'}"
            )
        response = requests.post(
            endpoint,
            headers={
                "Content-Type": "application/json",
                "Api-Key": api_key,
            },
            json={"input": data},
            timeout=90,  # 90 second timeout (cold start: model download + load + inference)
        )
        if response.status_code != 200:
            raise Exception(
                f"Embeddings API error {response.status_code}: {response.text[:500]}"
            )
        return response.json()["data"]

    def encode(self, data):
        embeddings, batch_size = [], 100  # for rate limit considerations
        try:
            for i in range(0, len(data), batch_size):
                batch = data[i : i + batch_size]
                batch_embeddings = self.__do_embeddings_api_call(batch)
                embeddings.extend([e["embedding"] for e in batch_embeddings])

                # Only sleep if there are more batches to process
                if i + batch_size < len(data):
                    time.sleep(1)

            return embeddings
        except Exception as e:
            raise Exception(f"Failed to generate embeddings: {str(e)}")
