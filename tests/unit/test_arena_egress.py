# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for what an arena agent may reach on the network (arena/egress.py)."""

import json

import pytest

from humanbound_cli.arena import door, egress
from humanbound_cli.arena.egress import MANIFEST, MODEL, Destination


def test_the_model_is_api_openai_com_unless_the_user_says_otherwise():
    default = Destination("api.openai.com", 443, MODEL)
    assert egress.model_destination({}) == default
    assert egress.model_destination({"OPENAI_BASE_URL": ""}) == default
    assert egress.model_destination({"OPENAI_BASE_URL": "  "}) == default


@pytest.mark.parametrize(
    ("url", "host", "port"),
    [
        ("https://api.openai.com/v1", "api.openai.com", 443),
        ("https://my-resource.openai.azure.com/openai/v1/", "my-resource.openai.azure.com", 443),
        ("https://LLM.Example.com.:8443/v1", "llm.example.com", 8443),
        ("http://llm.example.com/v1", "llm.example.com", 80),
        ("http://host.docker.internal:11434/v1", "host.docker.internal", 11434),
        ("http://192.168.1.20:8000/v1", "192.168.1.20", 8000),
        ("http://[fd00::20]:8000/v1", "fd00::20", 8000),
        ("https://user:secret@llm.example.com/v1", "llm.example.com", 443),
    ],
)
def test_the_model_is_the_host_and_port_of_openai_base_url(url, host, port):
    assert egress.model_destination({"OPENAI_BASE_URL": url}) == Destination(host, port, MODEL)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://[::1]:11434/v1",
        "http://app.localhost/v1",
    ],
)
def test_a_model_on_localhost_is_the_agent_itself(url):
    assert egress.model_destination({"OPENAI_BASE_URL": url}) is None


@pytest.mark.parametrize(
    "url",
    [
        "api.openai.com",
        "api.openai.com/v1",
        "ftp://llm.example.com/v1",
        "file:///etc/passwd",
        "https://",
        "https:///v1",
        "https://llm.example.com:99999/v1",
        "https://llm.example.com:port/v1",
        "https://[::1/v1",
        "https://llm exam ple.com/v1",
    ],
)
def test_an_unreadable_model_url_is_refused(url):
    with pytest.raises(ValueError) as err:
        egress.model_destination({"OPENAI_BASE_URL": url})
    assert "OPENAI_BASE_URL must be an http(s) URL" in str(err.value)


@pytest.mark.parametrize(
    "url", ["ftp://user:s3cret@llm.example.com/v1", "https://user:s3cret@llm.example.com:port/"]
)
def test_a_refused_model_url_is_never_repeated(url):
    """It may hold credentials."""
    with pytest.raises(ValueError) as err:
        egress.model_destination({"OPENAI_BASE_URL": url})
    assert "s3cret" not in str(err.value)
    assert "llm.example.com" not in str(err.value)


def test_allowed_is_the_model_then_the_manifest_entries():
    found = egress.allowed(
        ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
        ["files.example.com", "api.example.com:8443"],
        {"OPENAI_BASE_URL": "http://host.docker.internal:11434/v1"},
    )
    assert found == [
        Destination("host.docker.internal", 11434, MODEL),
        Destination("files.example.com", 443, MANIFEST),
        Destination("api.example.com", 8443, MANIFEST),
    ]


def test_an_agent_without_an_openai_key_gets_no_model_destination():
    assert egress.allowed([], None, {}) == []
    assert egress.allowed(["SHOP_TOKEN"], None, {"OPENAI_BASE_URL": "https://x.example.com"}) == []
    assert egress.allowed(["SHOP_TOKEN"], ["api.example.com"], {}) == [
        Destination("api.example.com", 443, MANIFEST)
    ]


def test_an_agent_with_any_openai_key_gets_the_model():
    assert egress.allowed(["OPENAI_API_KEY"], None, {}) == [
        Destination("api.openai.com", 443, MODEL)
    ]
    assert egress.allowed(["openai_base_url"], None, {}) == [
        Destination("api.openai.com", 443, MODEL)
    ]


def test_a_manifest_entry_that_is_also_the_model_is_listed_once_as_the_model():
    found = egress.allowed(["OPENAI_API_KEY"], ["api.openai.com", "api.openai.com:8443"], {})
    assert found == [
        Destination("api.openai.com", 443, MODEL),
        Destination("api.openai.com", 8443, MANIFEST),
    ]


def test_a_model_on_localhost_lets_nothing_through():
    env = {"OPENAI_BASE_URL": "http://localhost:11434/v1"}
    assert egress.allowed(["OPENAI_API_KEY"], None, env) == []


def test_describe():
    assert egress.describe([]) == "nothing"
    found = [
        Destination("api.openai.com", 443, MODEL),
        Destination("files.example.com", 8443, MANIFEST),
        Destination("fd00::20", 8000, MANIFEST),
    ]
    assert egress.describe(found) == (
        "api.openai.com:443 (the model), files.example.com:8443, [fd00::20]:8000"
    )


def test_the_proxy_variables_point_at_the_door_in_both_spellings():
    env = egress.proxy_env(["agent", "db", "agent"])
    assert env["HTTP_PROXY"] == env["HTTPS_PROXY"] == "http://hb-door:3128"
    assert env["http_proxy"] == env["https_proxy"] == "http://hb-door:3128"
    assert env["NO_PROXY"] == env["no_proxy"] == "localhost,127.0.0.1,::1,agent,db"
    assert set(env) == set(egress.PROXY_NAMES)


def test_the_door_reads_what_egress_writes():
    text = egress.door_config(
        [
            Destination("host.docker.internal", 11434, MODEL),
            Destination("files.example.com", 443, MANIFEST),
        ]
    )
    assert json.loads(text) == [
        {"host": "host.docker.internal", "port": 11434, "private": True},
        {"host": "files.example.com", "port": 443, "private": False},
    ]
    assert door.parse_allow(text) == {
        ("host.docker.internal", 11434): True,
        ("files.example.com", 443): False,
    }
    assert door.parse_allow(egress.door_config([])) == {}


def test_the_door_and_egress_agree_on_the_proxy_port():
    assert egress.PROXY_PORT == door.OUT_PORT
