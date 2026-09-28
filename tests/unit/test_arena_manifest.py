# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import copy
import re

import pytest

from humanbound_cli.arena import paths
from humanbound_cli.arena.manifest import (
    SCHEMA_VERSION,
    ManifestError,
    load_manifest,
    parse_manifest,
)

from .arena_testing import SHA

VALID = {
    "schema_version": 1,
    "id": "pricer",
    "name": "Pricer",
    "version": "1.2.0",
    "developer": {"name": "Humanbound", "url": "https://humanbound.ai"},
    "description": "Example agent.",
    "tags": ["indirect-injection"],
    "difficulty": "medium",
    "agent": {
        "version": "1.0",
        "scope": {"business": "Answers shop questions.", "more_info": "HIGH"},
        "intents": {"permitted": ["Read pages"], "restricted": ["Leak internal notes"]},
        "capabilities": ["tools"],
        "settings": {"mode": "strict"},
    },
    "source": {"image": "ghcr.io/example/arena-pricer:1.2.0"},
    "runtime": {"port": 8080, "env": {"required": ["OPENAI_API_KEY"]}},
    "integration": {
        "type": "http",
        "chat_completion": {"endpoint": "/run", "payload": {"prompt": "$PROMPT"}},
        "response": {"text": "recommendation"},
    },
    "context": "Example shop",
    "ground_truth": {"V1": {"category": "llm001", "description": "Indirect injection"}},
}


def _with(**changes):
    doc = copy.deepcopy(VALID)
    for dotted, value in changes.items():
        cur = doc
        *parents, last = dotted.split("__")
        for p in parents:
            cur = cur[p]
        if value is None:
            cur.pop(last, None)
        else:
            cur[last] = value
    return doc


def test_valid_manifest_parses_with_defaults():
    m = parse_manifest(copy.deepcopy(VALID))
    assert m.id == "pricer"
    assert m.runtime.health.path == "/health"
    assert m.runtime.timeout_s == 120
    assert m.integration.history == "none"


def test_agent_block_is_returned_exactly_as_authored():
    assert parse_manifest(copy.deepcopy(VALID)).agent_yaml() == VALID["agent"]
    minimal = {"scope": {"business": "b"}, "intents": {"permitted": []}, "tools": None}
    assert parse_manifest(_with(agent=minimal)).agent_yaml() == minimal


@pytest.mark.parametrize(
    "changes, fragment",
    [
        ({"id": "Bad Id"}, "\n  id:"),
        ({"version": "1.2"}, "version"),
        ({"agent__capabilities": ["telepathy"]}, "unknown capability"),
        ({"agent__capabilities": ["tools", "tools"]}, "duplicate capability"),
        ({"source": {}}, "exactly one of 'image' or 'compose'"),
        ({"source": {"compose": "docker-compose.yml"}}, "needs 'service'"),
        ({"integration__response": None}, "needs 'chat_completion' and 'response'"),
        (
            {"integration__chat_completion": {"endpoint": "/run", "payload": {"q": "hi"}}},
            "must contain $PROMPT",
        ),
        (
            {"integration__chat_completion": {"endpoint": "run", "payload": {"q": "$PROMPT"}}},
            "must start with '/'",
        ),
        ({"runtime__health": {"path": "health"}}, "must start with '/'"),
        ({"runtime__timeout_s": 0}, "timeout_s"),
        ({"runtime__env": {"required": ["HB_API_KEY"]}}, "reserved for hb's own credentials"),
        ({"runtime__env": {"required": ["not a name"]}}, "runtime.env"),
        ({"runtime__env": {"required": ["TRAILING\n"]}}, "runtime.env"),
        ({"context": "x" * 1501}, "context"),
        ({"origin": "community"}, "origin"),  # removed: an unknown key now
        ({"origin": "first-party"}, "origin"),
        ({"developer": None}, "developer"),
        ({"developer__name": "  "}, "developer.name can't be empty"),
        ({"developer__name": None}, "developer.name"),
        ({"developer__url": None}, "developer.url"),
        ({"developer__url": "humanbound.ai"}, "developer.url must be an http(s) URL"),
        ({"developer__url": "ftp://humanbound.ai"}, "developer.url must be an http(s) URL"),
        ({"developer__url": "https://"}, "developer.url must be an http(s) URL"),
        ({"developer__url": "https://x.io/a b"}, "developer.url must be an http(s) URL"),
        ({"developer__contact": ""}, "developer.contact can't be empty"),
        ({"developer__email": "a@b.c"}, "developer.email"),
        ({"schema_version": 0}, "schema_version"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_invalid_manifests_are_rejected_with_a_readable_message(changes, fragment):
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_with(**changes))
    assert fragment in str(exc.value)
    assert "Value error, " not in str(exc.value)


def test_a2a_integration_needs_no_http_calls():
    assert (
        parse_manifest(_with(integration={"type": "a2a", "path": "/a2a"})).integration.path
        == "/a2a"
    )


def test_rich_ground_truth_fields_are_optional_and_validated():
    gt = {
        "category": "llm001",
        "description": "d",
        "title": "t",
        "severity": "high",
        "vector": "indirect",
        "success": [
            {"reply_contains": "internal note"},
            {"reply_regex": "cost\\s*\\d+"},
            {"tool_called": {"name": "fetch", "arg_regex": "cost=\\d+"}},
        ],
    }
    m = parse_manifest(_with(ground_truth={"V1": gt}))
    assert m.ground_truth["V1"].severity == "high"
    with pytest.raises(ManifestError):
        parse_manifest(_with(ground_truth={"V1": {**gt, "severity": "extreme"}}))
    with pytest.raises(ManifestError):
        parse_manifest(
            _with(
                ground_truth={
                    "V1": {**gt, "success": [{"reply_contains": "a", "reply_regex": "b"}]}
                }
            )
        )


@pytest.mark.parametrize("version", ["2", 2.0, SCHEMA_VERSION + 1])
def test_future_schema_version_asks_for_upgrade(version):
    with pytest.raises(ManifestError, match="newer hb"):
        parse_manifest(_with(schema_version=version))


def test_load_manifest_reads_yaml_and_reports_problems(tmp_path):
    import yaml

    f = tmp_path / "arena.yaml"
    f.write_text(yaml.safe_dump(VALID))
    assert load_manifest(f).name == "Pricer"
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(tmp_path / "missing.yaml")
    bad = tmp_path / "bin.yaml"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(bad)


def test_arena_owner_is_stable_per_home(tmp_path, monkeypatch):
    import hashlib
    import sys

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "a")
    monkeypatch.setenv("HOME", str(tmp_path / "a"))
    owner_a = paths.arena_owner()
    assert re.fullmatch(r"[0-9a-f]{12}", owner_a)
    resolved = str(paths.arena_dir().resolve())
    if sys.platform in ("darwin", "win32"):
        resolved = resolved.casefold()
    expected = hashlib.sha256(resolved.encode()).hexdigest()[:12]
    assert owner_a == expected
    assert paths.arena_owner() == owner_a
    monkeypatch.setenv("HOME", str(tmp_path / "link"))  # same HOME through a symlink
    assert paths.arena_owner() == owner_a
    monkeypatch.setenv("HOME", str(tmp_path / "b"))
    assert paths.arena_owner() != owner_a


def test_paths_follow_home_and_port_env(arena_home, monkeypatch):
    assert paths.arena_dir() == arena_home
    assert paths.gateway_url() == "http://127.0.0.1:11500"
    assert paths.gateway_url(9999) == "http://127.0.0.1:9999"
    monkeypatch.setenv("HB_ARENA_PORT", "12001")
    assert paths.gateway_port() == 12001
    monkeypatch.setenv("HB_ARENA_PORT", "abc")
    with pytest.raises(ValueError, match="HB_ARENA_PORT must be a port number"):
        paths.gateway_port()


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/example/arena-pricer:1.2.0",
        "busybox@sha256:" + "a" * 64,
        "ghcr.io/humanbound/x:1.0@sha256:" + "0" * 64,
        "localhost:5000/team/agent:dev-1",
        "agent:Latest",
        "echo",
    ],
)
def test_source_image_accepts_image_refs(image):
    assert parse_manifest(_with(source={"image": image})).source.image == image


@pytest.mark.parametrize(
    "image",
    [
        "-v",
        "--privileged",
        "-it=alpine",
        "alpine --privileged",
        "alpine;id",
        "alpine\nx",
        "Alpine",
        "/abs",
        ".hidden",
        "a" * 300,
    ],
)
def test_source_image_rejects_flags_and_junk(image):
    with pytest.raises(ManifestError, match="source.image"):
        parse_manifest(_with(source={"image": image}))


UPSTREAM = {"repo": "https://github.com/x/y", "ref": SHA}


def test_upstream_is_optional():
    assert parse_manifest(_with()).source.upstream is None


def test_upstream_license_is_optional():
    source = {"image": "ghcr.io/x/y:1.0", "upstream": UPSTREAM}
    m = parse_manifest(_with(source=source))
    assert m.source.upstream.license is None
    assert m.source.upstream.ref == SHA
    for license_id in ("Apache-2.0", "MIT", "GPL-3.0-or-later", "MIT OR Apache-2.0"):
        up = {**UPSTREAM, "license": license_id}
        m = parse_manifest(_with(source={**source, "upstream": up}))
        assert m.source.upstream.license == license_id


@pytest.mark.parametrize(
    "upstream, fragment",
    [
        ({"repo": "https://github.com/x/y"}, "source.upstream.ref"),
        ({"ref": SHA}, "source.upstream.repo"),
        ({**UPSTREAM, "ref": "abc123"}, "full 40-character commit SHA"),
        ({**UPSTREAM, "ref": "main"}, "full 40-character commit SHA"),
        ({**UPSTREAM, "ref": SHA + "0"}, "full 40-character commit SHA"),
        ({**UPSTREAM, "repo": "github.com/x/y"}, "source.upstream.repo must be an http(s) URL"),
        ({**UPSTREAM, "repo": "file:///etc"}, "source.upstream.repo must be an http(s) URL"),
        ({**UPSTREAM, "license": "Apache 2.0 license"}, "SPDX license id"),
        ({**UPSTREAM, "license": ""}, "SPDX license id"),
        ({**UPSTREAM, "license": "MIT;rm"}, "SPDX license id"),
        ({**UPSTREAM, "commit": SHA}, "commit"),
    ],
)
def test_upstream_is_validated_when_present(upstream, fragment):
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_with(source={"image": "ghcr.io/x/y:1.0", "upstream": upstream}))
    assert fragment in str(exc.value)


def test_developer_contact_is_optional():
    m = parse_manifest(_with())
    assert m.developer.name == "Humanbound"
    assert m.developer.url == "https://humanbound.ai"
    assert m.developer.contact is None
    m = parse_manifest(_with(developer__contact="maintainers@example.org"))
    assert m.developer.contact == "maintainers@example.org"


@pytest.mark.parametrize(
    "field, value",
    [
        ("developer__name", "Evil\x1b[31mCorp"),
        ("developer__name", "two\nlines"),
        ("developer__contact", "a@b.c\x07"),
        ("developer__url", "https://x.io/\x1b"),
    ],
)
def test_developer_refuses_control_characters(field, value):
    with pytest.raises(ManifestError, match="control character"):
        parse_manifest(_with(**{field: value}))


@pytest.mark.parametrize("raw", ["0", "65536", "-1", "99999"])
def test_gateway_port_out_of_range(monkeypatch, raw):
    monkeypatch.setenv("HB_ARENA_PORT", raw)
    with pytest.raises(
        ValueError,
        match=f"HB_ARENA_PORT must be a port number between 1 and 65535, got '{raw}'",
    ):
        paths.gateway_port()


@pytest.mark.parametrize("raw, port", [("1", 1), ("65535", 65535)])
def test_gateway_port_range_bounds(monkeypatch, raw, port):
    monkeypatch.setenv("HB_ARENA_PORT", raw)
    assert paths.gateway_port() == port


# ── hardening: YAML limits, control characters, pinned images, timeouts ──

ALIAS_BOMB = (
    'a: &a ["x","x","x","x","x","x","x","x","x"]\n'
    "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
    "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
    "d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
    "e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]\n"
    "f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]\n"
    "g: &g [*f,*f,*f,*f,*f,*f,*f,*f,*f]\n"
)


def test_alias_bomb_rejected_quickly(tmp_path):
    import time

    path = tmp_path / "arena.yaml"
    path.write_text(ALIAS_BOMB)
    start = time.monotonic()
    with pytest.raises(ManifestError, match="alias|anchor"):
        load_manifest(path)
    assert time.monotonic() - start < 1


def test_anchor_alone_rejected(tmp_path):
    path = tmp_path / "arena.yaml"
    path.write_text("schema_version: 1\nid: &x pricer\n")
    with pytest.raises(ManifestError, match="anchor"):
        load_manifest(path)


def test_deep_nesting_is_a_clean_error(tmp_path):
    path = tmp_path / "arena.yaml"
    path.write_text("a: " + "[" * 20000 + "]" * 20000 + "\n")
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_too_many_nodes_rejected():
    from humanbound_cli.arena.manifest import load_yaml

    with pytest.raises(ManifestError, match="too large|nodes"):
        load_yaml("[" + ",".join(["1"] * 60000) + "]")


def test_oversize_manifest_file_rejected(tmp_path):
    path = tmp_path / "arena.yaml"
    path.write_text("context: " + "x" * (300 * 1024) + "\n")
    with pytest.raises(ManifestError, match="too large"):
        load_manifest(path)


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "Shop\x1b[31mBot"),
        ("name", "Shop\nBot"),
        ("name", "Shop\tBot"),
        ("description", "bell\x07"),
        ("description", "csi\x9b31m"),
        ("description", "del\x7f"),
        ("context", "nul\x00"),
        ("context", "cr\r"),
        ("tags", ["ok", "bad\x1b"]),
        ("tags", ["bad\n"]),
        ("agent__scope__business", "esc\x1b[2J"),
        ("ground_truth__V1__description", "esc\x1b[2J"),
        ("ground_truth__V1__category", "llm\n001"),
        (
            "source__upstream",
            {"repo": "https://x/\x1b", "ref": SHA},
        ),
    ],
)
def test_control_characters_rejected(field, value):
    with pytest.raises(ManifestError, match="control character"):
        parse_manifest(_with(**{field: value}))


@pytest.mark.parametrize(
    "field", ["description", "context", "ground_truth__V1__description", "agent__scope__business"]
)
def test_newline_and_tab_allowed_in_long_text(field):
    parse_manifest(_with(**{field: "line one\n\tline two"}))


@pytest.mark.parametrize("field", ["runtime__timeout_s", "runtime__health"])
def test_timeouts_are_capped(field):
    value = 601 if field == "runtime__timeout_s" else {"timeout_s": 601}
    with pytest.raises(ManifestError, match="600"):
        parse_manifest(_with(**{field: value}))
    ok = 600 if field == "runtime__timeout_s" else {"timeout_s": 600}
    parse_manifest(_with(**{field: ok}))


# ── ground_truth references (published standards) ──


def _gt(**changes):
    return _with(ground_truth={"V1": {"category": "llm001", "description": "d", **changes}})


def test_ground_truth_references_are_optional_and_kept_in_order():
    assert parse_manifest(_gt()).ground_truth["V1"].references is None
    refs = ["owasp-llm:LLM02", "owasp-agentic:ASI01", "atlas:AML.T0051.000", "atlas:AML.T0057"]
    assert parse_manifest(_gt(references=refs)).ground_truth["V1"].references == refs


def test_ground_truth_references_are_not_checked_against_a_list():
    """hb validates the shape only: the catalog decides which ids exist."""
    refs = ["some-standard:X1", "atlas:AML.T9999.999"]
    assert parse_manifest(_gt(references=refs)).ground_truth["V1"].references == refs


@pytest.mark.parametrize(
    "references, fragment",
    [
        ([], "at least 1"),
        ("owasp-llm:LLM02", "list"),
        (["LLM02"], "<standard>:<id>"),
        (["owasp-llm:"], "<standard>:<id>"),
        ([":LLM02"], "<standard>:<id>"),
        (["OWASP-LLM:LLM02"], "<standard>:<id>"),
        (["owasp llm:LLM02"], "<standard>:<id>"),
        (["owasp-llm:LLM 02"], "<standard>:<id>"),
        (["owasp-llm:LLM02\n"], "control character"),
        (["owasp-llm:LLM02", "owasp-llm:LLM02"], "duplicate reference"),
        ([42], "string"),
    ],
)
def test_ground_truth_references_shape_is_validated(references, fragment):
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_gt(references=references))
    assert "ground_truth.V1.references" in str(exc.value)
    assert fragment in str(exc.value)


# ── runtime.egress ──


def test_egress_is_optional_and_kept_as_written():
    assert parse_manifest(VALID).runtime.egress is None
    entries = ["api.example.com", "files.example.com:8443"]
    assert parse_manifest(_with(runtime__egress=entries)).runtime.egress == entries


@pytest.mark.parametrize(
    "entries, fragment",
    [
        ([], "at least 1"),
        ("api.example.com", "list"),
        ([42], "string"),
        (["*.example.com"], "exact host name"),
        (["example"], "exact host name"),
        (["API.example.com"], "exact host name"),
        (["https://api.example.com"], "is not a port"),
        (["api.example.com/path"], "exact host name"),
        (["api.example.com:"], "is not a port"),
        (["api.example.com:0"], "is not a port"),
        (["api.example.com:65536"], "is not a port"),
        (["10.0.0.5"], "exact host name"),
        (["169.254.169.254:80"], "exact host name"),
        (["[::1]:80"], "is not a port"),
        (["-api.example.com"], "exact host name"),
        (["api..example.com"], "exact host name"),
        (["api.example.com\n"], "control character"),
        (["a" * 64 + ".example.com"], "exact host name"),
        (["localhost"], "exact host name"),
        (["host.docker.internal"], "own machine or network"),
        (["printer.local:631"], "own machine or network"),
        (["nas.lan"], "own machine or network"),
        (["api.example.com", "api.example.com:443"], "listed twice"),
        ([f"h{i}.example.com" for i in range(21)], "at most 20"),
    ],
)
def test_egress_entries_are_exact_public_host_names(entries, fragment):
    with pytest.raises(ManifestError) as err:
        parse_manifest(_with(runtime__egress=entries))
    assert fragment in str(err.value)


@pytest.mark.parametrize("name", ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "https_proxy"])
def test_the_proxy_variables_are_set_by_hb_not_declared(name):
    with pytest.raises(ManifestError) as err:
        parse_manifest(_with(runtime__env={"required": [], "optional": [name]}))
    assert f"{name} is set by hb" in str(err.value)
