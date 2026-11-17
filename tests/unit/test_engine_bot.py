# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Unit tests for the Bot / ResponseExtractor / Telemetry classes in
``humanbound_cli.engine.bot``.

Covers the pure-logic pieces directly (placeholder substitution, response
extraction, header preparation, payload preparation) and the ``init()`` +
``ping()`` flows with ``requests`` mocked. The full telemetry parsers for
each provider (OpenAI Assistants / LangSmith / LangFuse / W&B / Helicone /
AgentOps) are covered here at smoke level — exhaustive provider-specific
parser tests would live alongside their respective real fixtures.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from humanbound_cli.engine.bot import (
    Bot,
    ResponseExtractor,
    Telemetry,
    _raise_if_redirect,
)

# ────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ────────────────────────────────────────────────────────────────


@pytest.fixture
def bot_config():
    """Minimal bot config — REST, non-streaming."""
    return {
        "streaming": None,
        "thread_auth": {"endpoint": "", "headers": {}, "payload": {}},
        "thread_init": {
            "endpoint": "https://agent.example/start",
            "headers": {"x-api-key": "k"},
            "payload": {"user": "u1"},
        },
        "chat_completion": {
            "endpoint": "https://agent.example/chat",
            "headers": {"x-api-key": "k"},
            "payload": {"message": "$prompt"},
        },
    }


@pytest.fixture
def bot(bot_config):
    return Bot(bot_config, e_id="exp-abc")


def _strip_conversation_id(payload):
    """Pop humanbound_conversation_id (asserting its shape) so existing exact-equality
    assertions on init()'s return value keep holding."""
    payload = dict(payload)
    conv_id = payload.pop("humanbound_conversation_id")
    assert isinstance(conv_id, str) and len(conv_id) == 32
    return payload


def _mock_post(status=200, payload=None, text="", is_redirect=False, location=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.is_redirect = is_redirect
    r.headers = {"location": location} if location else {}
    r.json = MagicMock(return_value=payload or {})
    return r


# ────────────────────────────────────────────────────────────────
# ResponseExtractor — base behaviour
# ────────────────────────────────────────────────────────────────


def test_response_extractor_default_returns_none():
    assert ResponseExtractor().extract_custom_response({"anything": 1}) is None


def test_bot_inherits_from_response_extractor(bot):
    assert isinstance(bot, ResponseExtractor)


def test_bot_rejects_connector_config():
    """The offline engine is classic-HTTP only; connector configs must fail fast."""
    connector_cfg = {
        "connector": {
            "provider": "openai_assistants",
            "config": {"api_key": "sk-x", "target_id": "asst_x"},
        }
    }
    with pytest.raises(ValueError, match="not supported by the offline engine"):
        Bot(connector_cfg, e_id="exp-abc")


# ────────────────────────────────────────────────────────────────
# __extract_ai_response — dict with standard keys, custom, fallback
# ────────────────────────────────────────────────────────────────


def test_extract_ai_response_prefers_content_key(bot):
    assert bot._Bot__extract_ai_response({"content": "hello"}) == "hello"


def test_extract_ai_response_falls_through_to_text(bot):
    assert bot._Bot__extract_ai_response({"text": "hi"}) == "hi"


def test_extract_ai_response_uses_custom_extractor(bot):
    class CustomBot(Bot):
        def extract_custom_response(self, chunk):
            return chunk.get("weird_format_field")

    b = CustomBot({"streaming": None}, "e1")
    result = b._Bot__extract_ai_response({"weird_format_field": "custom value"})
    assert result == "custom value"


def test_extract_ai_response_non_dict_stringifies(bot):
    assert bot._Bot__extract_ai_response(42) == "42"
    assert bot._Bot__extract_ai_response("plain") == "plain"


# ────────────────────────────────────────────────────────────────
# __parse_payload_item — placeholder substitution
# ────────────────────────────────────────────────────────────────


def test_parse_payload_substitutes_prompt(bot):
    out, found = bot._Bot__parse_payload_item("$prompt", {}, u_prompt="hi there")
    assert out == "hi there"
    assert found is True


def test_parse_payload_substitutes_humanbound_eid(bot):
    out, found = bot._Bot__parse_payload_item("$humanbound_eid", {}, u_prompt="")
    assert out == "exp-abc"
    assert found is False


def test_parse_payload_substitutes_conversation_as_openai_shape(bot):
    conv = [{"u": "hi", "a": "hello"}, {"u": "again"}]
    out, _ = bot._Bot__parse_payload_item("$conversation", {}, conversation=conv)
    # Intent: returns the conversation list mapped into OpenAI role shape.
    assert isinstance(out, list)
    assert any(item.get("role") == "user" and item.get("content") == "hi" for item in out)


def test_parse_payload_recurses_into_dict_and_list(bot):
    payload = {"outer": {"inner": ["$prompt", "literal"]}}
    out, found = bot._Bot__parse_payload_item(payload, {}, u_prompt="THE PROMPT")
    assert out["outer"]["inner"][0] == "THE PROMPT"
    assert out["outer"]["inner"][1] == "literal"
    assert found is True


def test_parse_payload_case_insensitive(bot):
    out1, _ = bot._Bot__parse_payload_item("$PROMPT", {}, u_prompt="hi")
    out2, _ = bot._Bot__parse_payload_item("$Prompt", {}, u_prompt="hi")
    assert out1 == "hi"
    assert out2 == "hi"


def test_parse_payload_passes_through_plain_string(bot):
    out, found = bot._Bot__parse_payload_item("unchanged", {}, u_prompt="ignored")
    assert out == "unchanged"
    assert found is False


def test_parse_payload_passes_through_empty_string(bot):
    # An empty string is not a placeholder — it must pass through unchanged
    # rather than crashing on the item[0] prefix check.
    out, found = bot._Bot__parse_payload_item("", {}, u_prompt="ignored")
    assert out == ""
    assert found is False


def test_prepare_headers_allows_empty_value(bot):
    # Empty header values (e.g. an optional meta header left blank) must not crash.
    out = bot._Bot__prepare_headers({"x-optional-meta": ""}, {})
    assert out["x-optional-meta"] == ""


def test_parse_payload_passes_through_non_string_scalars(bot):
    # None / numbers / booleans aren't placeholders — they fall through the
    # dict/list/str checks and are returned unchanged (the "other base type" path).
    for value in [None, 0, 42, 3.14, True]:
        out, found = bot._Bot__parse_payload_item(value, {})
        assert out is value
        assert found is False


# ────────────────────────────────────────────────────────────────
# __prepare_endpoint — path templating
# ────────────────────────────────────────────────────────────────


def test_prepare_endpoint_substitutes_scalar_values(bot):
    endpoint = "https://agent.example/sessions/$session_id/chat"
    payload = {"session_id": "sess-42", "other": [1, 2, 3]}
    out = bot._Bot__prepare_endpoint(endpoint, payload)
    assert out == "https://agent.example/sessions/sess-42/chat"


def test_prepare_endpoint_leaves_non_scalar_keys_alone(bot):
    endpoint = "https://agent.example/$list"
    # Lists / dicts in payload should not be substituted into the URL.
    out = bot._Bot__prepare_endpoint(endpoint, {"list": [1, 2], "obj": {"a": 1}})
    assert out == "https://agent.example/$list"


# ────────────────────────────────────────────────────────────────
# __prepare_headers — auth flows
# ────────────────────────────────────────────────────────────────


def test_prepare_headers_bearer_token_from_access_token(bot):
    out = bot._Bot__prepare_headers({}, {"access_token": "xyz"})
    assert out["authorization"] == "Bearer xyz"
    assert out["content-type"] == "application/json"
    assert out["x-humanbound-test-id"] == "exp-abc"


def test_prepare_headers_custom_auth_schema(bot):
    headers = {
        "x-humanbound-auth-schema": {
            "label": "x-auth",
            "key": "session_token",
            "value": "Token $token",
        },
    }
    out = bot._Bot__prepare_headers(headers, {"session_token": "abc123"})
    assert out["x-auth"] == "Token abc123"
    assert "x-humanbound-auth-schema" not in out


def test_prepare_headers_invalid_auth_schema_raises(bot):
    with pytest.raises(Exception, match="400"):
        bot._Bot__prepare_headers({"x-humanbound-auth-schema": "not a dict"}, {})


def test_prepare_headers_auth_schema_missing_key_from_payload(bot):
    headers = {
        "x-humanbound-auth-schema": {"key": "session_token", "label": "x-auth", "value": "Token"},
    }
    with pytest.raises(Exception, match="400"):
        bot._Bot__prepare_headers(headers, {})  # session_token missing


# ────────────────────────────────────────────────────────────────
# __prepare_payload — placeholder + OpenAI fallback
# ────────────────────────────────────────────────────────────────


def test_prepare_payload_dict_with_prompt_placeholder(bot):
    out = bot._Bot__prepare_payload({"msg": "$prompt"}, {}, u_prompt="hi")
    assert out == {"msg": "hi"}


def test_prepare_payload_dict_without_prompt_uses_openai_fallback(bot):
    out = bot._Bot__prepare_payload({"temperature": 0}, {}, u_prompt="hi")
    # Fallback appends a messages array with the user prompt.
    assert "messages" in out
    assert out["messages"] == [{"role": "user", "content": "hi"}]


def test_prepare_payload_openai_fallback_includes_conversation(bot):
    conv = [{"u": "previous", "a": "response"}]
    out = bot._Bot__prepare_payload({}, {}, u_prompt="now", conversation=conv)
    assert out["messages"] == [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "response"},
        {"role": "user", "content": "now"},
    ]


def test_prepare_payload_list_without_prompt_raises(bot):
    with pytest.raises(Exception, match=r"\$prompt"):
        bot._Bot__prepare_payload(["no-placeholder"], {}, u_prompt="hi")


def test_prepare_payload_string_substitutes_prompt_placeholder(bot):
    out = bot._Bot__prepare_payload("send: $prompt", {}, u_prompt="hello")
    assert out == "send: hello"


def test_prepare_payload_empty_prompt_skips_openai_fallback(bot):
    out = bot._Bot__prepare_payload({"just": "data"}, {}, u_prompt="")
    assert "messages" not in out


# ────────────────────────────────────────────────────────────────
# __extract_turn_metadata — per-turn telemetry path navigation
# ────────────────────────────────────────────────────────────────


def test_extract_turn_metadata_returns_none_when_mode_not_per_turn(bot):
    bot.bot_config["telemetry"] = {"mode": "end_of_conversation"}
    assert bot._Bot__extract_turn_metadata({"data": {"foo": 1}}) is None


def test_extract_turn_metadata_navigates_dot_path():
    config = {
        "streaming": None,
        "telemetry": {
            "mode": "per_turn",
            "extraction_map": {"metadata_path": "data.autopilot.meta"},
        },
    }
    b = Bot(config, "e1")
    response = {"data": {"autopilot": {"meta": {"latency_ms": 120}}}}
    assert b._Bot__extract_turn_metadata(response) == {"latency_ms": 120}


def test_extract_turn_metadata_missing_path_returns_none():
    config = {
        "streaming": None,
        "telemetry": {
            "mode": "per_turn",
            "extraction_map": {"metadata_path": "not.there"},
        },
    }
    b = Bot(config, "e1")
    assert b._Bot__extract_turn_metadata({"data": {}}) is None


# ────────────────────────────────────────────────────────────────
# init() — end-to-end REST handshake with requests mocked
# ────────────────────────────────────────────────────────────────


def test_init_stores_session_from_thread_init(bot):
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        post.return_value = _mock_post(payload={"session_id": "sess-99"})
        out = bot.init()
    assert _strip_conversation_id(out) == {"session_id": "sess-99"}


def test_init_with_auth_step_merges_payloads(bot_config):
    bot_config["thread_auth"] = {
        "endpoint": "https://agent.example/auth",
        "headers": {},
        "payload": {"client_id": "c"},
    }
    b = Bot(bot_config, "exp-1")
    with (
        patch("humanbound_cli.engine.bot.requests.post") as post,
        patch("humanbound_cli.engine.bot.time.sleep"),
    ):
        post.side_effect = [
            _mock_post(payload={"access_token": "tok"}),
            _mock_post(payload={"session_id": "sess"}),
        ]
        out = b.init()
    assert _strip_conversation_id(out) == {"access_token": "tok", "session_id": "sess"}


def test_init_skips_thread_init_when_endpoint_empty(bot_config):
    bot_config["thread_auth"] = {"endpoint": "", "headers": {}, "payload": {}}
    bot_config["thread_init"] = {"endpoint": "", "headers": {}, "payload": {}}
    b = Bot(bot_config, "exp-1")
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        out = b.init()
    assert _strip_conversation_id(out) == {}
    post.assert_not_called()


def test_init_skips_thread_init_when_null(bot_config):
    bot_config["thread_auth"] = None
    bot_config["thread_init"] = None
    b = Bot(bot_config, "exp-1")
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        out = b.init()
    assert _strip_conversation_id(out) == {}
    post.assert_not_called()


def test_init_skips_thread_init_when_missing(bot_config):
    bot_config.pop("thread_auth", None)
    bot_config.pop("thread_init", None)
    b = Bot(bot_config, "exp-1")
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        out = b.init()
    assert _strip_conversation_id(out) == {}
    post.assert_not_called()


def test_init_runs_auth_then_skips_thread_init(bot_config):
    bot_config["thread_auth"] = {
        "endpoint": "https://agent.example/auth",
        "headers": {},
        "payload": {},
    }
    bot_config["thread_init"] = None
    b = Bot(bot_config, "exp-1")
    with (
        patch("humanbound_cli.engine.bot.requests.post") as post,
        patch("humanbound_cli.engine.bot.time.sleep"),
    ):
        post.return_value = _mock_post(payload={"access_token": "tok"})
        out = b.init()
    assert _strip_conversation_id(out) == {"access_token": "tok"}
    assert post.call_count == 1  # auth fired, thread_init skipped


def test_init_bad_status_raises(bot):
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        post.return_value = _mock_post(status=500, text="boom")
        with pytest.raises(Exception, match="502/Testing AI Agent"):
            bot.init()


def test_init_timeout_raises_408(bot):
    import requests as req_real

    with patch(
        "humanbound_cli.engine.bot.requests.post", side_effect=req_real.exceptions.Timeout()
    ):
        with pytest.raises(Exception, match="408"):
            bot.init()


# ────────────────────────────────────────────────────────────────
# ping() (non-streaming) — chat completion
# ────────────────────────────────────────────────────────────────


def test_ping_non_streaming_returns_extracted_response(bot):
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        post.return_value = _mock_post(payload={"content": "agent says hi"})
        resp, exec_t, *_ = asyncio.run(bot.ping({}, "user prompt"))
    assert resp == "agent says hi"
    assert isinstance(exec_t, float)


def test_ping_non_streaming_with_list_response_uses_last(bot):
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        post.return_value = _mock_post(payload=[{"content": "first"}, {"content": "last"}])
        resp, _, *_ = asyncio.run(bot.ping({}, "hi"))
    assert resp == "last"


def test_ping_non_streaming_with_string_response(bot):
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        resp_mock = _mock_post(text="plain text response")
        resp_mock.json.side_effect = ValueError("not json")
        post.return_value = resp_mock
        resp, _, *_ = asyncio.run(bot.ping({}, "hi"))
    assert resp == "plain text response"


def test_ping_non_streaming_without_headers_or_payload():
    # A chat_completion block with only an endpoint (no `headers`/`payload`) is a
    # natural shape for a no-auth agent. It must not crash with KeyError; the
    # engine should default both to {}. Regression test for #51.
    bot = Bot({"chat_completion": {"endpoint": "https://agent.example/chat"}}, "exp-abc")
    with patch("humanbound_cli.engine.bot.requests.post") as post:
        post.return_value = _mock_post(payload={"content": "agent says hi"})
        resp, _, *_ = asyncio.run(bot.ping({}, "user prompt"))
        sent = post.call_args.kwargs["json"]
    assert resp == "agent says hi"
    # With no `$PROMPT` placeholder and an empty payload, the engine falls back to
    # the OpenAI-style messages array.
    assert sent["messages"][-1] == {"role": "user", "content": "user prompt"}


@pytest.mark.parametrize(
    "bot_config",
    [
        {},  # no chat_completion block at all
        {"chat_completion": {}},  # block present, endpoint missing
        {"chat_completion": {"endpoint": ""}},  # endpoint empty
    ],
)
def test_ping_fails_clearly_when_endpoint_is_missing(bot_config):
    # Unlike headers/payload, `endpoint` is genuinely required — a missing one
    # must surface as a clear config error, not a raw KeyError.
    bot = Bot(bot_config, "exp-abc")
    with pytest.raises(Exception, match="chat_completion.endpoint"):
        asyncio.run(bot.ping({}, "user prompt"))


# ────────────────────────────────────────────────────────────────
# Telemetry — smoke coverage
# ────────────────────────────────────────────────────────────────


def test_telemetry_constructs_cleanly():
    config = {
        "mode": "end_of_conversation",
        "format": "langfuse",
        "endpoint": "https://telemetry.example/$session_id",
        "headers": {"Authorization": "Basic k"},
        "payload": {},
    }
    t = Telemetry(config, "exp-1")
    assert t is not None


def test_telemetry_has_no_data_returns_true_for_empty():
    config = {
        "mode": "end_of_conversation",
        "format": "langfuse",
        "endpoint": "",
        "headers": {},
        "payload": {},
    }
    t = Telemetry(config, "exp-1")
    # _has_telemetry_data returns a boolean indicating presence.
    # Smoke-check: does not raise for standard inputs.
    result = t._has_telemetry_data({})
    assert isinstance(result, bool)


def test_telemetry_fetch_retries_immediately_and_returns_late_data():
    tel = Telemetry(
        {"endpoint": "https://tele.example/fetch", "headers": {}, "payload": {}},
        e_id="e1",
    )
    empty = {
        "tool_executions": [],
        "memory_operations": [],
        "resource_usage": {"tokens_used": 0},
    }
    data = {
        "tool_executions": [{"tool_name": "search"}],
        "memory_operations": [],
        "resource_usage": {"tokens_used": 0},
    }
    sleep = patch("humanbound_cli.engine.bot.time.sleep")
    api_call_counts = []

    def fetch_response(*args, **kwargs):
        api_call_counts.append(sleep_mock.call_count)
        return {"data": []}

    with (
        sleep as sleep_mock,
        patch.object(tel, "_Telemetry__make_api_call", side_effect=fetch_response) as api_call,
        patch.object(tel, "_Telemetry__standardize", side_effect=[empty, data]),
    ):
        result = tel.fetch({"session_id": "s1"}, 2)

    assert result == data
    assert api_call.call_count == 2
    assert api_call_counts == [0, 1]
    assert [call.args[0] for call in sleep_mock.call_args_list] == [2]


def test_telemetry_fetch_returns_traces_ready_after_15_seconds():
    tel = Telemetry(
        {"endpoint": "https://tele.example/fetch", "headers": {}, "payload": {}},
        e_id="e1",
    )
    empty = {
        "tool_executions": [],
        "memory_operations": [],
        "resource_usage": {"tokens_used": 0},
    }
    data = {
        "tool_executions": [{"tool_name": "search"}],
        "memory_operations": [],
        "resource_usage": {"tokens_used": 0},
    }
    elapsed = 0
    attempt_times = []

    def fetch_response(*args, **kwargs):
        attempt_times.append(elapsed)
        return {"data": []}

    def advance_time(delay):
        nonlocal elapsed
        elapsed += delay

    with (
        patch("humanbound_cli.engine.bot.time.sleep", side_effect=advance_time) as sleep,
        patch.object(tel, "_Telemetry__make_api_call", side_effect=fetch_response) as api_call,
        patch.object(tel, "_Telemetry__standardize", side_effect=[empty, empty, empty, data]),
    ):
        result = tel.fetch({"session_id": "s1"}, 2)

    assert result == data
    assert api_call.call_count == 4
    assert attempt_times == [0, 2, 7, 17]
    assert [call.args[0] for call in sleep.call_args_list] == [2, 5, 10]


def test_telemetry_fetch_caps_retry_delay_and_returns_last_result():
    tel = Telemetry(
        {"endpoint": "https://tele.example/fetch", "headers": {}, "payload": {}},
        e_id="e1",
    )
    empty = {
        "tool_executions": [],
        "memory_operations": [],
        "resource_usage": {"tokens_used": 0},
    }

    with (
        patch.object(tel, "_Telemetry__make_api_call", return_value={"data": []}) as api_call,
        patch.object(tel, "_Telemetry__standardize", return_value=empty),
        patch("humanbound_cli.engine.bot.time.sleep") as sleep,
    ):
        result = tel.fetch({"session_id": "s1"}, 2)

    assert result == empty
    assert api_call.call_count == 6
    assert [call.args[0] for call in sleep.call_args_list] == [2, 5, 10, 15, 15]


# ────────────────────────────────────────────────────────────────
# Redirect credential-leak guard
# ────────────────────────────────────────────────────────────────


def test_raise_if_redirect_handles_missing_location():
    with pytest.raises(Exception, match="not followed for security"):
        _raise_if_redirect(_mock_post(status=307, is_redirect=True))


def test_make_api_call_rejects_redirect_and_disables_following(bot):
    redirect = _mock_post(status=302, is_redirect=True, location="https://evil.example/steal")
    with patch("humanbound_cli.engine.bot.requests.post", return_value=redirect) as post:
        with pytest.raises(Exception, match=r"evil\.example"):
            bot._Bot__make_api_call({}, "https://agent.example/chat", {}, {"m": "x"})
    assert post.call_args.kwargs.get("allow_redirects") is False


def test_make_api_call_rejects_redirect_on_405_get_fallback(bot):
    post_405 = _mock_post(status=405)
    get_302 = _mock_post(status=302, is_redirect=True, location="https://evil.example/steal")
    with (
        patch("humanbound_cli.engine.bot.requests.post", return_value=post_405),
        patch("humanbound_cli.engine.bot.requests.get", return_value=get_302) as get,
    ):
        with pytest.raises(Exception, match="not followed for security"):
            bot._Bot__make_api_call({}, "https://agent.example/chat", {}, {"m": "x"})
    assert get.call_args.kwargs.get("allow_redirects") is False


def test_make_api_call_allows_normal_2xx(bot):
    ok = _mock_post(status=200, payload={"content": "hi"})
    with patch("humanbound_cli.engine.bot.requests.post", return_value=ok):
        data, _, _ = bot._Bot__make_api_call({}, "https://agent.example/chat", {}, {"m": "x"})
    assert data == {"content": "hi"}


def test_make_api_call_does_not_swallow_keyboard_interrupt(bot):
    resp = _mock_post(status=200, text="raw")
    resp.json.side_effect = KeyboardInterrupt
    with patch("humanbound_cli.engine.bot.requests.post", return_value=resp):
        with pytest.raises(KeyboardInterrupt):
            bot._Bot__make_api_call({}, "https://agent.example/chat", {}, {"m": "x"})


def test_telemetry_make_api_call_does_not_swallow_keyboard_interrupt():
    tel = Telemetry(
        {"endpoint": "https://tele.example/fetch", "headers": {}, "payload": {}, "method": "POST"},
        e_id="e1",
    )
    resp = _mock_post(status=200, text="raw")
    resp.json.side_effect = KeyboardInterrupt
    with patch("humanbound_cli.engine.bot.requests.post", return_value=resp):
        with pytest.raises(KeyboardInterrupt):
            tel._Telemetry__make_api_call({}, "https://tele.example/fetch", {}, {})


def test_telemetry_make_api_call_rejects_redirect():
    tel = Telemetry(
        {"endpoint": "https://tele.example/fetch", "headers": {}, "payload": {}, "method": "POST"},
        e_id="e1",
    )
    redirect = _mock_post(status=302, is_redirect=True, location="https://evil.example/steal")
    with patch("humanbound_cli.engine.bot.requests.post", return_value=redirect) as post:
        with pytest.raises(Exception, match="not followed for security"):
            tel._Telemetry__make_api_call({}, "https://tele.example/fetch", {}, {})
    assert post.call_args.kwargs.get("allow_redirects") is False


def _async_cm(enter_value):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=enter_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_stream_sse_rejects_redirect_and_disables_following(bot):
    redirect_resp = MagicMock()
    redirect_resp.is_redirect = True
    redirect_resp.status_code = 302
    redirect_resp.headers = {"location": "https://evil.example/steal"}

    client = MagicMock()
    client.stream = MagicMock(return_value=_async_cm(redirect_resp))

    with patch("humanbound_cli.engine.bot.httpx.AsyncClient", return_value=_async_cm(client)) as ac:
        with pytest.raises(Exception, match="not followed for security"):
            asyncio.run(bot._Bot__stream_sse({}, "hi"))
    assert ac.call_args.kwargs.get("follow_redirects") is False


def test_stream_websocket_blocks_handshake_redirect(bot):
    import websockets.asyncio.client as wsc
    from websockets.exceptions import SecurityError

    def _boom(*a, **k):
        raise SecurityError("more than 1 redirects")

    with patch.object(wsc, "connect", side_effect=_boom):
        with pytest.raises(Exception, match="not followed for security"):
            asyncio.run(bot._Bot__stream({}, "hi"))
    # module-level redirect budget capped to the initial handshake
    assert wsc.MAX_REDIRECTS == 1


# ────────────────────────────────────────────────────────────────
# A2A support: $UUID and humanbound_conversation_id
# ────────────────────────────────────────────────────────────────

_PLAIN_CONFIG = {
    "streaming": None,
    "chat_completion": {"endpoint": "https://agent.example/chat", "payload": {"q": "$PROMPT"}},
}


def test_uuid_placeholder_is_fresh_per_occurrence():
    bot = Bot(_PLAIN_CONFIG, "e1")
    out, found = bot._Bot__parse_payload_item({"a": "$UUID", "b": "$UUID"}, {}, "hi", [])
    assert found is False
    assert len(out["a"]) == 32 and len(out["b"]) == 32
    assert out["a"] != out["b"]


def test_init_seeds_a_new_conversation_id_each_time():
    first = Bot(_PLAIN_CONFIG, "e1").init()
    second = Bot(_PLAIN_CONFIG, "e1").init()
    assert len(first["humanbound_conversation_id"]) == 32
    assert first["humanbound_conversation_id"] != second["humanbound_conversation_id"]


def test_conversation_id_placeholder_is_stable_within_a_conversation():
    bot = Bot(_PLAIN_CONFIG, "e1")
    base = bot.init()
    one, _ = bot._Bot__parse_payload_item({"c": "$humanbound_conversation_id"}, base, "x", [])
    two, _ = bot._Bot__parse_payload_item({"c": "$humanbound_conversation_id"}, base, "y", [])
    assert one["c"] == two["c"] == base["humanbound_conversation_id"]


# ────────────────────────────────────────────────────────────────
# chat_completion.response — configurable reply completion / text path
# (event-based WebSocket agents such as ElevenLabs)
# ────────────────────────────────────────────────────────────────

_ELEVENLABS_STREAM = [
    {
        "type": "conversation_initiation_metadata",
        "conversation_initiation_metadata_event": {"conversation_id": "c1"},
    },
    {"type": "ping", "ping_event": {"event_id": 1, "ping_ms": None}},
    {"type": "agent_chat_response_part", "text_response_part": {"text": "noise", "type": "delta"}},
    {"type": "agent_response", "agent_response_event": {"agent_response": "Hello there"}},
]


def _ws_config(response=None):
    cc = {
        "endpoint": "wss://agent.example/convai",
        "payload": {"type": "user_message", "text": "$PROMPT"},
    }
    if response is not None:
        cc["response"] = response
    return {"streaming": "websocket", "chat_completion": cc}


class _FakeSocket:
    """Yields the scripted messages, then behaves like a server that closes the
    socket for inactivity (what ElevenLabs does when the client keeps waiting).

    `replies` maps a sent message's text to the messages the server sends back,
    so multi-turn conversations can be scripted. A "WAIT" entry makes recv()
    block (no message arrives), which lets tests exercise the greeting timeout."""

    def __init__(self, messages, replies=None, idle_close=True):
        import json as _json

        self._json = _json
        self._queue = list(messages)
        self._replies = replies or {}
        self._idle_close = idle_close
        self.sent = []
        self.recv_calls = 0
        self.closed = False

    @property
    def state(self):
        from websockets.protocol import State

        return State.CLOSED if self.closed else State.OPEN

    async def send(self, data):
        self.sent.append(data)
        text = self._json.loads(data).get("text")
        self._queue.extend(self._replies.get(text, []))

    async def recv(self):
        self.recv_calls += 1
        if self._queue and self._queue[0] == "WAIT":
            self._queue.pop(0)
            await asyncio.sleep(3600)
        if not self._queue:
            if not self._idle_close:
                await asyncio.sleep(3600)
            raise RuntimeError("received 1002 (protocol error) No user message received")
        return self._json.dumps(self._queue.pop(0))

    async def close(self):
        self.closed = True


def _fake_connect(*socks):
    """Patch target for websockets connect(): each call returns the next socket."""
    queue = list(socks)
    calls = []

    async def connect(endpoint, **kwargs):
        calls.append(endpoint)
        return queue.pop(0)

    connect.calls = calls
    return connect


def _run_ws(config, messages):
    import websockets.asyncio.client as wsc

    sock = _FakeSocket(messages)
    with patch.object(wsc, "connect", _fake_connect(sock)):
        text, _, _ = asyncio.run(Bot(config, "e1")._Bot__stream({}, "hi"))
    return text, sock


def test_ws_stops_on_complete_when_and_reads_text_path():
    cfg = _ws_config(
        {
            "complete_when": {"type": "agent_response"},
            "text_path": "agent_response_event.agent_response",
        }
    )
    text, sock = _run_ws(cfg, _ELEVENLABS_STREAM)
    assert text == "Hello there"
    assert sock.recv_calls == len(_ELEVENLABS_STREAM)  # never waits past the reply
    assert '"type": "user_message"' in sock.sent[0]


def test_ws_without_completion_rule_keeps_waiting_and_fails():
    # the reported bug: no {"type": "end"} ever arrives, so the server times us out
    with pytest.raises(Exception, match="No user message received"):
        _run_ws(_ws_config(), _ELEVENLABS_STREAM)


def test_ws_legacy_end_message_still_stops():
    text, _ = _run_ws(_ws_config(), [{"content": "a"}, {"content": "b"}, {"type": "end"}])
    assert text == "ab"


def test_ws_complete_when_without_text_path_uses_default_keys():
    msgs = [{"type": "delta", "content": "Hi "}, {"type": "done", "content": "you"}]
    text, _ = _run_ws(_ws_config({"complete_when": {"type": "done"}}), msgs)
    assert text == "Hi you"


def test_ws_text_path_accumulates_deltas_until_completion():
    msgs = [
        {"event": "delta", "data": {"chunk": "Hel"}},
        {"event": "delta", "data": {"chunk": "lo"}},
        {"event": "finished", "data": {}},
    ]
    cfg = _ws_config({"complete_when": {"event": "finished"}, "text_path": "data.chunk"})
    text, _ = _run_ws(cfg, msgs)
    assert text == "Hello"


def test_complete_when_matches_nested_path_and_all_conditions():
    b = Bot(_ws_config({"complete_when": {"meta.final": True, "type": "msg"}}), "e1")
    assert b._Bot__process_chunk({"type": "msg", "meta": {"final": False}}, "")[1] is False
    assert b._Bot__process_chunk({"type": "msg", "meta": {"final": True}}, "")[1] is True


def test_rest_text_path_extracts_reply():
    cfg = {
        "streaming": None,
        "chat_completion": {
            "endpoint": "https://agent.example/chat",
            "payload": {"q": "$PROMPT"},
            "response": {"text_path": "result.messages.1.body"},
        },
    }
    body = {"result": {"messages": [{"body": "ignored"}, {"body": "the reply"}]}, "text": "x"}
    with patch("humanbound_cli.engine.bot.requests.post", return_value=_mock_post(payload=body)):
        text, _, _ = asyncio.run(Bot(cfg, "e1").ping({}, "hi"))
    assert text == "the reply"


@pytest.mark.parametrize(
    "response, match",
    [
        ({"complete_when": "agent_response"}, "complete_when"),
        ({"complete_when": {}}, "complete_when"),
        ({"text_path": 5}, "text_path"),
        ({"ignore_when": []}, "ignore_when"),
        ("oops", "response"),
    ],
)
def test_invalid_response_rules_fail_clearly(response, match):
    with pytest.raises(Exception, match=match):
        _run_ws(_ws_config(response), _ELEVENLABS_STREAM)


# ────────────────────────────────────────────────────────────────
# chat_completion.websocket — one connection per conversation, greeting,
# automatic replies (ElevenLabs keeps the conversation in the connection)
# ────────────────────────────────────────────────────────────────

_GREETING = {
    "type": "agent_response",
    "agent_response_event": {"agent_response": "Hello!", "in_response_to_ids": []},
}
_META = {"type": "conversation_initiation_metadata", "conversation_initiation_metadata_event": {}}


def _say(text, in_response_to=("u",)):
    return {
        "type": "agent_response",
        "agent_response_event": {
            "agent_response": text,
            "in_response_to_ids": list(in_response_to),
        },
    }


def _session_config(**ws):
    cfg = _ws_config(
        {
            "complete_when": {"type": "agent_response"},
            "text_path": "agent_response_event.agent_response",
            "ignore_when": {
                "type": "agent_response",
                "agent_response_event.in_response_to_ids": [],
            },
        }
    )
    cfg["chat_completion"]["websocket"] = ws
    return cfg


def _conversation(config, socks, prompts):
    """Run one conversation (init + several turns) on a single event loop."""
    import websockets.asyncio.client as wsc

    connect = _fake_connect(*socks)

    async def run():
        bot = Bot(config, "e1")
        base = bot.init()
        replies = [(await bot.ping(base, p))[0] for p in prompts]
        await bot.close(base)
        return replies

    with patch.object(wsc, "connect", connect):
        replies = asyncio.run(run())
    return replies, connect.calls


def test_ignore_when_skips_the_greeting_sent_after_the_first_message():
    # ElevenLabs: the greeting is triggered by the first user message and answers
    # nothing (in_response_to_ids == []); the real reply follows it
    sock = _FakeSocket([_META], replies={"hi": [_GREETING, _say("real answer", ["u1"])]})
    replies, _ = _conversation(_session_config(), [sock], ["hi"])
    assert replies == ["real answer"]


def test_without_ignore_when_the_greeting_is_taken_as_the_reply():
    # documents the bug seen against ElevenLabs
    sock = _FakeSocket([_META], replies={"hi": [_GREETING, _say("real answer", ["u1"])]})
    cfg = _session_config()
    del cfg["chat_completion"]["response"]["ignore_when"]
    replies, _ = _conversation(cfg, [sock], ["hi"])
    assert replies == ["Hello!"]


def test_keep_open_with_greeting_keeps_every_turn_aligned():
    sock = _FakeSocket(
        [_META],
        replies={
            "one": [_GREETING, _say("first", ["u1"])],
            "two": [_say("second", ["u2"])],
        },
        idle_close=False,
    )
    replies, calls = _conversation(_session_config(keep_open=True), [sock], ["one", "two"])
    assert replies == ["first", "second"]
    assert len(calls) == 1


def test_keep_open_uses_one_connection_for_the_whole_conversation():
    sock = _FakeSocket(
        [_META],
        replies={
            "one": [_GREETING, _say("first")],
            "two": [_say("second")],
            "three": [_say("third")],
        },
        idle_close=False,
    )
    cfg = _session_config(keep_open=True)
    replies, calls = _conversation(cfg, [sock], ["one", "two", "three"])
    assert replies == ["first", "second", "third"]
    assert len(calls) == 1  # one connection = one ElevenLabs conversation
    assert len(sock.sent) == 3
    assert sock.closed  # closed when the conversation ends


def test_without_keep_open_each_turn_opens_and_closes_a_connection():
    socks = [
        _FakeSocket([], replies={"one": [_say("first")]}),
        _FakeSocket([], replies={"two": [_say("second")]}),
    ]
    replies, calls = _conversation(_session_config(), socks, ["one", "two"])
    assert replies == ["first", "second"]
    assert len(calls) == 2
    assert all(s.closed for s in socks)


def test_keep_open_reconnects_when_the_agent_closed_the_connection():
    first = _FakeSocket([], replies={"one": [_say("first")]}, idle_close=False)
    second = _FakeSocket([], replies={"two": [_say("second")]}, idle_close=False)

    import websockets.asyncio.client as wsc

    connect = _fake_connect(first, second)

    async def run():
        bot = Bot(_session_config(keep_open=True), "e1")
        base = bot.init()
        out = [(await bot.ping(base, "one"))[0]]
        first.closed = True  # agent hung up between turns
        out.append((await bot.ping(base, "two"))[0])
        await bot.close(base)
        return out

    with patch.object(wsc, "connect", connect):
        assert asyncio.run(run()) == ["first", "second"]
    assert len(connect.calls) == 2


def test_keep_open_conversations_do_not_share_a_connection():
    a = _FakeSocket([], replies={"a": [_say("A")]}, idle_close=False)
    b = _FakeSocket([], replies={"b": [_say("B")]}, idle_close=False)

    import websockets.asyncio.client as wsc

    connect = _fake_connect(a, b)

    async def run():
        bot = Bot(_session_config(keep_open=True), "e1")
        one, two = bot.init(), bot.init()
        out = [(await bot.ping(one, "a"))[0], (await bot.ping(two, "b"))[0]]
        await bot.close(one)
        await bot.close(two)
        return out

    with patch.object(wsc, "connect", connect):
        assert asyncio.run(run()) == ["A", "B"]
    assert a.sent and b.sent and len(a.sent) == len(b.sent) == 1


def test_keep_open_falls_back_to_a_new_connection_on_another_event_loop():
    # callers that asyncio.run() each turn (e.g. the scope probe) still work
    import websockets.asyncio.client as wsc

    first = _FakeSocket([], replies={"one": [_say("first")]}, idle_close=False)
    second = _FakeSocket([], replies={"two": [_say("second")]}, idle_close=False)
    connect = _fake_connect(first, second)
    bot = Bot(_session_config(keep_open=True), "e1")
    base = bot.init()
    with patch.object(wsc, "connect", connect):
        assert asyncio.run(bot.ping(base, "one"))[0] == "first"
        assert asyncio.run(bot.ping(base, "two"))[0] == "second"
    assert len(connect.calls) == 2


def test_auto_reply_answers_pings_with_values_from_the_message():
    ping = {"type": "ping", "ping_event": {"event_id": 7, "ping_ms": 50}}
    sock = _FakeSocket([_META, ping], replies={"hi": [ping, _GREETING, _say("answer")]})
    cfg = _session_config(
        keep_open=True,
        auto_reply=[
            {"when": {"type": "ping"}, "send": {"type": "pong", "event_id": "$ping_event.event_id"}}
        ],
    )
    replies, _ = _conversation(cfg, [sock], ["hi"])
    import json as _json

    sent = [_json.loads(m) for m in sock.sent]
    assert replies == ["answer"]
    assert sent == [
        {"type": "user_message", "text": "hi"},
        {"type": "pong", "event_id": 7},  # the ping that came on connect
        {"type": "pong", "event_id": 7},  # the ping during the reply
    ]


@pytest.mark.parametrize(
    "ws, match",
    [
        ("yes", "websocket"),
        ({"keep_open": "yes"}, "keep_open"),
        ({"auto_reply": {"when": {}}}, "auto_reply"),
        ({"auto_reply": [{"when": {}, "send": {}}]}, "auto_reply"),
        ({"auto_reply": [{"when": {"type": "ping"}}]}, "auto_reply"),
    ],
)
def test_invalid_websocket_options_fail_clearly(ws, match):
    cfg = _ws_config()
    cfg["chat_completion"]["websocket"] = ws
    with pytest.raises(ValueError, match=match):
        Bot(cfg, "e1")
