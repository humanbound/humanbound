# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""pull → run → A2A + OpenAI → reset → stop against real Docker.

Opt-in: HB_ARENA_DOCKER_TESTS=1 python -m pytest tests/unit/test_arena_e2e_docker.py -v
"""

import os
import socket
import subprocess

import httpx
import pytest
from click.testing import CliRunner
from conftest import ARENA_FIXTURES

from humanbound_cli.main import cli

pytestmark = [
    pytest.mark.docker,
    pytest.mark.timeout(300),
    pytest.mark.skipif(
        os.environ.get("HB_ARENA_DOCKER_TESTS") != "1", reason="set HB_ARENA_DOCKER_TESTS=1"
    ),
]

CATALOG = ARENA_FIXTURES / "catalog"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def e2e_env(arena_home, monkeypatch):
    subprocess.run(
        ["docker", "build", "-t", "humanbound-arena-echo:test", str(CATALOG / "agents" / "echo")],
        check=True,
    )
    port = _free_port()
    monkeypatch.setenv("HB_ARENA_INDEX", str(CATALOG))
    monkeypatch.setenv("HB_ARENA_PORT", str(port))
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        CliRunner().invoke(cli, ["arena", "stop", "--all"])


def test_full_lifecycle(e2e_env):
    runner = CliRunner()
    result = runner.invoke(cli, ["arena", "run", "echo"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    card = httpx.get(f"{e2e_env}/a2a/echo/.well-known/agent-card.json").json()
    assert card["name"] == "Echo"

    def send(text, ctx):
        return httpx.post(
            f"{e2e_env}/a2a/echo",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": "ROLE_USER",
                        "messageId": "m",
                        "contextId": ctx,
                        "parts": [{"text": text}],
                    }
                },
            },
            timeout=30,
        ).json()

    first = send("hello", "c-1")
    assert first["result"]["message"]["parts"][0]["text"] == "echo: hello"

    chat = httpx.post(
        f"{e2e_env}/v1/chat/completions",
        json={"model": "arena/echo", "messages": [{"role": "user", "content": "hi"}]},
        timeout=30,
    ).json()
    assert chat["choices"][0]["message"]["content"] == "echo: hi"

    assert runner.invoke(cli, ["arena", "reset", "echo"]).exit_code == 0
    assert (
        send("after reset", "c-1")["result"]["message"]["parts"][0]["text"] == "echo: after reset"
    )

    assert runner.invoke(cli, ["arena", "stop", "echo"]).exit_code == 0
    assert runner.invoke(cli, ["arena", "ps"]).output.strip().endswith("No arena agents running.")
