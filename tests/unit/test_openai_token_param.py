# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The OpenAI pinger adapts its request to reasoning models (o-series, gpt-5)."""

from unittest.mock import MagicMock, patch

from humanbound_cli.engine.llm import openai as openai_llm

# Error bodies OpenAI returns to reasoning models, as quoted in public bug reports
# (e.g. rcourtman/Pulse#1837 for gpt-5.6-luna, agno-agi/agno#9951 for gpt-5-mini).
UNSUPPORTED_MAX_TOKENS = (
    '{"error": {"message": "Unsupported parameter: \'max_tokens\' is not supported with '
    'this model. Use \'max_completion_tokens\' instead.", "type": "invalid_request_error", '
    '"param": "max_tokens", "code": "unsupported_parameter"}}'
)
UNSUPPORTED_TEMPERATURE = (
    '{"error": {"message": "Unsupported value: \'temperature\' does not support 0 with this '
    'model. Only the default (1) value is supported.", "type": "invalid_request_error", '
    '"param": "temperature", "code": "unsupported_value"}}'
)


def _resp(status, text="", content="hello"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


def _pinger():
    return openai_llm.LLMPinger(
        {"name": "x", "integration": {"api_key": "sk-test", "model": "o4-mini"}}
    )


def _token_keys(post):
    return [
        [k for k in c.kwargs["json"] if k in ("max_tokens", "max_completion_tokens")]
        for c in post.call_args_list
    ]


def test_switches_to_max_completion_tokens_and_retries():
    pinger = _pinger()
    responses = [_resp(400, UNSUPPORTED_MAX_TOKENS), _resp(200)]
    with patch("requests.post", side_effect=responses) as post:
        assert pinger.ping("sys", "user", max_tokens=100) == "hello"
    assert _token_keys(post) == [["max_tokens"], ["max_completion_tokens"]]
    assert post.call_args_list[1].kwargs["json"]["max_completion_tokens"] == 100


def test_switch_is_kept_for_later_calls():
    pinger = _pinger()
    responses = [_resp(400, UNSUPPORTED_MAX_TOKENS), _resp(200), _resp(200)]
    with patch("requests.post", side_effect=responses) as post:
        pinger.ping("sys", "user")
        pinger.ping("sys", "user")
    assert _token_keys(post) == [
        ["max_tokens"],
        ["max_completion_tokens"],
        ["max_completion_tokens"],
    ]


def test_other_400_is_not_retried():
    pinger = _pinger()
    with patch("requests.post", side_effect=[_resp(400, "content policy")]) as post:
        try:
            pinger.ping("sys", "user")
        except Exception as e:  # noqa: BLE001
            assert "content policy" in str(e)
        else:
            raise AssertionError("expected an exception")
    assert post.call_count == 1
    assert pinger.token_param == "max_tokens"


def test_second_rejection_does_not_loop():
    pinger = _pinger()
    responses = [_resp(400, UNSUPPORTED_MAX_TOKENS), _resp(400, UNSUPPORTED_MAX_TOKENS)]
    with patch("requests.post", side_effect=responses) as post:
        try:
            pinger.ping("sys", "user")
        except Exception:  # noqa: BLE001
            pass
        else:
            raise AssertionError("expected an exception")
    assert post.call_count == 2


def test_drops_temperature_and_retries():
    pinger = _pinger()
    responses = [_resp(400, UNSUPPORTED_TEMPERATURE), _resp(200)]
    with patch("requests.post", side_effect=responses) as post:
        assert pinger.ping("sys", "user", temperature=0) == "hello"
    sent = [c.kwargs["json"] for c in post.call_args_list]
    assert sent[0]["temperature"] == 0
    assert "temperature" not in sent[1]


def test_reasoning_model_needs_both_fixes_then_remembers_them():
    pinger = _pinger()
    responses = [
        _resp(400, UNSUPPORTED_MAX_TOKENS),
        _resp(400, UNSUPPORTED_TEMPERATURE),
        _resp(200),
        _resp(200),
    ]
    with patch("requests.post", side_effect=responses) as post:
        assert pinger.ping("sys", "user", temperature=0) == "hello"
        assert pinger.ping("sys", "user", temperature=0) == "hello"
    assert post.call_count == 4
    last = post.call_args_list[-1].kwargs["json"]
    assert "max_completion_tokens" in last and "max_tokens" not in last
    assert "temperature" not in last


def test_older_models_are_unchanged():
    pinger = _pinger()
    with patch("requests.post", side_effect=[_resp(200)]) as post:
        pinger.ping("sys", "user", max_tokens=100, temperature=0)
    sent = post.call_args.kwargs["json"]
    assert sent["max_tokens"] == 100 and sent["temperature"] == 0
    assert "max_completion_tokens" not in sent
