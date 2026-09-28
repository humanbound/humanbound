# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The door: the way in to an arena agent, and its only way out.

An agent's networks have no route out, and no port of theirs can be published. hb runs this
program in a small container of its own that sits on the agent's networks and on one
ordinary network, and does two things:

  in   forwards connections from the published port (127.0.0.1 on the host) to the agent;
  out  is an HTTP proxy that lets through the destinations in DOOR_ALLOW and refuses
       everything else with 403.

It runs as `python -c <this file>` in a stock Python image, so it uses the standard library
only and imports nothing from hb.

Settings (environment):
  DOOR_TARGET  host:port of the agent, as seen from its network
  DOOR_ALLOW   JSON list of {"host", "port", "private"}; with "private" false the
               destination must resolve to a public address

Limits: only traffic of clients that use the proxy passes; an allowed destination is still a
way out; this is a filter on host name and port, not an inspection of what is sent.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import signal
import socket
import sys
from urllib.parse import urlsplit

IN_PORT = 8080
OUT_PORT = 3128
HEAD_LIMIT = 64 * 1024
HEAD_TIMEOUT_S = 15.0
CONNECT_TIMEOUT_S = 15.0
CHUNK = 64 * 1024
GRACE_S = 2.0
# Headers that are about the connection to the proxy, not for the destination.
HOP_HEADERS = frozenset(
    {"connection", "keep-alive", "proxy-connection", "proxy-authorization", "proxy-authenticate"}
)


def log(message: str) -> None:
    print(message, flush=True)


# ── settings ──


def clean_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def parse_allow(text: str) -> dict[tuple[str, int], bool]:
    """{(host, port): may it resolve to a private address}. Raises ValueError."""
    data = json.loads(text or "[]")
    if not isinstance(data, list):
        raise ValueError("DOOR_ALLOW must be a JSON list")
    allow: dict[tuple[str, int], bool] = {}
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("DOOR_ALLOW entries must be objects")
        host, port = item.get("host"), item.get("port")
        if not isinstance(host, str) or not clean_host(host):
            raise ValueError("DOOR_ALLOW: an entry has no host")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"DOOR_ALLOW: {host} has no valid port")
        allow[(clean_host(host), port)] = item.get("private") is True
    return allow


def split_host_port(text: str, default: int | None = None) -> tuple[str, int] | None:
    """(host, port) of "host:port", "[v6]:port" or, with a default port, "host"."""
    text = text.strip()
    if text.startswith("["):
        host, sep, rest = text[1:].partition("]")
        if not sep or (rest and not rest.startswith(":")):
            return None
        port_text = rest[1:]
    elif text.count(":") == 1:
        host, _, port_text = text.partition(":")
    elif ":" in text:
        return None
    else:
        host, port_text = text, ""
    if not port_text:
        port = default
    elif port_text.isascii() and port_text.isdigit() and len(port_text) <= 5:
        port = int(port_text)
    else:
        return None
    host = clean_host(host)
    if not host or port is None or not 1 <= port <= 65535:
        return None
    return host, port


def is_public(address: str) -> bool:
    """A public internet address: not loopback, private, link-local or otherwise special."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


# ── plumbing ──


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy until the reader ends, then tell the writer's side that no more is coming."""
    try:
        while data := await reader.read(CHUNK):
            writer.write(data)
            await writer.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except (OSError, RuntimeError):
            pass


async def close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
        await writer.wait_closed()
    except (OSError, RuntimeError, asyncio.CancelledError):
        pass


async def join(
    near_reader: asyncio.StreamReader,
    near_writer: asyncio.StreamWriter,
    far_reader: asyncio.StreamReader,
    far_writer: asyncio.StreamWriter,
) -> None:
    """Copy both ways between the side that called (near) and the side it called (far).
    Done when the far side has nothing more to send: the near side may stop sending first
    and still get the whole answer."""
    sending = asyncio.ensure_future(pipe(near_reader, far_writer))
    try:
        await pipe(far_reader, near_writer)
        await asyncio.wait({sending}, timeout=GRACE_S)
    finally:
        sending.cancel()
        await close(near_writer)
        await close(far_writer)


async def open_to(host: str, port: int):
    return await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT_S)


# ── in: the host's published port → the agent ──


def inbound(target: tuple[str, int]):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            up_reader, up_writer = await open_to(*target)
        except (OSError, asyncio.TimeoutError):
            await close(writer)  # the agent is not up (yet): the caller sees a dropped call
            return
        await join(reader, writer, up_reader, up_writer)

    return handle


# ── out: the agent → an allowed destination ──


def refusal(status: str, message: str) -> bytes:
    body = f"hb arena: {message}\n".encode()
    head = (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "X-Arena-Egress: blocked\r\n"
        "Connection: close\r\n\r\n"
    )
    return head.encode("ascii") + body


def parse_head(head: bytes) -> tuple[str, str, str, list[bytes]] | None:
    """(method, target, version, header lines) of a request head, or None."""
    lines = head.split(b"\r\n")
    try:
        method, target, version = lines[0].decode("ascii").split(" ")
    except (UnicodeDecodeError, ValueError):
        return None
    if not method or not target or not version.startswith("HTTP/1."):
        return None
    return method, target, version, [line for line in lines[1:] if line]


def origin_request(method: str, url_path: str, headers: list[bytes]) -> bytes:
    """The request as the destination gets it: origin form, one request per connection."""
    kept = [h for h in headers if h.split(b":", 1)[0].strip().lower().decode("latin-1")
            not in HOP_HEADERS]  # fmt: skip
    lines = [f"{method} {url_path} HTTP/1.1".encode("ascii"), *kept, b"Connection: close"]
    return b"\r\n".join(lines) + b"\r\n\r\n"


async def resolve(host: str, port: int, private_ok: bool) -> list[str]:
    """The addresses of `host` the door may connect to (public ones only, unless the
    destination may be private). Raises OSError when the name does not resolve."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    return [a for a in addresses if private_ok or is_public(a)]


def outbound(allow: dict[tuple[str, int], bool], *, resolver=resolve, connect=open_to):
    names = ", ".join(f"{h}:{p}" for h, p in allow) or "nothing"

    async def refuse(writer: asyncio.StreamWriter, status: str, message: str) -> None:
        try:
            writer.write(refusal(status, message))
            await writer.drain()
        except OSError:
            pass
        await close(writer)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT_S)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            await close(writer)
            return
        except OSError:
            await close(writer)
            return
        parsed = parse_head(head[:-4])
        if parsed is None:
            await refuse(writer, "400 Bad Request", "not a request the door understands")
            return
        method, target, _version, headers = parsed
        tunnel = method.upper() == "CONNECT"
        if tunnel:
            where = split_host_port(target)
            path = ""
        else:
            try:
                url = urlsplit(target)
                plain = url.scheme.lower() == "http" and bool(url.hostname)
                where = (clean_host(url.hostname), url.port or 80) if plain else None
            except ValueError:
                where = None
            path = ""
            if where is not None:
                path = (url.path or "/") + (f"?{url.query}" if url.query else "")
        if where is None:
            await refuse(writer, "400 Bad Request", "not a request the door understands")
            return
        host, port = where
        if where not in allow:
            log(f"blocked {host}:{port}")
            await refuse(
                writer,
                "403 Forbidden",
                f"this agent may not reach {host}:{port} (it may reach: {names})",
            )
            return
        try:
            addresses = await resolver(host, port, allow[where])
        except OSError:
            log(f"failed {host}:{port} (the name does not resolve)")
            await refuse(writer, "502 Bad Gateway", f"{host} does not resolve")
            return
        if not addresses:
            log(f"blocked {host}:{port} (it resolves to a private address)")
            await refuse(
                writer, "403 Forbidden", f"{host} resolves to a private address, not allowed"
            )
            return
        upstream = None
        for address in addresses:
            try:
                upstream = await connect(address, port)
                break
            except (OSError, asyncio.TimeoutError):
                continue
        if upstream is None:
            log(f"failed {host}:{port} (no connection)")
            await refuse(writer, "502 Bad Gateway", f"could not connect to {host}:{port}")
            return
        up_reader, up_writer = upstream
        log(f"allowed {host}:{port}")
        try:
            if tunnel:
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                up_writer.write(origin_request(method, path, headers))
                await up_writer.drain()
        except OSError:
            await close(writer)
            await close(up_writer)
            return
        await join(reader, writer, up_reader, up_writer)

    return handle


# ── the program ──


async def serve(
    target: tuple[str, int],
    allow: dict[tuple[str, int], bool],
    *,
    host: str = "0.0.0.0",  # noqa: S104 - inside the door's container; only IN_PORT is published
    in_port: int = IN_PORT,
    out_port: int = OUT_PORT,
    resolver=resolve,
    connect=open_to,
) -> tuple[asyncio.AbstractServer, asyncio.AbstractServer]:
    way_in = await asyncio.start_server(inbound(target), host, in_port)
    way_out = await asyncio.start_server(
        outbound(allow, resolver=resolver, connect=connect), host, out_port, limit=HEAD_LIMIT
    )
    return way_in, way_out


async def run() -> None:
    target = split_host_port(os.environ.get("DOOR_TARGET", ""))
    if target is None:
        raise ValueError("DOOR_TARGET must be host:port")
    allow = parse_allow(os.environ.get("DOOR_ALLOW", "[]"))
    way_in, way_out = await serve(target, allow)
    log(f"door: in → {target[0]}:{target[1]}")
    log("door: out → " + (", ".join(f"{h}:{p}" for h, p in allow) or "nothing"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    async with way_in, way_out:
        await stop.wait()


def main() -> int:
    try:
        asyncio.run(run())
    except ValueError as e:
        print(f"door: {e}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
