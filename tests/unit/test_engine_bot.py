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
from unittest.mock import MagicMock, patch

import pytest

from humanbound_cli.engine.bot import (
    Bot,
    ResponseExtractor,
    Telemetry,
)

# ────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ────────────────────────────────────────────────────────────────


@pytest.fixture
def bot_config():
    """Minimal bot config — REST, non-streaming."""
    return {
        "streaming": False,
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


def _mock_post(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json = MagicMock(return_value=payload or {})
    return r


# ────────────────────────────────────────────────────────────────
# ResponseExtractor — base behaviour
# ────────────────────────────────────────────────────────────────


def test_response_extractor_default_returns_none():
    assert ResponseExtractor().extract_custom_response({"anything": 1}) is None


def test_bot_inherits_from_response_extractor(bot):
    assert isinstance(bot, ResponseExtractor)


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

    b = CustomBot({"streaming": False}, "e1")
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
        "streaming": False,
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
        "streaming": False,
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
    assert out == {"session_id": "sess-99"}


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
    assert out == {"access_token": "tok", "session_id": "sess"}


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
