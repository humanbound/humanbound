import copy
import requests, re, json, ssl, certifi, time, asyncio, re, traceback
from websockets.asyncio.client import connect

import logging

logger = logging.getLogger("humanbound.engine.bot")


def _log_error(title="", description=None, tag="", hook=""):
    """Log non-fatal errors."""
    logger.warning(f"[{tag}] {title}: {description}")

MIN_URL_LENGTH = 80  # truncate url after this character
REQUESTS_TIMEOUT = 500

DEFAULT_AI_RESPONSE_KEYS = ["content", "text", "response", "resp", "answer", "ans"]

ssl_context = ssl.create_default_context()
ssl_context.load_verify_locations(certifi.where())

# truncate URL details (redact any critical info) if present in the exception message
url_pattern = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+\-.]*://\S+")


def truncate(match):
    url = match.group(0)
    if len(url) > MIN_URL_LENGTH:
        return url[:MIN_URL_LENGTH] + "..."
    return url


#
# Override this method to handle non-standard bot response formats.
#
class ResponseExtractor:
    """Base class for custom response extraction.

    Override `extract_custom_response` if your bot returns responses
    in a non-standard format (not one of: content, text, response, answer).
    """

    def extract_custom_response(self, chunk):
        """Override to handle custom response formats. Return None to fall back to default extraction."""
        return None


#
# Chat Client
#
class Bot(ResponseExtractor):
    def __init__(self, bot_config, e_id):
        self.bot_config = bot_config
        self.e_id = e_id

    #
    # Utility functions
    #

    # Utility functions to handle the ai agent's response from the chunked websocket message
    # or the http api call -> extract the actual response from the chunk
    # IMPORTANT: Handle also conversational UI elements (e.g. quick replies, buttons, etc.)
    # => convert them to text that guides the conversation so as the test/atatck agent
    # can understand and use them in the next prompt (LLM response genetrator)

    # for streaming responses, identify if the chunck holds a response delta (for streaming cases)
    def __is_ai_response_chunk(self, chunk):
        if "type" not in chunk:
            return False
        if chunk["type"] != "chunk":
            return False
        if chunk not in DEFAULT_AI_RESPONSE_KEYS:
            return False
        return True

    # extract the AI agent's response from the API response
    def __extract_ai_response(self, chunk):
        if isinstance(chunk, dict):
            # Basic extraction logic -> check for the various common response formats
            for key in DEFAULT_AI_RESPONSE_KEYS:
                if key in chunk and isinstance(chunk[key], str):
                    return chunk[key]

            # Try custom extraction for non-standard formats
            custom = self.extract_custom_response(chunk)
            if custom:
                return custom

        return str(chunk)

    # extract metadata from a single turn's response (for per-turn telemetry mode)
    def __extract_turn_metadata(self, response):
        """Extract metadata from a chat response for per-turn telemetry collection"""
        try:
            telemetry_config = self.bot_config.get("telemetry", {})

            # Only extract if per-turn mode is enabled
            if telemetry_config.get("mode") != "per_turn":
                return None

            extraction_map = telemetry_config.get("extraction_map", {})
            metadata_path = extraction_map.get("metadata_path")

            if not metadata_path:
                return None

            # Navigate to metadata using dot notation path (e.g., "data.autopilotResponse.value.metadata")
            parts = metadata_path.split(".")
            current = response

            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None

            return current

        except Exception:
            return None

    #
    # Utility functions to prepare the api call data (endpoint, headers, payload)
    # Replace any placeholders with actual values on the fly from previous api calls
    # e.g. auth tokens, thread ids, etc.
    #

    # util function to process the input payload schema and replace the
    # various meta variables with the actual values (e.g. $PROMPT, $EID, $CONVERSATION, $<custom_key>)
    # returns the parsed item and a boolean indicating if the $PROMPT placeholder was found
    def __parse_payload_item(self, item, base_payload, u_prompt="", conversation=[]):
        # item: the current item to parse - can be a dict, list or string - the property value in the chat completion payload schema
        # u_prompt: the actual user prompt to replace the $PROMPT placeholder
        # conversation: the conversation history to replace the $CONVERSATION placeholder (if any)
        # base_payload: this serves as the source for any $<custom_key> replacement
        # -> gives the user the flexibility to use any value returned by the init request in the chat completion request (e.g. thread_id, access_token, etc.)
        prompt_placeholder_is_found = False
        if isinstance(item, dict):
            # nested dict -> parse recursively
            for key in item:
                item[key], prompt_placeholder_is_found_cur = self.__parse_payload_item(
                    item[key], base_payload, u_prompt, conversation
                )
                prompt_placeholder_is_found = (
                    prompt_placeholder_is_found or prompt_placeholder_is_found_cur
                )
            return item, prompt_placeholder_is_found

        if isinstance(item, list):
            # nested list -> parse recursively
            for idx in range(len(item)):
                item[idx], prompt_placeholder_is_found_cur = self.__parse_payload_item(
                    item[idx], base_payload, u_prompt, conversation
                )
                prompt_placeholder_is_found = (
                    prompt_placeholder_is_found or prompt_placeholder_is_found_cur
                )
            return item, prompt_placeholder_is_found

        if isinstance(item, str):
            # string -> check for the various placeholders
            if item.lower() == "$prompt":
                return u_prompt, True

            if item.lower() == "$humanbound_eid":
                return self.e_id, False

            if item.lower() == "$conversation":
                conversation_map_to_openai = []
                # map the intental humanbound conversation history to OpenAI specific format
                for c in [] if conversation is None else conversation:
                    if "u" in c:
                        conversation_map_to_openai.append(
                            {
                                "role": "user",
                                "content": c["u"],
                            }
                        )
                    if "a" in c:
                        conversation_map_to_openai.append(
                            {
                                "role": "assistant",
                                "content": c["a"],
                            }
                        )
                return conversation_map_to_openai, False

            if item[0] == "$":
                key = item[1:]
                return (
                    base_payload[key] if len(key) and key in base_payload else None
                ), False

            if item[0] == "\\":
                return item[1:], False

        # fallback - return the item as is (probably a string without any placeholders or other base type)
        return item, False

    # prepare the endpoint - replace any $<custom_key> placeholders with actual values from the payload
    # <custom_key> refers to any key in payload argument
    def __prepare_endpoint(self, endpoint, payload):
        for key in payload:
            if not isinstance(payload[key], list) and not isinstance(
                payload[key], dict
            ):
                endpoint = endpoint.replace(f"${key}", str(payload[key]))
        return endpoint

    # prepare the headers - handle also any $<custom_key> placeholders with actual values from the payload
    # <custom_key> refers to any key in payload argument
    # special handling for authorization header (bearer token or custom schema)
    def __prepare_headers(self, headers, payload):
        # handle authorization (if any)
        if "x-humanbound-auth-schema" in headers:
            # custom authorization schema - prioritize this over the default bearer token schema
            auth_schema = headers["x-humanbound-auth-schema"]
            if not isinstance(auth_schema, dict):
                raise Exception("400/'x-humanbound-auth-schema' is not a valid dict.")
            if (
                "key" not in auth_schema
                and "label" not in auth_schema
                and "value" not in auth_schema
            ):
                raise Exception(
                    "400/'x-humanbound-auth-schema' must contain 'key' or 'label' or 'value' property."
                )
            auth_label = (
                auth_schema["label"] if "label" in auth_schema else "authorization"
            )
            if isinstance(auth_label, str) == False:
                raise Exception(
                    "400/'x-humanbound-auth-schema::label' must be a string."
                )
            auth_key = auth_schema["key"] if "key" in auth_schema else "access_token"
            if isinstance(auth_key, str) == False:
                raise Exception("400/'x-humanbound-auth-schema::key' must be a string.")
            if auth_key not in payload:
                raise Exception(
                    f"400/'{auth_key}' is missing in the payload for authorization header."
                )
            auth_value = (
                auth_schema["value"] if "value" in auth_schema else payload[auth_key]
            )
            if isinstance(auth_value, str) == False:
                raise Exception(
                    "400/'x-humanbound-auth-schema::value' must be a string."
                )

            # all done - now we can set the complete authorization header in the customised context
            headers[auth_label] = auth_value.replace("$token", str(payload[auth_key]))

            # remove x-humanbound-auth-schema info, no need to send it to the api
            del headers["x-humanbound-auth-schema"]
        elif "access_token" in payload and isinstance(payload["access_token"], str):
            # deafault authorization schema - bearer token
            headers["authorization"] = f"Bearer {payload['access_token']}"

        # parse the rest of the headers for any $<custom_key> placeholders
        for key in headers:
            headers[key], _ = self.__parse_payload_item(headers[key], payload)

        # attach common headers
        headers["content-type"] = "application/json"
        headers["x-humanbound-test-id"] = self.e_id

        return headers

    # prepare the payload - handle also any $<custom_key> placeholders with actual values from the payload
    # <custom_key> refers to any key in payload argument
    # special handling for:
    #   $PROMPT (case insensitive) placeholder with the actual user prompt
    #     IMPORTANT: if no $PROMPT placeholder is found, the user prompt is appended to the payload as a typical OpenAI
    #     chat completion schema
    #   $CONVERSATION (case insensitive) placeholder with the conversation history (if passed as an argument, else [])
    #   $HUMANBOUND_EID (case insensitive) placeholder with the current e_id
    def __prepare_payload(self, payload, base_payload, u_prompt="", conversation=None):
        prompt_placeholder_is_found = False

        # if payload is dict
        if isinstance(payload, dict):
            for key in payload:
                payload[key], prompt_placeholder_is_found_cur = (
                    self.__parse_payload_item(
                        payload[key],
                        base_payload,
                        u_prompt,
                        conversation,
                    )
                )
                prompt_placeholder_is_found = (
                    prompt_placeholder_is_found or prompt_placeholder_is_found_cur
                )
            # not a custom content schema -> follow OpenAI specific
            # but ONLY if u_prompt is not empty
            if not prompt_placeholder_is_found and u_prompt != "":
                messages = []
                # Include prior conversation turns for stateless bots
                if conversation:
                    for c in conversation:
                        if "u" in c:
                            messages.append({"role": "user", "content": c["u"]})
                        if "a" in c:
                            messages.append({"role": "assistant", "content": c["a"]})
                messages.append({"role": "user", "content": u_prompt})
                payload["messages"] = messages

        # if payload is list
        if isinstance(payload, list):
            for idx in range(len(payload)):
                payload[idx], prompt_placeholder_is_found_cur = (
                    self.__parse_payload_item(
                        payload[idx],
                        base_payload,
                        u_prompt,
                        conversation,
                    )
                )
                prompt_placeholder_is_found = (
                    prompt_placeholder_is_found or prompt_placeholder_is_found_cur
                )
            # $prompt not detected -> for list type paylod $prompt is mandatory => FAIL
            # but ONLY if u_prompt is not empty
            if not prompt_placeholder_is_found and u_prompt != "":
                raise Exception(f"400/'$prompt' is missing from the payload array.")

        # if payload is a string, replace directly the $prompt placeholder
        # NO OTHER PLACEHOLDERS SUPPORTED IN THIS CASE
        if isinstance(payload, str):
            payload = payload.replace("$prompt", u_prompt)

        return payload

    # make an api call - generic function to be used for both init and chat completion requests
    # IMPORTANT:
    #   1. Handles both POST and GET methods (tries POST first, then GET if 405)
    #   2. Handles placeholder replacement in endpoint, headers and payload
    def __make_api_call(
        self, base_payload, endpoint, headers, payload1, u_prompt="", conversation=None
    ):
        endpoint = self.__prepare_endpoint(endpoint, base_payload)
        headers = self.__prepare_headers(headers, base_payload)
        payload = self.__prepare_payload(payload1, base_payload, u_prompt, conversation)
        t_start = time.time()

        resp = requests.post(
            endpoint, headers=headers, json=payload, timeout=REQUESTS_TIMEOUT
        )
        if resp.status_code == 405:
            t_start = time.time()
            resp = requests.get(
                endpoint, headers=headers, params=payload, timeout=REQUESTS_TIMEOUT
            )
        if resp.status_code != 200 and resp.status_code != 201:
            raise Exception(
                f"{resp.status_code}/{resp.text} - {url_pattern.sub(truncate, endpoint)}"
            )

        # All ok -> return the response
        try:
            # by default assume json response
            return resp.json(), time.time() - t_start, endpoint
        except:
            return resp.text, time.time() - t_start, endpoint

    #
    # Handle chat completion requests (streaming and non-streaming)
    #
    def __chat(self, base_payload, u_prompt, conversation):
        try:
            # a. ping
            messages, exec_t, _ = self.__make_api_call(
                base_payload,
                self.bot_config["chat_completion"]["endpoint"],
                copy.deepcopy(self.bot_config["chat_completion"]["headers"]),
                copy.deepcopy(self.bot_config["chat_completion"]["payload"]),
                u_prompt,
                conversation,
            )
            # b. extract ai agent response
            # (might be in different formats, will handle accordingly in the next step)
            last_msg = (
                (
                    messages
                    if isinstance(messages, dict)
                    else messages[len(messages) - 1]
                )
                if not isinstance(messages, str)
                else messages
            )

            # c. extract turn metadata if per-turn telemetry mode is enabled
            turn_metadata = self.__extract_turn_metadata(last_msg)

            return (
                self.__extract_ai_response(last_msg),
                exec_t,
                turn_metadata,
            )

        except (requests.exceptions.Timeout, asyncio.TimeoutError):
            raise Exception(
                f"408/Testing AI Agent error - Cannot generate completion, timeout at {REQUESTS_TIMEOUT} sec."
            )
        except (AttributeError, ValueError) as e:
            _log_error(
                title=e.__class__.__name__,
                description={
                    "where": "ClientBot :: Chat",
                    "e": url_pattern.sub(truncate, str(e)),
                    "trace": str(traceback.format_exc()),
                },
                tag="Exception",
                hook="ENGINEERING",
            )
            raise Exception(
                f"500/Testing AI Agent error [internal] - Cannot generate completion."
            )
        except Exception as e:
            raise Exception(
                f"502/Testing AI Agent error - Cannot generate completion. - {url_pattern.sub(truncate, str(e))}."
            )

    # streaming case
    async def __listen(self, socket):
        # Listens for a message and returns the buffer (complete message) once done
        # handle timeout
        async def read_complete_message():
            buffer, t_start = "", time.time()
            while True:
                raw_data = await socket.recv()

                # if chunk NOT in the expected json format break - message is completed
                try:
                    chunk = json.loads(raw_data)
                except:
                    break

                if not isinstance(chunk, dict) or "type" not in chunk:
                    continue

                if chunk["type"] == "end":
                    break

                if not self.__is_ai_response_chunk(chunk):
                    continue

                # all ok - append content data (ai agent resonse stream - deltas)
                buffer += self.__extract_ai_response(chunk)

            return buffer, time.time() - t_start

        try:
            return await asyncio.wait_for(read_complete_message(), REQUESTS_TIMEOUT)
        except:
            await asyncio.wait_for(socket.close(), REQUESTS_TIMEOUT)
            raise

    async def __stream(self, base_payload, u_prompt, conversation=None):
        try:
            endpoint = self.__prepare_endpoint(
                self.bot_config["chat_completion"]["endpoint"], base_payload
            )
            headers = self.__prepare_headers(
                copy.deepcopy(self.bot_config["chat_completion"]["headers"]),
                base_payload,
            )
            payload = self.__prepare_payload(
                copy.deepcopy(self.bot_config["chat_completion"]["payload"]),
                base_payload,
                u_prompt,
                conversation,
            )

            async with connect(
                endpoint,
                open_timeout=REQUESTS_TIMEOUT,
                ping_timeout=REQUESTS_TIMEOUT,
                close_timeout=REQUESTS_TIMEOUT,
                ssl=ssl_context,
                additional_headers=headers,
            ) as websocket:
                await websocket.send(json.dumps(payload, ensure_ascii=False))
                message, exec_t = await self.__listen(websocket)

            # NOTE: Streaming mode doesn't support per-turn metadata extraction
            # since chunks are processed incrementally and final response object isn't available
            return message, exec_t, None

        except (asyncio.TimeoutError, TimeoutError) as e:
            raise Exception(
                f"408/Testing AI Agent Error – Unable to stream completion. The request timed out after {REQUESTS_TIMEOUT} seconds."
            )
        except (AttributeError, ValueError) as e:
            _log_error(
                title=e.__class__.__name__,
                description={
                    "where": "ClientBot :: Chat",
                    "e": str(e),
                    "trace": str(traceback.format_exc()),
                },
                tag="Exception",
                hook="ENGINEERING",
            )

            raise Exception(
                f"500/Testing AI Agent error [internal] - Cannot generate completion."
            )
        except Exception as e:
            raise Exception(
                f"502/Testing AI Agent error - Cannot stream completion. - {url_pattern.sub(truncate, str(e))}."
            )

    #
    # Public interface for thread initialization and chat completion
    #

    # STEP 1: Session start
    # - execute any required auth calls to get access tokens (will be used in init call and chat completion calls if needed)
    # - start the thread/session with the bot
    def init(self):
        try:
            # 1.1 - execute any required auth calls to get access tokens (if related endpoint is defined)
            endpoint = self.bot_config["thread_auth"]["endpoint"]
            if endpoint != "":
                base_payload, _, endpoint = self.__make_api_call(
                    {},
                    endpoint,
                    copy.deepcopy(self.bot_config["thread_auth"]["headers"]),
                    copy.deepcopy(self.bot_config["thread_auth"]["payload"]),
                )
                time.sleep(1)  # small delay to avoid race conditions
            else:
                base_payload = {}

            # 2.2 - start the thread/session with the bot
            temp_payload, _, endpoint = self.__make_api_call(
                base_payload,
                self.bot_config["thread_init"]["endpoint"],
                copy.deepcopy(self.bot_config["thread_init"]["headers"]),
                copy.deepcopy(self.bot_config["thread_init"]["payload"]),
            )

            # append the session start payload to the base payload
            return {**base_payload, **temp_payload}
        except requests.exceptions.Timeout:
            raise Exception(
                f"408/Testing AI Agent error - Cannot create thread, timeout at {REQUESTS_TIMEOUT} sec."
            )
        except Exception as e:
            raise Exception(
                f"502/Testing AI Agent error - Cannot create thread - {url_pattern.sub(truncate, str(e))}."
            )

    # STEP 2: Chat completion
    # send the user prompt to the bot and get the response (streaming or non-streaming)
    # Conduct the converation
    async def ping(self, base_payload, u_prompt, conversation=None):
        a_resp = (
            await self.__stream(base_payload, u_prompt, conversation)
            if self.bot_config["streaming"]
            else self.__chat(base_payload, u_prompt, conversation)
        )
        return a_resp


#
# Telemetry Client (fetch observability data after conversation)
#
class Telemetry:
    def __init__(self, telemetry_config, e_id):
        self.config = telemetry_config
        self.e_id = e_id

    #
    # Utility functions (reuse from Bot class pattern)
    #

    def __prepare_endpoint(self, endpoint, payload):
        """Replace $<key> placeholders in endpoint with values from payload"""
        for key in payload:
            if not isinstance(payload[key], list) and not isinstance(
                payload[key], dict
            ):
                endpoint = endpoint.replace(f"${key}", str(payload[key]))
        return endpoint

    def __prepare_headers(self, headers, payload):
        """Prepare headers with authorization and meta-variable replacement"""
        # Handle authorization schema (same as Bot class)
        if "x-humanbound-auth-schema" in headers:
            auth_schema = headers["x-humanbound-auth-schema"]
            if not isinstance(auth_schema, dict):
                raise Exception("400/'x-humanbound-auth-schema' is not a valid dict.")
            if (
                "key" not in auth_schema
                and "label" not in auth_schema
                and "value" not in auth_schema
            ):
                raise Exception(
                    "400/'x-humanbound-auth-schema' must contain 'key' or 'label' or 'value' property."
                )
            auth_label = (
                auth_schema["label"] if "label" in auth_schema else "authorization"
            )
            auth_key = auth_schema["key"] if "key" in auth_schema else "access_token"
            if auth_key not in payload:
                raise Exception(
                    f"400/'{auth_key}' is missing in the payload for authorization header."
                )
            auth_value = (
                auth_schema["value"] if "value" in auth_schema else payload[auth_key]
            )
            headers[auth_label] = auth_value.replace("$token", str(payload[auth_key]))
            del headers["x-humanbound-auth-schema"]
        elif "access_token" in payload and isinstance(payload["access_token"], str):
            headers["authorization"] = f"Bearer {payload['access_token']}"

        # Replace other meta-variables in headers
        for key in headers:
            if isinstance(headers[key], str):
                for payload_key in payload:
                    if not isinstance(payload[payload_key], (list, dict)):
                        headers[key] = headers[key].replace(
                            f"${payload_key}", str(payload[payload_key])
                        )

        headers["content-type"] = "application/json"
        headers["x-humanbound-test-id"] = self.e_id

        return headers

    def __prepare_payload(self, payload, base_payload):
        """Replace meta-variables in payload"""
        if isinstance(payload, dict):
            for key in payload:
                if isinstance(payload[key], str):
                    for base_key in base_payload:
                        if not isinstance(base_payload[base_key], (list, dict)):
                            payload[key] = payload[key].replace(
                                f"${base_key}", str(base_payload[base_key])
                            )
        return payload

    def __make_api_call(self, base_payload, endpoint, headers, payload):
        """Generic API call for telemetry fetch"""
        endpoint = self.__prepare_endpoint(endpoint, base_payload)
        headers = self.__prepare_headers(headers, base_payload)
        payload = self.__prepare_payload(payload, base_payload)

        method = self.config.get("method", "GET").upper()

        if method == "POST":
            resp = requests.post(
                endpoint, headers=headers, json=payload, timeout=REQUESTS_TIMEOUT
            )
        else:  # GET
            resp = requests.get(
                endpoint, headers=headers, params=payload, timeout=REQUESTS_TIMEOUT
            )

        if resp.status_code != 200 and resp.status_code != 201:
            raise Exception(
                f"{resp.status_code}/{resp.text} - {url_pattern.sub(truncate, endpoint)}"
            )

        try:
            return resp.json()
        except:
            return resp.text

    #
    # Standardization parsers
    #

    def __parse_openai_assistants(self, raw_data):
        """Parse OpenAI Assistants API format"""
        try:
            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            # Extract tool calls from run_steps
            if "run_steps" in raw_data:
                for step in raw_data["run_steps"]:
                    if step.get("type") == "tool_calls" and "step_details" in step:
                        tool_calls = step["step_details"].get("tool_calls", [])
                        for tool_call in tool_calls:
                            if tool_call.get("type") == "function":
                                func = tool_call.get("function", {})
                                standardized["tool_executions"].append(
                                    {
                                        "turn": step.get("step_number", 0),
                                        "tool_name": func.get("name", ""),
                                        "parameters": (
                                            json.loads(func.get("arguments", "{}"))
                                            if isinstance(func.get("arguments"), str)
                                            else func.get("arguments", {})
                                        ),
                                        "result": func.get("output", ""),
                                    }
                                )

            # Extract resource usage
            if "usage" in raw_data:
                standardized["resource_usage"] = {
                    "tokens_used": raw_data["usage"].get("total_tokens", 0),
                    "api_calls_count": len(raw_data.get("run_steps", [])),
                }

            return standardized
        except Exception as e:
            raise Exception(f"500/Telemetry parsing error (OpenAI format): {str(e)}")

    def __parse_langsmith(self, raw_data):
        """Parse LangSmith traces format"""
        try:
            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            # Extract tool runs
            if "runs" in raw_data:
                total_tokens = 0
                for run in raw_data["runs"]:
                    if run.get("run_type") == "tool":
                        standardized["tool_executions"].append(
                            {
                                "turn": run.get("turn", 0),
                                "tool_name": run.get("name", ""),
                                "parameters": run.get("inputs", {}).get(
                                    "tool_input", {}
                                ),
                                "result": run.get("outputs", {}).get("result", ""),
                                "execution_time_ms": run.get("execution_time", 0),
                            }
                        )
                    if "usage" in run:
                        total_tokens += run["usage"].get("total_tokens", 0)

                if total_tokens > 0:
                    standardized["resource_usage"]["tokens_used"] = total_tokens

            return standardized
        except Exception as e:
            raise Exception(f"500/Telemetry parsing error (LangSmith format): {str(e)}")

    def __parse_langfuse(self, raw_data):
        """Parse LangFuse traces format.

        Handles two response shapes:
        - Session endpoint: {"traces": [...]} — fetch observations per trace
        - Trace endpoint: {"observations": [...]} — direct observations
        """
        try:
            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            # Session endpoint returns traces[] — need to fetch observations per trace
            observations = raw_data.get("observations", [])
            if not observations and raw_data.get("traces"):
                # Sort traces by timestamp to derive turn order
                sorted_traces = sorted(
                    raw_data["traces"],
                    key=lambda t: t.get("timestamp", ""),
                )
                for turn_idx, trace in enumerate(sorted_traces, 1):
                    trace_id = trace.get("id", "")
                    if not trace_id:
                        continue
                    try:
                        trace_detail = self.__make_api_call(
                            {},
                            self.config["endpoint"].split("/sessions/")[0] + f"/traces/{trace_id}",
                            self.config["headers"].copy(),
                            {},
                        )
                        # Tag each observation with its turn number
                        for obs in trace_detail.get("observations", []):
                            obs["_turn"] = turn_idx
                        observations.extend(trace_detail.get("observations", []))
                    except Exception:
                        continue
            total_tokens = 0
            total_cost = 0

            for obs in observations:
                obs_type = obs.get("type", "")
                obs_turn = obs.get("_turn", 0)  # Turn number from trace order

                # Extract tool executions from GENERATION observations
                if obs_type == "GENERATION":
                    # Check for tool/function calls in metadata
                    metadata = obs.get("metadata", {})

                    # LangFuse can store tool calls in various ways
                    tool_calls = (
                        metadata.get("toolCalls", [])
                        or metadata.get("tool_calls", [])
                        or obs.get("toolCalls", [])
                        or []
                    )

                    for tool_call in tool_calls:
                        standardized["tool_executions"].append(
                            {
                                "turn": obs_turn,
                                "tool_name": tool_call.get(
                                    "name",
                                    tool_call.get("function", {}).get("name", ""),
                                ),
                                "parameters": (
                                    tool_call.get("arguments", {})
                                    if isinstance(tool_call.get("arguments"), dict)
                                    else tool_call.get("input", {})
                                ),
                                "result": tool_call.get(
                                    "output", tool_call.get("result", "")
                                ),
                            }
                        )

                    # Accumulate token usage
                    usage = obs.get("usage", {})
                    if usage:
                        total_tokens += usage.get("totalTokens", 0) or usage.get(
                            "total", 0
                        )
                        total_cost += usage.get("totalCost", 0) or 0

                # Extract tool executions from TOOL observations (LangGraph via LangFuse)
                elif obs_type == "TOOL":
                    standardized["tool_executions"].append(
                        {
                            "turn": obs_turn,
                            "tool_name": obs.get("name", ""),
                            "parameters": obs.get("input", {}),
                            "result": str(obs.get("output", ""))[:500],
                        }
                    )

                # Extract memory operations from SPAN observations
                elif obs_type == "SPAN":
                    span_name = obs.get("name", "")

                    # Identify memory-related spans
                    if any(
                        keyword in span_name.lower()
                        for keyword in ["memory", "store", "retrieve", "save", "load"]
                    ):
                        standardized["memory_operations"].append(
                            {
                                "turn": obs_turn,
                                "operation_type": span_name,
                                "content": str(obs.get("input", obs.get("output", ""))),
                            }
                        )

                # Extract external API calls from EVENT observations
                elif obs_type == "EVENT":
                    event_name = obs.get("name", "")
                    metadata = obs.get("metadata", {})

                    if (
                        "api_call" in event_name.lower()
                        or "external" in event_name.lower()
                    ):
                        standardized["external_calls"].append(
                            {
                                "turn": obs_turn,
                                "url": metadata.get("url", ""),
                                "method": metadata.get("method", ""),
                                "status": metadata.get("status", ""),
                            }
                        )

            # Set accumulated resource usage
            if total_tokens > 0:
                standardized["resource_usage"]["tokens_used"] = total_tokens
            if total_cost > 0:
                standardized["resource_usage"]["total_cost_usd"] = total_cost

            standardized["resource_usage"]["api_calls_count"] = len(
                [obs for obs in observations if obs.get("type") == "GENERATION"]
            )

            # Extract trace-level metadata
            trace_metadata = raw_data.get("metadata", {})
            if trace_metadata.get("user_id"):
                standardized["authorization_events"].append(
                    {
                        "user_id": trace_metadata["user_id"],
                        "session_id": raw_data.get("sessionId", ""),
                    }
                )

            return standardized
        except Exception as e:
            raise Exception(f"500/Telemetry parsing error (LangFuse format): {str(e)}")

    def __parse_wandb(self, raw_data):
        """Parse Weights & Biases (W&B) format"""
        try:
            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            # W&B structure: run with history (logged data) and summary (aggregated metrics)
            history = raw_data.get("history", [])
            summary = raw_data.get("summary", {})
            config = raw_data.get("config", {})

            total_tokens = 0
            total_cost = 0

            # Extract tool executions from logged history
            # W&B typically logs custom data under specific keys
            for idx, entry in enumerate(history):
                # Check for tool call logs (common W&B patterns)
                if "tool_calls" in entry:
                    tool_calls = entry["tool_calls"]
                    if isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            standardized["tool_executions"].append(
                                {
                                    "turn": idx + 1,
                                    "tool_name": tool_call.get(
                                        "name", tool_call.get("function", "")
                                    ),
                                    "parameters": tool_call.get(
                                        "parameters", tool_call.get("arguments", {})
                                    ),
                                    "result": tool_call.get(
                                        "result", tool_call.get("output", "")
                                    ),
                                }
                            )

                # Check for agent actions (custom logged field)
                if "agent_action" in entry:
                    action = entry["agent_action"]
                    if isinstance(action, dict):
                        standardized["tool_executions"].append(
                            {
                                "turn": idx + 1,
                                "tool_name": action.get(
                                    "tool", action.get("action", "")
                                ),
                                "parameters": action.get("input", {}),
                                "result": action.get("output", ""),
                            }
                        )

                # Extract memory operations
                if "memory_operation" in entry:
                    mem_op = entry["memory_operation"]
                    if isinstance(mem_op, dict):
                        standardized["memory_operations"].append(
                            {
                                "turn": idx + 1,
                                "operation_type": mem_op.get(
                                    "type", mem_op.get("operation", "")
                                ),
                                "content": str(
                                    mem_op.get("content", mem_op.get("data", ""))
                                ),
                            }
                        )

                # Accumulate token usage
                if "tokens" in entry:
                    total_tokens += entry.get("tokens", 0)
                if "cost" in entry:
                    total_cost += entry.get("cost", 0)

            # Extract from summary (aggregated metrics)
            if "total_tokens" in summary:
                total_tokens = summary["total_tokens"]
            if "total_cost" in summary:
                total_cost = summary["total_cost"]
            if "api_calls" in summary:
                standardized["resource_usage"]["api_calls_count"] = summary["api_calls"]

            # Set resource usage
            if total_tokens > 0:
                standardized["resource_usage"]["tokens_used"] = total_tokens
            if total_cost > 0:
                standardized["resource_usage"]["total_cost_usd"] = total_cost

            # Extract system metrics if available
            if "gpu_utilization" in summary:
                standardized["resource_usage"]["gpu_utilization_percent"] = summary[
                    "gpu_utilization"
                ]
            if "memory_mb" in summary:
                standardized["resource_usage"]["memory_mb"] = summary["memory_mb"]

            return standardized
        except Exception as e:
            raise Exception(f"500/Telemetry parsing error (W&B format): {str(e)}")

    def __parse_helicone(self, raw_data):
        """Parse Helicone format"""
        try:
            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            # Helicone structure: request/response pairs with metadata
            request_data = raw_data.get("request", {})
            response_data = raw_data.get("response", {})
            properties = raw_data.get("properties", {})
            scores = raw_data.get("scores", {})

            # Extract tool calls from response
            # Helicone captures the full LLM response including tool calls
            response_body = response_data.get("body", {})

            # OpenAI-style tool calls
            if "choices" in response_body:
                for choice in response_body["choices"]:
                    message = choice.get("message", {})
                    tool_calls = message.get("tool_calls", [])

                    for tool_call in tool_calls:
                        function = tool_call.get("function", {})
                        standardized["tool_executions"].append(
                            {
                                "turn": 1,  # Helicone tracks single requests
                                "tool_name": function.get("name", ""),
                                "parameters": (
                                    json.loads(function.get("arguments", "{}"))
                                    if isinstance(function.get("arguments"), str)
                                    else function.get("arguments", {})
                                ),
                                "result": "",  # Result typically in next request
                            }
                        )

            # Extract from function_call (legacy OpenAI format)
            if "choices" in response_body:
                for choice in response_body["choices"]:
                    message = choice.get("message", {})
                    function_call = message.get("function_call", {})

                    if function_call:
                        standardized["tool_executions"].append(
                            {
                                "turn": 1,
                                "tool_name": function_call.get("name", ""),
                                "parameters": (
                                    json.loads(function_call.get("arguments", "{}"))
                                    if isinstance(function_call.get("arguments"), str)
                                    else function_call.get("arguments", {})
                                ),
                                "result": "",
                            }
                        )

            # Extract resource usage
            usage = response_body.get("usage", {})
            if usage:
                standardized["resource_usage"]["tokens_used"] = usage.get(
                    "total_tokens", 0
                )
                standardized["resource_usage"]["prompt_tokens"] = usage.get(
                    "prompt_tokens", 0
                )
                standardized["resource_usage"]["completion_tokens"] = usage.get(
                    "completion_tokens", 0
                )

            # Extract cost and latency from Helicone metadata
            if "cost" in raw_data:
                standardized["resource_usage"]["total_cost_usd"] = raw_data["cost"]
            if "latency" in raw_data:
                standardized["resource_usage"]["latency_ms"] = raw_data["latency"]

            # Extract custom properties
            if properties:
                # Check for custom tool execution tracking
                if "tool_executions" in properties:
                    for tool_exec in properties["tool_executions"]:
                        standardized["tool_executions"].append(
                            {
                                "turn": tool_exec.get("turn", 1),
                                "tool_name": tool_exec.get("name", ""),
                                "parameters": tool_exec.get("parameters", {}),
                                "result": tool_exec.get("result", ""),
                            }
                        )

            # Extract user/session info
            if "user" in properties:
                standardized["authorization_events"].append(
                    {
                        "user_id": properties["user"],
                        "request_id": raw_data.get("id", ""),
                    }
                )

            return standardized
        except Exception as e:
            raise Exception(f"500/Telemetry parsing error (Helicone format): {str(e)}")

    def __parse_agentops(self, raw_data):
        """Parse AgentOps format"""
        try:
            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            # AgentOps structure: session -> events[] -> actions/tools
            session = raw_data.get("session", {})
            events = raw_data.get("events", [])
            agents = raw_data.get("agents", [])
            metrics = raw_data.get("metrics", {})

            total_tokens = 0
            total_cost = 0

            for event in events:
                event_type = event.get("event_type", event.get("type", ""))
                event_data = event.get("data", event)
                turn = event.get("step", event.get("turn", 1))

                # Extract tool executions
                if event_type in ["tool_call", "action", "tool_execution"]:
                    standardized["tool_executions"].append(
                        {
                            "turn": turn,
                            "tool_name": event_data.get(
                                "tool_name", event_data.get("action", "")
                            ),
                            "parameters": event_data.get(
                                "parameters", event_data.get("input", {})
                            ),
                            "result": event_data.get(
                                "result", event_data.get("output", "")
                            ),
                        }
                    )

                # Extract LLM calls (may contain tool calls)
                elif event_type in ["llm_call", "completion"]:
                    tool_calls = event_data.get("tool_calls", [])
                    for tool_call in tool_calls:
                        standardized["tool_executions"].append(
                            {
                                "turn": turn,
                                "tool_name": tool_call.get(
                                    "name",
                                    tool_call.get("function", {}).get("name", ""),
                                ),
                                "parameters": tool_call.get(
                                    "arguments", tool_call.get("parameters", {})
                                ),
                                "result": tool_call.get("result", ""),
                            }
                        )

                    # Accumulate tokens from LLM calls
                    usage = event_data.get("usage", {})
                    if usage:
                        total_tokens += usage.get("total_tokens", 0)
                        total_cost += usage.get("cost", 0)

                # Extract memory operations
                elif event_type in ["memory_save", "memory_load", "memory_update"]:
                    standardized["memory_operations"].append(
                        {
                            "turn": turn,
                            "operation_type": event_type,
                            "content": str(
                                event_data.get("content", event_data.get("data", ""))
                            ),
                        }
                    )

                # Extract external API calls
                elif event_type in ["api_call", "external_call"]:
                    standardized["external_calls"].append(
                        {
                            "turn": turn,
                            "url": event_data.get("url", ""),
                            "method": event_data.get("method", ""),
                            "status": event_data.get(
                                "status_code", event_data.get("status", "")
                            ),
                        }
                    )

                # Extract agent delegation events
                elif event_type in ["agent_handoff", "agent_delegation"]:
                    standardized["agent_delegation"].append(
                        {
                            "turn": turn,
                            "from_agent": event_data.get(
                                "from_agent", event_data.get("source", "")
                            ),
                            "to_agent": event_data.get(
                                "to_agent", event_data.get("target", "")
                            ),
                            "reason": event_data.get("reason", ""),
                        }
                    )

            # Extract from metrics (aggregated)
            if metrics:
                if "total_tokens" in metrics:
                    total_tokens = metrics["total_tokens"]
                if "total_cost" in metrics:
                    total_cost = metrics["total_cost"]
                if "api_calls" in metrics:
                    standardized["resource_usage"]["api_calls_count"] = metrics[
                        "api_calls"
                    ]
                if "latency_ms" in metrics:
                    standardized["resource_usage"]["latency_ms"] = metrics["latency_ms"]

            # Set resource usage
            if total_tokens > 0:
                standardized["resource_usage"]["tokens_used"] = total_tokens
            if total_cost > 0:
                standardized["resource_usage"]["total_cost_usd"] = total_cost

            # Extract session/user info
            if session:
                if "user_id" in session or "session_id" in session:
                    standardized["authorization_events"].append(
                        {
                            "user_id": session.get("user_id", ""),
                            "session_id": session.get(
                                "session_id", session.get("id", "")
                            ),
                            "agent_id": session.get("agent_id", ""),
                        }
                    )

            # Track multi-agent information
            if agents:
                for agent in agents:
                    if agent.get("role") or agent.get("name"):
                        # Store agent metadata if needed for multi-agent analysis
                        pass

            return standardized
        except Exception as e:
            raise Exception(f"500/Telemetry parsing error (AgentOps format): {str(e)}")

    def __parse_custom(self, raw_data, extraction_map):
        """Parse custom format using JSONPath-like extraction map"""
        try:
            from jsonpath_ng.ext import parse

            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            # Extract tool executions
            if "tool_executions" in extraction_map:
                path_expr = parse(extraction_map["tool_executions"])
                matches = path_expr.find(raw_data)

                for match in matches:
                    tool_exec = {}
                    item = match.value

                    # Map fields
                    if "tool_executions.tool_name" in extraction_map:
                        field = extraction_map["tool_executions.tool_name"]
                        tool_exec["tool_name"] = item.get(field, "")

                    if "tool_executions.parameters" in extraction_map:
                        field = extraction_map["tool_executions.parameters"]
                        tool_exec["parameters"] = item.get(field, {})

                    if "tool_executions.result" in extraction_map:
                        field = extraction_map["tool_executions.result"]
                        tool_exec["result"] = item.get(field, "")

                    if "tool_executions.turn" in extraction_map:
                        field = extraction_map["tool_executions.turn"]
                        tool_exec["turn"] = item.get(field, 0)

                    standardized["tool_executions"].append(tool_exec)

            # Extract memory operations (similar pattern)
            if "memory_operations" in extraction_map:
                path_expr = parse(extraction_map["memory_operations"])
                matches = path_expr.find(raw_data)

                for match in matches:
                    mem_op = {}
                    item = match.value

                    if "memory_operations.operation_type" in extraction_map:
                        field = extraction_map["memory_operations.operation_type"]
                        mem_op["operation_type"] = item.get(field, "")

                    if "memory_operations.content" in extraction_map:
                        field = extraction_map["memory_operations.content"]
                        mem_op["content"] = item.get(field, "")

                    if "memory_operations.turn" in extraction_map:
                        field = extraction_map["memory_operations.turn"]
                        mem_op["turn"] = item.get(field, 0)

                    standardized["memory_operations"].append(mem_op)

            return standardized
        except ImportError:
            raise Exception(
                "500/Custom telemetry parsing requires 'jsonpath-ng' package"
            )
        except Exception as e:
            raise Exception(f"500/Telemetry parsing error (custom format): {str(e)}")

    def __standardize(self, raw_data):
        """Convert vendor format to standardized schema"""
        format_type = self.config.get("format", "openai_assistants")

        if format_type == "openai_assistants":
            return self.__parse_openai_assistants(raw_data)
        elif format_type == "langsmith":
            return self.__parse_langsmith(raw_data)
        elif format_type == "langfuse":
            return self.__parse_langfuse(raw_data)
        elif format_type == "wandb" or format_type == "weights_and_biases":
            return self.__parse_wandb(raw_data)
        elif format_type == "helicone":
            return self.__parse_helicone(raw_data)
        elif format_type == "agentops":
            return self.__parse_agentops(raw_data)
        elif format_type == "custom":
            extraction_map = self.config.get("extraction_map")
            if not extraction_map:
                raise Exception(
                    "400/Custom telemetry format requires 'extraction_map' in config"
                )
            return self.__parse_custom(raw_data, extraction_map)
        else:
            raise Exception(f"400/Unsupported telemetry format: {format_type}")

    #
    # Public interface
    #

    def auth(self):
        """Optional: Get telemetry-specific access token"""
        try:
            endpoint = self.config.get("telemetry_auth", {}).get("endpoint", "")
            if endpoint == "":
                return {}

            auth_data = self.__make_api_call(
                {},
                endpoint,
                self.config["telemetry_auth"]["headers"].copy(),
                self.config["telemetry_auth"]["payload"].copy(),
            )
            return auth_data
        except Exception as e:
            raise Exception(f"502/Telemetry auth error - {str(e)}")

    def _has_telemetry_data(self, raw_data):
        """Check if the fetched telemetry response contains actual data.
        Vendors return different shapes — check common patterns."""
        if not raw_data or not isinstance(raw_data, dict):
            return False
        # Langfuse: traces array
        if raw_data.get("traces"):
            return True
        # Direct observations (Langfuse trace detail)
        if raw_data.get("observations"):
            return True
        # OpenAI: data array
        if raw_data.get("data"):
            return True
        # Langsmith: runs
        if raw_data.get("runs"):
            return True
        # Generic: any non-empty list/dict value beyond metadata keys
        skip = {"id", "createdAt", "projectId", "environment", "sessionId", "public"}
        for k, v in raw_data.items():
            if k not in skip and v and isinstance(v, (list, dict)) and len(v) > 0:
                return True
        return False

    def fetch(self, session_metadata, total_turns):
        """Fetch telemetry data after conversation completes.

        Uses progressive retry with delay to allow vendor ingestion:
        - Initial 5s delay
        - Up to 3 retries with increasing delays (2s, 5s, 8s)
        - Total max wait: ~20s before giving up
        """
        try:
            fetch_payload = {
                **session_metadata,
                "TOTAL_TURNS": total_turns,
                "HUMANBOUND_EID": self.e_id,
            }

            # Initial delay — allow vendor to ingest traces (~15s for Langfuse)
            time.sleep(15)

            retry_delay = 5
            max_retries = 3

            for attempt in range(max_retries + 1):
                raw_data = self.__make_api_call(
                    fetch_payload,
                    self.config["endpoint"],
                    self.config["headers"].copy(),
                    self.config.get("payload", {}).copy(),
                )

                standardized = self.__standardize(raw_data)

                # Check if standardized result has meaningful data
                has_data = (
                    standardized.get("tool_executions")
                    or standardized.get("memory_operations")
                    or standardized.get("resource_usage", {}).get("tokens_used", 0) > 0
                )
                if has_data:
                    return standardized

                # Last attempt — don't sleep
                if attempt == max_retries:
                    break

                time.sleep(retry_delay)
                retry_delay += 5  # 5 → 10 → 15

            # All retries exhausted — return whatever we got (may be empty)
            return standardized if raw_data else None

        except Exception as e:
            # Graceful degradation — continue without telemetry
            return None

    @staticmethod
    def __navigate_path(data, path):
        """Navigate nested dict/list structure using dot notation path"""
        if not path or data is None:
            return None

        try:
            parts = path.split(".")
            current = data

            for part in parts:
                # Handle array notation like "items[*]" or "items[0]"
                if "[" in part and "]" in part:
                    key = part.split("[")[0]
                    index_part = part.split("[")[1].split("]")[0]

                    if isinstance(current, dict) and key in current:
                        current = current[key]
                    else:
                        return None

                    # Handle wildcard [*] - return the list itself for iteration
                    if index_part == "*":
                        return current if isinstance(current, list) else None
                    # Handle specific index
                    else:
                        idx = int(index_part)
                        if isinstance(current, list) and 0 <= idx < len(current):
                            current = current[idx]
                        else:
                            return None
                else:
                    # Regular dict navigation
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return None

            return current

        except Exception:
            return None

    @staticmethod
    def standardize_accumulated_metadata(accumulated_metadata, extraction_map):
        """
        Standardize per-turn metadata into common telemetry format

        Args:
            accumulated_metadata: List of {"turn": int, "metadata": dict} objects
            extraction_map: Dict with paths for extracting fields from metadata

        Returns:
            Standardized telemetry data in common format
        """
        try:
            standardized = {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }

            total_tokens = 0
            total_api_calls = 0

            for turn_data in accumulated_metadata:
                turn_num = turn_data.get("turn", 0)
                metadata = turn_data.get("metadata", {})

                if not metadata:
                    continue

                # Extract tool executions
                tool_path = extraction_map.get("tool_executions")
                if tool_path:
                    tool_items = Telemetry.__navigate_path(metadata, tool_path)

                    if isinstance(tool_items, list):
                        for tool_item in tool_items:
                            tool_exec = {"turn": turn_num}

                            # Extract tool fields using configured paths
                            name_field = extraction_map.get(
                                "tool_executions.tool_name", "name"
                            )
                            tool_exec["tool_name"] = Telemetry.__navigate_path(
                                tool_item, name_field
                            ) or tool_item.get("name", "")

                            params_field = extraction_map.get(
                                "tool_executions.parameters", "parameters"
                            )
                            tool_exec["parameters"] = Telemetry.__navigate_path(
                                tool_item, params_field
                            ) or tool_item.get("parameters", {})

                            result_field = extraction_map.get(
                                "tool_executions.result", "result"
                            )
                            tool_exec["result"] = Telemetry.__navigate_path(
                                tool_item, result_field
                            ) or tool_item.get("result", "")

                            standardized["tool_executions"].append(tool_exec)

                # Extract memory operations
                memory_path = extraction_map.get("memory_operations")
                if memory_path:
                    memory_items = Telemetry.__navigate_path(metadata, memory_path)

                    if isinstance(memory_items, list):
                        for mem_item in memory_items:
                            mem_op = {"turn": turn_num}

                            op_type_field = extraction_map.get(
                                "memory_operations.operation_type", "operation_type"
                            )
                            mem_op["operation_type"] = Telemetry.__navigate_path(
                                mem_item, op_type_field
                            ) or mem_item.get("operation_type", "")

                            content_field = extraction_map.get(
                                "memory_operations.content", "content"
                            )
                            mem_op["content"] = Telemetry.__navigate_path(
                                mem_item, content_field
                            ) or mem_item.get("content", "")

                            standardized["memory_operations"].append(mem_op)

                # Extract resource usage (accumulate across turns)
                tokens_path = extraction_map.get("resource_usage.tokens_used")
                if tokens_path:
                    tokens = Telemetry.__navigate_path(metadata, tokens_path)
                    if isinstance(tokens, (int, float)):
                        total_tokens += int(tokens)

                total_api_calls += 1

            # Set accumulated resource usage
            if total_tokens > 0:
                standardized["resource_usage"]["tokens_used"] = total_tokens
            if total_api_calls > 0:
                standardized["resource_usage"]["api_calls_count"] = total_api_calls

            return standardized

        except Exception as e:
            # Return empty standardized structure on error
            return {
                "tool_executions": [],
                "memory_operations": [],
                "external_calls": [],
                "resource_usage": {},
                "authorization_events": [],
                "agent_delegation": [],
            }
