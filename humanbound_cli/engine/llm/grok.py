import time
from os import getenv
import xai_sdk

ALLOWED_MAX_OUT_TOKENS = 4096
DEFAULT_MAX_OUT_TOKENS = 1024
MAX_RETRY_COUNTER = 5
LLM_PING_TIMEOUT = 30
DEFAULT_TEMPERATURE = 0


class LLMStreamer:
    def __init__(self, model_provider=None):
        model_provider = model_provider or {
            "integration": {
                "api_key": getenv("LLM_API_KEY"),
                "model": getenv("LLM_MODEL"),
            }
        }

        self.client = xai_sdk.Client(api_key=model_provider["integration"]["api_key"])
        self.model = model_provider["integration"]["model"]

    async def ping(
        self,
        system_p,
        user_p,
        max_tokens=DEFAULT_MAX_OUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    ):
        max_tokens = min(max_tokens, ALLOWED_MAX_OUT_TOKENS)
        prompt = f"{system_p}\n{user_p}"
        return await self.client.sampler.sample_async(
            prompt=prompt,
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
        self.client = xai_sdk.Client(
            api_key=self.model_provider["integration"]["api_key"]
        )

    def __do_completion_api_call(self, prompt, max_tokens, temperature):
        return self.client.sampler.sample(
            prompt=prompt,
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
        prompt = f"{system_p}\n{user_p}"
        while retry_counter <= MAX_RETRY_COUNTER:
            try:
                response = self.__do_completion_api_call(
                    prompt, max_tokens, temperature
                )
                return response.generated_text
            except xai_sdk.exceptions.RateLimitError:
                retry_counter += 1
                if retry_counter <= MAX_RETRY_COUNTER:
                    time.sleep(retry_counter)
                    continue
                raise Exception("502/Rate limit error.")
            except xai_sdk.exceptions.AuthenticationError:
                raise Exception("502/Authentication error. Please check your API key.")
            except Exception as e:
                raise Exception(f"502/Error while pinging the LLM - {str(e)}")
