import requests, time
from os import getenv
from openai import OpenAI

#
# Handle communications with LLM
#
ALLOWED_MAX_OUT_TOKENS = 4096  # max allowed tokens
DEFAULT_MAX_OUT_TOKENS = 2048  # max numbers of tokens each LLM ping can deliver
MAX_RETRY_COUNTER = 3  # how many times to retry an API call before returning error
LLM_PING_TIMEOUT = 90  # llm completion api request timeout (sec)

DEFAULT_TEMPERATURE = 0  # default temperature for LLM completion

OPENAI_CHAT_COMPLETION_ENDPOINT = "https://api.openai.com/v1/chat/completions"


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
            dict(
                integration=dict(
                    api_key=getenv("LLM_API_KEY"), model=getenv("LLM_MODEL")
                )
            )
            if model_provider is None
            else model_provider
        )

    def __do_completion_api_call(self, system_p, user_p, max_tokens, temperature):
        return requests.post(
            OPENAI_CHAT_COMPLETION_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.model_provider['integration']['api_key']}",
            },
            json={
                "model": self.model_provider["integration"]["model"],
                "messages": [
                    {"role": "system", "content": system_p},
                    {"role": "user", "content": user_p},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=LLM_PING_TIMEOUT,
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
            resp = self.__do_completion_api_call(
                system_p, user_p, max_tokens, temperature
            )

            # handle response
            if resp.status_code == 200:
                # success -> return response
                result = resp.json()
                if "choices" not in result or not result["choices"]:
                    raise Exception("502/Invalid LLM response format.")
                content = result["choices"][0]["message"].get("content")
                if content is None:
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
                raise Exception(
                    f"502/Inappropriate content ({resp.text}). Please try again."
                )
            else:
                # not sucess and also not rate limit error -> total error
                raise Exception(
                    f"502/Error while pinging the LLM - {resp.status_code}/{resp.text}"
                )
