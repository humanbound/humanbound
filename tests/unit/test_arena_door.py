# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the arena door (the way in to an agent and its only way out). Real sockets on
127.0.0.1; no Docker."""

import asyncio
import json

import pytest

from humanbound_cli.arena import door

LOCAL = "127.0.0.1"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def port_of(server) -> int:
    return server.sockets[0].getsockname()[1]


class Upstream:
    """A server that records what it got and answers like an HTTP server that closes."""

    def __init__(self, answer=b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"):
        self.answer = answer
        self.heads: list[bytes] = []
        self.server = None

    async def start(self) -> int:
        async def handle(reader, writer):
            self.heads.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(self.answer)
            await writer.drain()
            writer.close()

        self.server = await asyncio.start_server(handle, LOCAL, 0)
        return port_of(self.server)


class Echo:
    """A server that sends back whatever it gets, until the caller stops sending."""

    async def start(self) -> int:
        async def handle(reader, writer):
            while data := await reader.read(1024):
                writer.write(data)
                await writer.drain()
            writer.close()

        self.server = await asyncio.start_server(handle, LOCAL, 0)
        return port_of(self.server)


async def doors(allow, target=(LOCAL, 9), **kwargs):
    way_in, way_out = await door.serve(target, allow, host=LOCAL, in_port=0, out_port=0, **kwargs)
    return port_of(way_in), port_of(way_out)


async def ask(port: int, data: bytes, *, more: bytes | None = None) -> bytes:
    """Send `data` (then, after the first answer, `more`) and read until the other side
    closes."""
    reader, writer = await asyncio.open_connection(LOCAL, port)
    writer.write(data)
    await writer.drain()
    got = b""
    if more is not None:
        got = await reader.readuntil(b"\r\n\r\n")
        writer.write(more)
        await writer.drain()
        writer.write_eof()
    got += await reader.read()
    writer.close()
    return got


# ── settings ──


def test_parse_allow_reads_hosts_ports_and_private():
    text = json.dumps(
        [
            {"host": "API.OpenAI.com.", "port": 443, "private": True},
            {"host": "files.example.com", "port": 8443, "private": False},
            {"host": "other.example.com", "port": 443},
        ]
    )
    assert door.parse_allow(text) == {
        ("api.openai.com", 443): True,
        ("files.example.com", 8443): False,
        ("other.example.com", 443): False,
    }
    assert door.parse_allow("") == {}


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        '["api.example.com"]',
        '[{"port": 443}]',
        '[{"host": " ", "port": 443}]',
        '[{"host": "a.example.com"}]',
        '[{"host": "a.example.com", "port": "443"}]',
        '[{"host": "a.example.com", "port": true}]',
        '[{"host": "a.example.com", "port": 0}]',
        '[{"host": "a.example.com", "port": 65536}]',
        "not json",
    ],
)
def test_parse_allow_refuses_anything_else(text):
    with pytest.raises(ValueError):
        door.parse_allow(text)


@pytest.mark.parametrize(
    ("text", "default", "expected"),
    [
        ("api.example.com:443", None, ("api.example.com", 443)),
        ("API.Example.COM.:8443", None, ("api.example.com", 8443)),
        ("api.example.com", 80, ("api.example.com", 80)),
        ("[::1]:8080", None, ("::1", 8080)),
        ("[2001:db8::1]", 443, ("2001:db8::1", 443)),
        ("api.example.com", None, None),
        ("api.example.com:", None, None),
        ("api.example.com:0", None, None),
        ("api.example.com:65536", None, None),
        ("api.example.com:44a", None, None),
        ("api.example.com:٤٤٣", None, None),
        ("2001:db8::1", 443, None),
        ("[::1", 443, None),
        ("[::1]8080", None, None),
        (":443", None, None),
        ("", 443, None),
    ],
)
def test_split_host_port(text, default, expected):
    assert door.split_host_port(text, default) == expected


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "1.1.1.1", "2606:4700:4700::1111", "::ffff:1.1.1.1"]
)
def test_public_addresses(address):
    assert door.is_public(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.17.0.1",
        "192.168.1.10",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1%eth0",
        "fd00::1",
        "::ffff:10.0.0.5",
        "::ffff:127.0.0.1",
        "not an address",
        "",
    ],
)
def test_addresses_that_are_not_public(address):
    assert not door.is_public(address)


# ── in ──


def test_the_way_in_forwards_to_the_agent_and_back():
    async def scenario():
        agent = Upstream()
        in_port, _ = await doors({}, target=(LOCAL, await agent.start()))
        answer = await ask(in_port, b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
        return agent.heads, answer

    heads, answer = run(scenario())
    assert heads == [b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n"]
    assert answer.endswith(b"\r\n\r\nok")


def test_the_way_in_drops_the_call_while_the_agent_is_down():
    async def scenario():
        in_port, _ = await doors({}, target=(LOCAL, 9))
        return await ask(in_port, b"GET / HTTP/1.1\r\n\r\n")

    assert run(scenario()) == b""


# ── out ──


def test_connect_to_an_allowed_destination_opens_a_tunnel():
    async def scenario():
        far = Echo()
        far_port = await far.start()
        _, out_port = await doors({("localhost", far_port): True})
        head = f"CONNECT localhost:{far_port} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
        return await ask(out_port, head, more=b"through the tunnel")

    answer = run(scenario())
    assert answer == b"HTTP/1.1 200 Connection established\r\n\r\nthrough the tunnel"


def test_connect_matches_the_host_whatever_its_case_or_trailing_dot():
    async def scenario():
        far = Echo()
        far_port = await far.start()
        _, out_port = await doors({("localhost", far_port): True})
        head = f"CONNECT LocalHost.:{far_port} HTTP/1.1\r\n\r\n".encode()
        return await ask(out_port, head, more=b"x")

    assert run(scenario()).startswith(b"HTTP/1.1 200 ")


def refused(answer: bytes, status: bytes) -> str:
    head, _, body = answer.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 " + status), answer
    assert b"X-Arena-Egress: blocked" in head
    assert b"Connection: close" in head
    assert f"Content-Length: {len(body)}".encode() in head
    return body.decode()


def test_connect_to_anything_else_is_refused_and_never_attempted(capsys):
    contacted = []

    async def connect(host, port):
        contacted.append((host, port))
        raise OSError

    async def scenario():
        _, out_port = await doors({("api.example.com", 443): False}, connect=connect)
        return await ask(out_port, b"CONNECT evil.example.net:443 HTTP/1.1\r\n\r\n")

    body = refused(run(scenario()), b"403")
    assert "may not reach evil.example.net:443" in body
    assert "api.example.com:443" in body
    assert contacted == []
    assert "blocked evil.example.net:443" in capsys.readouterr().out


@pytest.mark.parametrize(
    "target",
    [
        "api.example.com:8443",  # the right host, another port
        "api.example.com.evil.net:443",
        "xapi.example.com:443",
        "host.docker.internal:443",
        "127.0.0.1:443",
        "[::1]:443",
    ],
)
def test_only_the_exact_host_and_port_pass(target):
    async def scenario():
        _, out_port = await doors({("api.example.com", 443): False})
        return await ask(out_port, f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())

    refused(run(scenario()), b"403")


def test_with_nothing_allowed_everything_is_refused():
    async def scenario():
        _, out_port = await doors({})
        return await ask(out_port, b"CONNECT api.openai.com:443 HTTP/1.1\r\n\r\n")

    assert "it may reach: nothing" in refused(run(scenario()), b"403")


def test_a_manifest_destination_that_resolves_to_a_private_address_is_refused(capsys):
    async def scenario():
        far = Echo()
        far_port = await far.start()
        _, out_port = await doors({("localhost", far_port): False})  # resolves to 127.0.0.1
        return await ask(out_port, f"CONNECT localhost:{far_port} HTTP/1.1\r\n\r\n".encode())

    assert "private address" in refused(run(scenario()), b"403")
    assert "resolves to a private address" in capsys.readouterr().out


def test_the_door_connects_to_the_address_it_checked():
    """Resolved once: the address that passed the check is the one connected to."""
    connected = []

    async def resolver(host, port, private_ok):
        return ["93.184.216.34"]

    async def scenario():
        far = Echo()
        far_port = await far.start()

        async def connect(host, port):
            connected.append((host, port))
            return await asyncio.open_connection(LOCAL, far_port)

        _, out_port = await doors(
            {("api.example.com", 443): False}, resolver=resolver, connect=connect
        )
        return await ask(out_port, b"CONNECT api.example.com:443 HTTP/1.1\r\n\r\n", more=b"x")

    assert run(scenario()).startswith(b"HTTP/1.1 200 ")
    assert connected == [("93.184.216.34", 443)]


def test_a_name_that_does_not_resolve_is_a_bad_gateway():
    async def resolver(host, port, private_ok):
        raise OSError("no such name")

    async def scenario():
        _, out_port = await doors({("api.example.com", 443): False}, resolver=resolver)
        return await ask(out_port, b"CONNECT api.example.com:443 HTTP/1.1\r\n\r\n")

    assert "does not resolve" in refused(run(scenario()), b"502")


def test_a_destination_that_does_not_answer_is_a_bad_gateway():
    async def scenario():
        _, out_port = await doors({("localhost", 9): True})
        return await ask(out_port, b"CONNECT localhost:9 HTTP/1.1\r\n\r\n")

    assert "could not connect" in refused(run(scenario()), b"502")


def test_plain_http_reaches_the_destination_as_one_ordinary_request():
    async def scenario():
        far = Upstream()
        far_port = await far.start()
        _, out_port = await doors({("localhost", far_port): True})
        request = (
            f"POST http://localhost:{far_port}/v1/chat/completions?x=1 HTTP/1.1\r\n"
            f"Host: localhost:{far_port}\r\n"
            "Proxy-Connection: keep-alive\r\n"
            "Proxy-Authorization: Basic abc\r\n"
            "Connection: keep-alive\r\n"
            "Content-Length: 2\r\n\r\n{}"
        ).encode()
        return far_port, far.heads, await ask(out_port, request)

    far_port, heads, answer = run(scenario())
    assert answer.endswith(b"\r\n\r\nok")
    assert heads == [
        (
            "POST /v1/chat/completions?x=1 HTTP/1.1\r\n"
            f"Host: localhost:{far_port}\r\n"
            "Content-Length: 2\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
    ]


def test_plain_http_without_a_path_asks_for_the_root():
    async def scenario():
        far = Upstream()
        far_port = await far.start()
        _, out_port = await doors({("localhost", far_port): True})
        await ask(out_port, f"GET http://localhost:{far_port} HTTP/1.1\r\n\r\n".encode())
        return far.heads

    assert run(scenario())[0].startswith(b"GET / HTTP/1.1\r\n")


def test_plain_http_to_anything_else_is_refused():
    async def scenario():
        _, out_port = await doors({("api.example.com", 443): False})
        return await ask(out_port, b"GET http://evil.example.net/x HTTP/1.1\r\n\r\n")

    assert "may not reach evil.example.net:80" in refused(run(scenario()), b"403")


@pytest.mark.parametrize(
    "request_head",
    [
        b"GET / HTTP/1.1\r\nHost: api.example.com\r\n\r\n",  # not a proxy request
        b"GET https://api.example.com/ HTTP/1.1\r\n\r\n",
        b"GET ftp://api.example.com/ HTTP/1.1\r\n\r\n",
        b"GET http://api.example.com:99999/ HTTP/1.1\r\n\r\n",
        b"CONNECT api.example.com HTTP/1.1\r\n\r\n",
        b"CONNECT api.example.com:443\r\n\r\n",
        b"CONNECT api.example.com:443 HTTP/2\r\n\r\n",
        b"\xff\xfe nonsense\r\n\r\n",
        b"\r\n\r\n",
    ],
)
def test_what_the_door_does_not_understand_is_refused(request_head):
    async def scenario():
        _, out_port = await doors({("api.example.com", 443): True})
        return await ask(out_port, request_head)

    refused(run(scenario()), b"400")


def test_an_endless_request_head_is_dropped():
    async def scenario():
        _, out_port = await doors({("api.example.com", 443): True})
        try:
            return await ask(
                out_port, b"CONNECT api.example.com:443 HTTP/1.1\r\nX: " + b"a" * 200_000
            )
        except (ConnectionResetError, BrokenPipeError):
            return b""  # dropped with data still unread

    assert run(scenario()) == b""


# ── the program ──


def test_the_program_refuses_to_start_without_a_target(monkeypatch, capsys):
    monkeypatch.delenv("DOOR_TARGET", raising=False)
    assert door.main() == 2
    assert "DOOR_TARGET must be host:port" in capsys.readouterr().err


def test_the_program_refuses_a_broken_allow_list(monkeypatch, capsys):
    monkeypatch.setenv("DOOR_TARGET", "agent:8080")
    monkeypatch.setenv("DOOR_ALLOW", "{}")
    assert door.main() == 2
    assert "DOOR_ALLOW must be a JSON list" in capsys.readouterr().err


def test_the_program_uses_the_standard_library_only():
    """It runs as `python -c <source>` in a stock Python image."""
    import ast
    import sys
    from pathlib import Path

    tree = ast.parse(Path(door.__file__).read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            modules.add((node.module or "").split(".")[0])
    assert modules <= set(sys.stdlib_module_names)
