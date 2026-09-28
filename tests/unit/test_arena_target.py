# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for `arena://` target resolution and the Bot↔gateway contract."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
import yaml
from starlette.testclient import TestClient

from humanbound_cli.agent_yaml import scope_from_agent_yaml
from humanbound_cli.arena import daemon, paths, runtime, target
from humanbound_cli.arena.gateway import create_app
from humanbound_cli.arena.manifest import ManifestError
from humanbound_cli.arena.runtime import DockerError, RunningAgent
from humanbound_cli.arena.target import (
    ARENA_SCHEME,
    ArenaTarget,
    TargetError,
    bot_config,
    is_arena_target,
    parse_target,
    reset_via_gateway,
    resolve_target,
)
from humanbound_cli.engine import bot as bot_module
from humanbound_cli.engine.bot import Bot, Telemetry

from .arena_testing import returns
from .test_arena_gateway import ECHO, NATIVE, PLAIN, FakeAgentState, FakeRegistry, fake_agent_app

GATEWAY = "http://127.0.0.1:11500"


@pytest.fixture(autouse=True)
def _isolated_home(arena_home):
    """bot_config and the gateway calls read (and create) the owner's token under HOME."""
    return arena_home


def _auth():
    return {"Authorization": f"Bearer {paths.gateway_token()}"}


# ── parsing ──


@pytest.mark.parametrize(
    "value, expected",
    [
        ("arena://echo", True),
        ("arena://", True),
        ("http://x", False),
        ("", False),
        (None, False),
        (42, False),
    ],
)
def test_is_arena_target(value, expected):
    result = is_arena_target(value)
    assert result is expected


def test_scheme():
    assert ARENA_SCHEME == "arena://"


def test_parse_target_ok():
    assert parse_target("arena://echo") == "echo"
    assert parse_target("arena://my-agent-2") == "my-agent-2"


@pytest.mark.parametrize(
    "value",
    [
        "arena://",
        "arena://Echo",
        "arena://-x",
        "arena://a/b",
        "http://echo",
        "echo",
        "arena://echo\n",
    ],
)
def test_parse_target_invalid(value):
    with pytest.raises(TargetError, match=r"invalid arena target .*expected arena://<agent-id>"):
        parse_target(value)


# ── bot_config ──


def test_bot_config_shape():
    assert bot_config("echo", GATEWAY) == {
        "streaming": None,
        "chat_completion": {
            "endpoint": "http://127.0.0.1:11500/a2a/echo",
            "headers": {"A2A-Version": "1.0", **_auth()},
            "payload": {
                "jsonrpc": "2.0",
                "id": "$UUID",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": "ROLE_USER",
                        "messageId": "$UUID",
                        "contextId": "$humanbound_conversation_id",
                        "parts": [{"text": "$PROMPT"}],
                    }
                },
            },
        },
        "telemetry": {
            "mode": "per_turn",
            "extraction_map": {
                "metadata_path": "result.message.metadata.humanbound",
                "tool_executions": "tool_calls",
            },
        },
    }


def test_bot_config_takes_an_explicit_token():
    headers = bot_config("echo", GATEWAY, token="abc")["chat_completion"]["headers"]
    assert headers["Authorization"] == "Bearer abc"


def test_bot_config_trailing_slash():
    assert bot_config("echo", GATEWAY + "/")["chat_completion"]["endpoint"] == (
        "http://127.0.0.1:11500/a2a/echo"
    )


def test_bot_config_is_fresh_each_call():
    a = bot_config("echo", GATEWAY)
    a["chat_completion"]["headers"]["X"] = "y"
    assert "X" not in bot_config("echo", GATEWAY)["chat_completion"]["headers"]


# ── resolve_target ──


def _installed_at(agent_dir, calls=None):
    def installed(agent_id, version=None):
        if calls is not None:
            calls.append((agent_id, version))
        return ECHO, agent_dir

    return installed


def test_resolve_target_success(tmp_path):
    agent_dir = tmp_path / "agents" / "echo" / "0.1.0"
    agent_dir.mkdir(parents=True)
    calls = []
    t = resolve_target(
        "arena://echo",
        list_running=returns(
            RunningAgent("other", "1.0.0", "image", 4000),
            RunningAgent("echo", "0.1.0", "image", 4001),
        ),
        installed=_installed_at(agent_dir, calls),
        ensure_gateway=lambda: GATEWAY,
    )
    assert isinstance(t, ArenaTarget)
    assert t.agent_id == "echo"
    assert t.gateway == GATEWAY
    assert t.bot_config == bot_config("echo", GATEWAY)
    assert t.scope_path == agent_dir / "scope.yaml"
    assert yaml.safe_load(t.scope_path.read_text()) == scope_from_agent_yaml(ECHO.agent_yaml())
    assert t.context == ECHO.context
    assert t.whitebox is True
    assert t.version == "0.1.0"
    assert t.default_catalog is False  # no record of where it came from
    assert calls == [("echo", "0.1.0")]
    # atomic write leaves no temp files behind
    assert sorted(p.name for p in agent_dir.iterdir()) == ["scope.yaml"]


@pytest.mark.parametrize("index, expected", [("default", True), ("/my/index.json", False)])
def test_resolve_target_knows_whether_the_agent_is_from_the_default_catalog(
    tmp_path, index, expected
):
    import json

    from humanbound_cli.arena import catalog, paths

    agent_dir = tmp_path / "agents" / "echo" / "0.1.0"
    agent_dir.mkdir(parents=True)
    location = paths.DEFAULT_INDEX_URL if index == "default" else index
    (agent_dir / catalog.PROVENANCE_FILE).write_text(json.dumps({"index": location, "images": []}))
    t = resolve_target(
        "arena://echo",
        list_running=returns(RunningAgent("echo", "0.1.0", "image", 4001)),
        installed=_installed_at(agent_dir),
        ensure_gateway=lambda: GATEWAY,
    )
    assert t.default_catalog is expected


@pytest.mark.parametrize(
    "manifest, whitebox",
    [(ECHO, True), (PLAIN, False), (NATIVE, False)],
    ids=["http-with-tool-calls", "http-without-tool-calls", "native-a2a"],
)
def test_resolve_target_whitebox_only_with_tool_calls(tmp_path, manifest, whitebox):
    t = resolve_target(
        f"arena://{manifest.id}",
        list_running=returns(RunningAgent(manifest.id, manifest.version, "image", 4001)),
        installed=lambda agent_id, version=None: (manifest, tmp_path),
        ensure_gateway=lambda: GATEWAY,
    )
    assert t.whitebox is whitebox
    # the engine picks whitebox categories from the telemetry block, so it must agree
    assert ("telemetry" in t.bot_config) is whitebox
    assert t.bot_config == bot_config(manifest.id, GATEWAY, whitebox=whitebox)


def test_bot_config_blackbox_has_no_telemetry():
    config = bot_config("echo", GATEWAY, whitebox=False)
    assert "telemetry" not in config
    assert config["chat_completion"] == bot_config("echo", GATEWAY)["chat_completion"]


def test_resolve_target_scope_write_is_atomic(tmp_path, monkeypatch):
    agent_dir = tmp_path / "echo"
    agent_dir.mkdir()
    (agent_dir / "scope.yaml").write_text("old: true\n")
    replaced = []
    real_replace = os.replace

    def spy_replace(src, dst):
        replaced.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(target.os, "replace", spy_replace)
    resolve_target(
        "arena://echo",
        list_running=returns(RunningAgent("echo", "0.1.0", "image", 4001)),
        installed=_installed_at(agent_dir),
        ensure_gateway=lambda: GATEWAY,
    )
    assert len(replaced) == 1
    src, dst = replaced[0]
    assert dst == str(agent_dir / "scope.yaml")
    assert os.path.dirname(src) == str(agent_dir)
    assert "old" not in (agent_dir / "scope.yaml").read_text()


def test_resolve_target_empty_version_passes_none(tmp_path):
    calls = []
    resolve_target(
        "arena://echo",
        list_running=returns(RunningAgent("echo", "", "image", 4001)),
        installed=_installed_at(tmp_path, calls),
        ensure_gateway=lambda: GATEWAY,
    )
    assert calls == [("echo", None)]


def test_resolve_target_not_running(tmp_path, arena_home):
    gateway_calls = []
    with pytest.raises(TargetError, match="echo is not running, and it is not installed"):
        resolve_target(
            "arena://echo",
            list_running=returns(RunningAgent("other", "1.0.0", "image", 4000)),
            installed=_installed_at(tmp_path),
            ensure_gateway=lambda: gateway_calls.append(1) or GATEWAY,
        )
    assert gateway_calls == []


def test_resolve_target_not_installed():
    with pytest.raises(TargetError, match="manifest isn't cached → hb arena pull echo"):
        resolve_target(
            "arena://echo",
            list_running=returns(RunningAgent("echo", "0.1.0", "image", 4001)),
            installed=lambda agent_id, version=None: None,
            ensure_gateway=lambda: GATEWAY,
        )


def test_resolve_target_invalid_value():
    with pytest.raises(TargetError, match="invalid arena target"):
        resolve_target("arena://Bad!", list_running=returns(), ensure_gateway=lambda: GATEWAY)


def test_resolve_target_wraps_docker_error():
    def boom():
        raise DockerError("Docker is installed but not running.")

    with pytest.raises(TargetError, match="Docker is installed but not running.") as e:
        resolve_target("arena://echo", list_running=boom, ensure_gateway=lambda: GATEWAY)
    assert isinstance(e.value.__cause__, runtime.DockerError)


def test_resolve_target_wraps_gateway_error(tmp_path):
    def boom():
        raise daemon.GatewayError("port 11500 is used; set HB_ARENA_PORT to a free port")

    with pytest.raises(TargetError, match="set HB_ARENA_PORT to a free port"):
        resolve_target(
            "arena://echo",
            list_running=returns(RunningAgent("echo", "0.1.0", "image", 4001)),
            installed=_installed_at(tmp_path),
            ensure_gateway=boom,
        )


def test_resolve_target_wraps_manifest_error():
    def installed(agent_id, version=None):
        raise ManifestError("invalid arena.yaml")

    with pytest.raises(TargetError, match="invalid arena.yaml"):
        resolve_target(
            "arena://echo",
            list_running=returns(RunningAgent("echo", "0.1.0", "image", 4001)),
            installed=installed,
            ensure_gateway=lambda: GATEWAY,
        )


# ── the container baseline before a test ──


def test_resolve_target_knows_how_to_stop_the_agent(tmp_path):
    agent_dir = tmp_path / "agents" / "echo" / "0.1.0"
    agent_dir.mkdir(parents=True)
    t = resolve_target(
        "arena://echo",
        list_running=returns(RunningAgent("echo", "0.1.0", "compose", 4001)),
        installed=_installed_at(agent_dir),
        ensure_gateway=lambda: GATEWAY,
    )
    assert (t.kind, t.agent_dir) == ("compose", agent_dir)


def _target(tmp_path, kind="image"):
    return ArenaTarget(
        agent_id="echo",
        gateway=GATEWAY,
        bot_config={},
        scope_path=tmp_path / "scope.yaml",
        context="",
        whitebox=False,
        version="0.1.0",
        kind=kind,
        agent_dir=tmp_path,
    )


def test_enforce_baseline_passes_quietly(tmp_path):
    stops = []
    target.enforce_baseline(
        _target(tmp_path), check=lambda agent_id: [], stop=lambda *a, **k: stops.append(a)
    )
    assert stops == []


def test_enforce_baseline_stops_the_agent_and_lists_the_violations(tmp_path):
    from humanbound_cli.arena.baseline import Violation

    violations = [
        Violation("arena-x-echo", "non-root", "runs as root (Config.User is 'root')"),
        Violation("arena-x-echo", "not-privileged", "runs privileged"),
    ]
    stops = []
    with pytest.raises(TargetError) as e:
        target.enforce_baseline(
            _target(tmp_path, "compose"),
            check=lambda agent_id: violations,
            stop=lambda *a, **k: stops.append((a, k)),
        )
    assert stops == [(("echo", "compose"), {"agent_dir": tmp_path})]
    lines = str(e.value).splitlines()
    assert "container baseline" in lines[0]
    assert lines[1:] == [str(v) for v in violations]


def test_enforce_baseline_refuses_even_when_stopping_fails(tmp_path):
    from humanbound_cli.arena.baseline import Violation

    def broken_stop(*args, **kwargs):
        raise DockerError("docker went away")

    with pytest.raises(TargetError, match="non-root"):
        target.enforce_baseline(
            _target(tmp_path),
            check=lambda agent_id: [Violation("c", "non-root", "runs as root")],
            stop=broken_stop,
        )


def test_enforce_baseline_that_cannot_run_refuses(tmp_path):
    def down(agent_id):
        raise DockerError("Docker is not running")

    with pytest.raises(TargetError, match="container baseline.*Docker is not running"):
        target.enforce_baseline(_target(tmp_path), check=down, stop=lambda *a, **k: None)


def test_enforce_baseline_defaults_to_the_runtime(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(runtime, "check_baseline", lambda agent_id: seen.append(agent_id) or [])
    target.enforce_baseline(_target(tmp_path))
    assert seen == ["echo"]


# ── reset_via_gateway ──


def _mock_post(monkeypatch, handler):
    seen = []
    transport = httpx.MockTransport(handler)

    def fake_post(url, **kwargs):
        seen.append((url, kwargs))
        with httpx.Client(transport=transport) as c:
            return c.post(url, json=kwargs.get("json"))

    monkeypatch.setattr(target.httpx, "post", fake_post)
    return seen


def test_reset_sends_empty_json(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append((request.headers["content-type"], request.content))
        return httpx.Response(200, json={"id": "echo", "status": "reset"})

    seen = _mock_post(monkeypatch, handler)
    reset_via_gateway("echo", GATEWAY)
    assert seen == [
        (
            f"{GATEWAY}/arena/v1/agents/echo/reset",
            {"json": {}, "headers": _auth(), "timeout": 300, "trust_env": False},
        )
    ]
    assert bodies == [("application/json", b"{}")]


def test_reset_error_uses_json_message(monkeypatch):
    _mock_post(
        monkeypatch,
        lambda r: httpx.Response(
            500, json={"error": {"code": "reset_failed", "message": "could not reset echo: x"}}
        ),
    )
    with pytest.raises(TargetError, match="^could not reset echo: x$"):
        reset_via_gateway("echo", GATEWAY)


def test_reset_error_falls_back_to_text(monkeypatch):
    _mock_post(monkeypatch, lambda r: httpx.Response(400, text="Invalid host header"))
    with pytest.raises(TargetError, match="Invalid host header"):
        reset_via_gateway("echo", GATEWAY)


def test_reset_error_json_without_message(monkeypatch):
    _mock_post(monkeypatch, lambda r: httpx.Response(502, json={"detail": "nope"}))
    with pytest.raises(TargetError, match="nope"):
        reset_via_gateway("echo", GATEWAY)


def test_reset_transport_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _mock_post(monkeypatch, handler)
    with pytest.raises(TargetError, match="connection refused"):
        reset_via_gateway("echo", GATEWAY)


def test_reset_against_real_gateway_app(monkeypatch):
    """The real gateway accepts the reset POST (JSON content type, loopback host)."""
    resets = []
    app = create_app(
        FakeRegistry([ECHO]),
        transport=httpx.ASGITransport(app=fake_agent_app(FakeAgentState())),
        reset_agent=lambda m, d: resets.append(m.id),
        allowed_hosts=["testserver"],
    )
    with TestClient(app) as client:

        def fake_post(url, **kwargs):
            return client.post(
                url, **{k: v for k, v in kwargs.items() if k not in ("timeout", "trust_env")}
            )

        monkeypatch.setattr(target.httpx, "post", fake_post)
        reset_via_gateway("echo", "http://testserver")
        with pytest.raises(TargetError, match="ghost is not running, and it is not installed"):
            reset_via_gateway("ghost", "http://testserver")
    assert resets == ["echo"]


# ── the Bot↔gateway contract ──


def test_bot_talks_to_gateway(monkeypatch):
    app = create_app(
        FakeRegistry([ECHO]),
        transport=httpx.ASGITransport(app=fake_agent_app(FakeAgentState())),
        allowed_hosts=["testserver"],
    )
    requests_seen = []
    with TestClient(app) as client:

        def fake_post(url, headers=None, json=None, timeout=None, allow_redirects=True):
            requests_seen.append((url, headers, json))
            return client.post(url, headers=headers, json=json, follow_redirects=allow_redirects)

        monkeypatch.setattr(bot_module.requests, "post", fake_post)
        bot = Bot(bot_config("echo", "http://testserver"), "e1")
        base = bot.init()
        text1, _, meta1 = asyncio.run(bot.ping(base, "one"))
        text2, _, meta2 = asyncio.run(bot.ping(base, "two"))

    assert text1 == "echo: one (0 before)"
    assert text2 == "echo: two (2 before)"

    assert [url for url, _, _ in requests_seen] == ["http://testserver/a2a/echo"] * 2
    assert all(h["A2A-Version"] == "1.0" for _, h, _ in requests_seen)
    context_ids = {body["params"]["message"]["contextId"] for _, _, body in requests_seen}
    assert context_ids == {base["humanbound_conversation_id"]}
    rpc_ids = [body["id"] for _, _, body in requests_seen]
    message_ids = [body["params"]["message"]["messageId"] for _, _, body in requests_seen]
    assert len(set(rpc_ids + message_ids)) == 4  # $UUID is fresh at each occurrence

    for meta in (meta1, meta2):
        assert meta["tool_calls"] == [{"name": "echo", "parameters": {}, "result": ""}]
        assert meta["agent"] == "echo"


def test_gateway_metadata_standardizes_to_tool_executions():
    gateway_metadata = {
        "latency_ms": 3,
        "agent": "echo",
        "version": "0.1.0",
        "tool_calls": [{"name": "echo"}],
    }
    extraction_map = bot_config("echo", GATEWAY)["telemetry"]["extraction_map"]
    out = Telemetry.standardize_accumulated_metadata(
        [{"turn": 1, "metadata": gateway_metadata}], extraction_map
    )
    assert len(out["tool_executions"]) == 1
    assert out["tool_executions"][0]["tool_name"] == "echo"
    assert out["tool_executions"][0]["turn"] == 1


def test_resolve_target_wraps_value_error(tmp_path):
    def bad_port():
        raise ValueError("HB_ARENA_PORT must be a port number between 1 and 65535, got '0'")

    with pytest.raises(TargetError, match="HB_ARENA_PORT must be a port number"):
        resolve_target(
            "arena://echo",
            list_running=returns(RunningAgent("echo", "0.1.0", "image", 4001)),
            installed=_installed_at(tmp_path),
            ensure_gateway=bad_port,
        )


# ── forget_via_gateway ──


def test_forget_posts_empty_json_without_proxies(monkeypatch):
    seen = _mock_post(monkeypatch, lambda r: httpx.Response(200, json={"status": "forgotten"}))
    target.forget_via_gateway("echo", GATEWAY)
    assert seen == [
        (
            f"{GATEWAY}/arena/v1/agents/echo/forget",
            {"json": {}, "headers": _auth(), "timeout": 10, "trust_env": False},
        )
    ]


def test_forget_errors_become_target_error(monkeypatch):
    _mock_post(monkeypatch, lambda r: httpx.Response(500, json={"error": {"message": "x"}}))
    with pytest.raises(TargetError, match="x"):
        target.forget_via_gateway("echo", GATEWAY)

    def handler(request):
        raise httpx.ConnectError("refused")

    _mock_post(monkeypatch, handler)
    with pytest.raises(TargetError, match="refused"):
        target.forget_via_gateway("echo", GATEWAY)
