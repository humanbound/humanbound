# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the arena catalog client (index + manifest fetch + install cache)."""

import json
import os

import httpx
import pytest
import yaml

from humanbound_cli.arena import catalog
from humanbound_cli.arena.catalog import (
    CatalogError,
    IndexEntry,
    _join,
    agent_dir,
    fetch_manifest,
    installed,
    list_installed,
    load_index,
    read_manifest,
    remove_installed,
    resolve,
    version_key,
)

from .arena_testing import CATALOG, DIGEST, ECHO_YAML, mode_of

INDEX_TEXT = (CATALOG / "index.json").read_text(encoding="utf-8")
ECHO_MANIFEST = yaml.safe_load(ECHO_YAML.read_text())


@pytest.fixture
def local_catalog(arena_home, monkeypatch):
    monkeypatch.setenv("HB_ARENA_INDEX", str(CATALOG))
    return CATALOG


def _fake_get(texts: dict, calls: list | None = None):
    """An httpx transport serving `texts[url]`; unknown URLs raise ConnectError. A value that
    is an httpx.Response is returned as is (redirects, headers)."""

    def handler(request):
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if url not in texts:
            raise httpx.ConnectError("unreachable", request=request)
        value = texts[url]
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, text=value)

    return httpx.MockTransport(handler)


def _make_catalog(root, manifest: dict, *, compose_text: str | None = None):
    """Write a one-agent local catalog under root and return the index.json path."""
    (root / "agents" / manifest["id"]).mkdir(parents=True, exist_ok=True)
    (root / "agents" / manifest["id"] / "arena.yaml").write_text(yaml.safe_dump(manifest))
    if compose_text is not None:
        (root / "agents" / manifest["id"] / "docker-compose.yml").write_text(compose_text)
    index = {
        "schema_version": 1,
        "agents": [
            {
                "id": manifest["id"],
                "version": manifest["version"],
                "name": manifest["name"],
                "manifest_url": f"agents/{manifest['id']}/arena.yaml",
            }
        ],
    }
    (root / "index.json").write_text(json.dumps(index))
    return root / "index.json"


def _compose_manifest(compose: str) -> dict:
    m = json.loads(json.dumps(ECHO_MANIFEST))
    m["source"] = {"compose": compose, "service": "agent"}
    return m


def test_index_loads_from_local_directory(local_catalog):
    loaded = load_index()
    assert loaded.stale is False
    assert loaded.location == str(CATALOG / "index.json")
    assert {e.id for e in loaded.index.agents} == {"echo"}


def test_resolve_versions_and_errors(local_catalog):
    index = load_index().index
    assert resolve(index, "echo").version == "0.1.0"
    assert resolve(index, "echo:0.0.9").version == "0.0.9"
    with pytest.raises(CatalogError, match="Did you mean: echo"):
        resolve(index, "ecko")
    with pytest.raises(CatalogError, match="0.0.9, 0.1.0"):
        resolve(index, "echo:9.9.9")


def test_fetch_manifest_caches_and_installed_finds_it(local_catalog, arena_home):
    loaded = load_index()
    manifest, target = fetch_manifest(resolve(loaded.index, "echo"), loaded.location)
    assert manifest.id == "echo"
    assert target == arena_home / "agents" / "echo" / "0.1.0"
    assert (target / "arena.yaml").exists()
    found = installed("echo")
    assert found is not None and found[1] == target
    assert [m.id for m in list_installed()] == ["echo"]


def test_index_manifest_mismatch_writes_nothing(local_catalog, arena_home):
    loaded = load_index()
    with pytest.raises(CatalogError, match="mismatch"):
        fetch_manifest(resolve(loaded.index, "echo:0.0.9"), loaded.location)
    assert not (arena_home / "agents").exists()
    assert installed("echo") is None


def test_remove_installed(local_catalog, arena_home):
    loaded = load_index()
    fetch_manifest(resolve(loaded.index, "echo"), loaded.location)
    assert remove_installed("echo") is True
    assert remove_installed("echo") is False
    assert installed("echo") is None


def test_remove_installed_rejects_traversal(arena_home):
    (arena_home / "agents" / "keep").mkdir(parents=True)
    with pytest.raises(CatalogError):
        remove_installed("..")
    assert (arena_home / "agents" / "keep").exists()
    assert installed("..") is None


def test_ids_with_trailing_newline_rejected(arena_home):
    (arena_home / "agents" / "echo").mkdir(parents=True)
    assert installed("echo\n") is None
    with pytest.raises(CatalogError):
        remove_installed("echo\n")
    assert (arena_home / "agents" / "echo").exists()


URL_A = "https://example.test/a/index.json"
URL_B = "https://example.test/b/index.json"


def test_url_cache_served_when_same_url_unreachable(arena_home, monkeypatch):
    monkeypatch.setattr(catalog, "_transport", _fake_get({URL_A: INDEX_TEXT}))
    fresh = load_index(URL_A)
    assert fresh.stale is False and fresh.location == URL_A
    monkeypatch.setattr(catalog, "_transport", _fake_get({}))
    stale = load_index(URL_A)
    assert stale.stale is True
    assert {e.id for e in stale.index.agents} == {"echo"}


def test_url_cache_not_served_for_other_url(arena_home, monkeypatch):
    monkeypatch.setattr(catalog, "_transport", _fake_get({URL_A: INDEX_TEXT}))
    load_index(URL_A)
    monkeypatch.setattr(catalog, "_transport", _fake_get({}))
    with pytest.raises(CatalogError, match="cannot load"):
        load_index(URL_B)


def test_mistyped_local_path_raises_even_with_cache(arena_home, tmp_path, monkeypatch):
    missing = str(tmp_path / "no-such-catalog" / "index.json")
    (arena_home / "cache").mkdir(parents=True)
    (arena_home / "cache" / "index.json").write_text(
        json.dumps({"location": missing, "index": json.loads(INDEX_TEXT)})
    )
    with pytest.raises(CatalogError, match="cannot load"):
        load_index(missing)


def test_local_index_is_not_cached(local_catalog, arena_home):
    load_index()
    assert not (arena_home / "cache" / "index.json").exists()


@pytest.mark.parametrize("text", ["{not json", json.dumps({"agents": []})])
def test_invalid_index_content(arena_home, tmp_path, text):
    path = tmp_path / "index.json"
    path.write_text(text)
    with pytest.raises(CatalogError, match="is invalid"):
        load_index(str(path))


def test_corrupt_cache_file(arena_home, monkeypatch):
    (arena_home / "cache").mkdir(parents=True)
    (arena_home / "cache" / "index.json").write_text("{garbage")
    monkeypatch.setattr(catalog, "_transport", _fake_get({}))
    with pytest.raises(CatalogError, match="cannot load"):
        load_index(URL_A)


def test_min_hb_version_enforced(arena_home, tmp_path, monkeypatch):
    data = json.loads(INDEX_TEXT)
    data["min_hb_version"] = "999.0.0"
    path = tmp_path / "index.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(catalog, "__version__", "2.10.0")
    with pytest.raises(CatalogError, match="newer hb"):
        load_index(str(path))


def test_version_key():
    assert version_key("2.11.0rc1") == (2, 11, 0)
    assert version_key("2") == (2, 0, 0)
    assert version_key("1.10.0") > version_key("1.9.9")


def test_join_url_base_never_yields_local_path():
    assert (
        _join("https://x/a/index.json", "agents/e/arena.yaml") == "https://x/a/agents/e/arena.yaml"
    )
    assert _join("https://x/a/index.json", "/etc/passwd") == "https://x/etc/passwd"
    assert _join("https://x/a/index.json", "https://y/b.yaml") == "https://y/b.yaml"
    assert _join("http://x/a/index.json", "http://y/b.yaml") == "http://y/b.yaml"


@pytest.mark.parametrize(
    "relative",
    [
        "C:/Users/me/secret.yaml",  # urljoin keeps it: 'c' parses as a URL scheme
        "C:\\Users\\me\\secret.yaml",
        "file:///etc/passwd",
        "file:etc/passwd",
        "ftp://x/y",
        "http://x/downgrade.yaml",  # https base must not downgrade to http
    ],
)
def test_join_url_base_rejects_non_https_results(relative):
    with pytest.raises(CatalogError):
        _join("https://x/a/index.json", relative)


@pytest.mark.parametrize(
    "compose",
    [
        "/etc/docker-compose.yml",
        "../docker-compose.yml",
        "a/../../x.yml",
        "C:/docker-compose.yml",
        "C:docker-compose.yml",
        "file:docker-compose.yml",
        "a\\..\\..\\x.yml",
        "https://evil/x.yml",
    ],
)
def test_unsafe_compose_path_rejected_before_fetch(arena_home, tmp_path, monkeypatch, compose):
    index_path = _make_catalog(tmp_path / "cat", _compose_manifest(compose))
    reads = []
    real_read = catalog._read_text
    monkeypatch.setattr(
        catalog, "_read_text", lambda loc, **kw: reads.append(loc) or real_read(loc, **kw)
    )
    entry = load_index(str(index_path)).index.agents[0]
    reads.clear()
    with pytest.raises(CatalogError, match="source.compose"):
        fetch_manifest(entry, str(index_path))
    assert reads == [str(index_path.parent / "agents" / "echo" / "arena.yaml")]
    assert installed("echo") is None


def test_compose_fetch_failure_installs_nothing(arena_home, tmp_path):
    index_path = _make_catalog(tmp_path / "cat", _compose_manifest("docker-compose.yml"))
    entry = load_index(str(index_path)).index.agents[0]
    with pytest.raises(CatalogError, match="compose file"):
        fetch_manifest(entry, str(index_path))
    assert installed("echo") is None


def test_compose_to_image_removes_stale_compose_file(arena_home, tmp_path):
    root = tmp_path / "cat"
    index_path = _make_catalog(
        root,
        _compose_manifest("docker-compose.yml"),
        compose_text="services: {agent: {image: x}}\n",
    )
    entry = load_index(str(index_path)).index.agents[0]
    _, target = fetch_manifest(entry, str(index_path))
    assert (target / "docker-compose.yml").exists()

    _make_catalog(root, ECHO_MANIFEST)
    manifest, target = fetch_manifest(entry, str(index_path))
    assert manifest.source.image
    assert not (target / "docker-compose.yml").exists()


def _fail_replace_of(name, monkeypatch):
    real_replace = catalog.os.replace

    def replace(src, dst):
        if str(dst).endswith(name):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(catalog.os, "replace", replace)


def test_failed_arena_yaml_write_leaves_no_partial_install(arena_home, tmp_path, monkeypatch):
    index_path = _make_catalog(
        tmp_path / "cat",
        _compose_manifest("docker-compose.yml"),
        compose_text="services: {agent: {image: x}}\n",
    )
    entry = load_index(str(index_path)).index.agents[0]
    _fail_replace_of("arena.yaml", monkeypatch)
    with pytest.raises(OSError):
        fetch_manifest(entry, str(index_path))
    target = agent_dir("echo", "0.1.0")
    assert not (target / "arena.yaml").exists()
    assert installed("echo") is None
    # no temp files
    assert sorted(p.name for p in target.iterdir()) == ["docker-compose.yml", "installed.json"]


def test_failed_rewrite_keeps_previous_arena_yaml(local_catalog, arena_home, monkeypatch):
    loaded = load_index()
    entry = resolve(loaded.index, "echo")
    _, target = fetch_manifest(entry, loaded.location)
    before = (target / "arena.yaml").read_text()
    _fail_replace_of("arena.yaml", monkeypatch)
    with pytest.raises(OSError):
        fetch_manifest(entry, loaded.location)
    assert (target / "arena.yaml").read_text() == before
    assert sorted(p.name for p in target.iterdir()) == ["arena.yaml", "installed.json"]


def test_compose_file_written_before_arena_yaml(arena_home, tmp_path, monkeypatch):
    index_path = _make_catalog(
        tmp_path / "cat",
        _compose_manifest("docker-compose.yml"),
        compose_text="services: {agent: {image: x}}\n",
    )
    entry = load_index(str(index_path)).index.agents[0]
    order = []
    real_replace = catalog.os.replace
    monkeypatch.setattr(
        catalog.os,
        "replace",
        lambda src, dst: order.append(os.path.basename(dst)) or real_replace(src, dst),
    )
    fetch_manifest(entry, str(index_path))
    assert order == ["docker-compose.yml", "installed.json", "arena.yaml"]


def test_read_manifest_writes_nothing(local_catalog, arena_home):
    loaded = load_index()
    manifest = read_manifest(resolve(loaded.index, "echo"), loaded.location)
    assert manifest.id == "echo"
    assert installed("echo") is None
    assert not (arena_home / "agents").exists()


def test_list_installed_skips_corrupt(arena_home, local_catalog):
    loaded = load_index()
    fetch_manifest(resolve(loaded.index, "echo"), loaded.location)
    bad = agent_dir("broken", "1.0.0")
    bad.mkdir(parents=True)
    (bad / "arena.yaml").write_text("id: [unterminated")
    assert [m.id for m in list_installed()] == ["echo"]


@pytest.mark.parametrize("bad", ["/abs.yml", "../x.yml", "C:x.yml", "a\\b.yml"])
def test_check_compose_path_is_public(bad):
    catalog.check_compose_path("docker-compose.yml")
    catalog.check_compose_path("deploy/stack.yml")
    with pytest.raises(CatalogError, match="source.compose"):
        catalog.check_compose_path(bad)


# ── hardening: sizes, redirects, YAML limits, control characters ──

HTTPS_INDEX = "https://catalog.example/index.json"


def _index_with(entry_changes: dict) -> str:
    data = json.loads(INDEX_TEXT)
    data["agents"][0].update(entry_changes)
    return json.dumps(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "Echo"},
        {"id": "../echo"},
        {"id": "echo\n"},
        {"version": "1.0"},
        {"version": "1.0.0\x1b"},
        {"name": "Echo\x1b[31m"},
        {"name": "Echo\nsecond line"},
        {"description": "bad \x9b escape"},
        {"description": "bell\x07"},
        {"tags": ["ok", "bad\x00"]},
        {"difficulty": "easy\x1b"},
        {"manifest_url": "agents/echo/arena.yaml\x00"},
    ],
)
def test_index_entry_rejects_bad_text(changes):
    entry = dict(json.loads(INDEX_TEXT)["agents"][0], **changes)
    with pytest.raises(ValueError):
        IndexEntry.model_validate(entry)


def test_index_entry_description_allows_newline_and_tab():
    entry = dict(json.loads(INDEX_TEXT)["agents"][0], description="one\n\ttwo")
    assert IndexEntry.model_validate(entry).description == "one\n\ttwo"


def test_index_with_bad_entry_is_a_catalog_error(arena_home, tmp_path):
    path = tmp_path / "index.json"
    path.write_text(_index_with({"name": "\x1b]0;pwned\x07"}))
    with pytest.raises(CatalogError, match="invalid"):
        load_index(str(path))


@pytest.mark.parametrize("depth", [65, 1000, 100000])
def test_deeply_nested_index_is_a_catalog_error(arena_home, tmp_path, depth):
    """The same on every Python version: their JSON parsers give up at different depths."""
    path = tmp_path / "index.json"
    path.write_text('{"schema_version": 1, "x": ' + "[" * (depth - 1) + "]" * (depth - 1) + "}")
    with pytest.raises(CatalogError, match="nested too deeply"):
        load_index(str(path))


def test_nesting_is_counted_outside_strings_only(arena_home, tmp_path):
    from humanbound_cli.arena.catalog import MAX_INDEX_DEPTH, _too_deep

    assert not _too_deep("[" * MAX_INDEX_DEPTH + "]" * MAX_INDEX_DEPTH)
    assert _too_deep("[" * (MAX_INDEX_DEPTH + 1) + "]" * (MAX_INDEX_DEPTH + 1))
    assert not _too_deep('{"a": "' + "[{" * 500 + '"}')
    assert not _too_deep('{"a": "quote \\" then ' + "[" * 500 + '"}')
    assert not _too_deep('{"a": "ends with a backslash \\\\", "b": [[1]]}')
    assert not _too_deep("[1], " * 500)  # one after the other, not inside each other
    data = {"schema_version": 1, "agents": [], "note": "[" * 500}
    path = tmp_path / "index.json"
    path.write_text(json.dumps(data))
    assert load_index(str(path)).index.agents == []


def test_oversize_local_index_rejected(arena_home, tmp_path):
    path = tmp_path / "index.json"
    path.write_text(INDEX_TEXT[:-2] + ', "pad": "' + "x" * (1024 * 1024) + '"}')
    with pytest.raises(CatalogError, match="too large"):
        load_index(str(path))


def test_oversize_remote_index_rejected(arena_home, monkeypatch):
    big = INDEX_TEXT[:-2] + ', "pad": "' + "x" * (1024 * 1024) + '"}'
    monkeypatch.setattr(catalog, "_transport", _fake_get({HTTPS_INDEX: big}))
    with pytest.raises(CatalogError, match="too large"):
        load_index(HTTPS_INDEX)


def test_oversize_remote_index_rejected_by_content_length(arena_home, monkeypatch):
    resp = httpx.Response(200, headers={"Content-Length": str(50 * 1024 * 1024)}, content=b"{}")
    monkeypatch.setattr(catalog, "_transport", _fake_get({HTTPS_INDEX: resp}))
    with pytest.raises(CatalogError, match="too large"):
        load_index(HTTPS_INDEX)


def test_oversize_remote_manifest_rejected(arena_home, monkeypatch):
    manifest_url = "https://catalog.example/agents/echo/arena.yaml"
    big = yaml.safe_dump(dict(ECHO_MANIFEST, context="x" * 1000)) + "#" + "x" * (300 * 1024)
    monkeypatch.setattr(
        catalog, "_transport", _fake_get({HTTPS_INDEX: INDEX_TEXT, manifest_url: big})
    )
    loaded = load_index(HTTPS_INDEX)
    with pytest.raises(CatalogError, match="too large"):
        read_manifest(resolve(loaded.index, "echo"), loaded.location)


def test_alias_bomb_manifest_from_index_rejected(arena_home, tmp_path):
    from .test_arena_manifest import ALIAS_BOMB

    index_path = _make_catalog(tmp_path / "cat", ECHO_MANIFEST)
    (tmp_path / "cat" / "agents" / "echo" / "arena.yaml").write_text(ALIAS_BOMB)
    entry = load_index(str(index_path)).index.agents[0]
    with pytest.raises(catalog.ManifestError, match="alias|anchor"):
        read_manifest(entry, str(index_path))


def test_redirect_within_https_is_followed(arena_home, monkeypatch):
    moved = "https://mirror.example/index.json"
    texts = {
        HTTPS_INDEX: httpx.Response(302, headers={"Location": moved}),
        moved: INDEX_TEXT,
    }
    monkeypatch.setattr(catalog, "_transport", _fake_get(texts))
    assert load_index(HTTPS_INDEX).index.agents[0].id == "echo"


@pytest.mark.parametrize(
    "location",
    ["http://mirror.example/index.json", "file:///etc/passwd", "ftp://mirror.example/index.json"],
)
def test_redirect_changing_scheme_refused(arena_home, monkeypatch, location):
    texts = {HTTPS_INDEX: httpx.Response(301, headers={"Location": location})}
    monkeypatch.setattr(catalog, "_transport", _fake_get(texts))
    with pytest.raises(CatalogError, match="redirect"):
        load_index(HTTPS_INDEX)


def test_redirect_loop_refused(arena_home, monkeypatch):
    texts = {HTTPS_INDEX: httpx.Response(302, headers={"Location": HTTPS_INDEX})}
    monkeypatch.setattr(catalog, "_transport", _fake_get(texts))
    with pytest.raises(CatalogError, match="redirect"):
        load_index(HTTPS_INDEX)


# ── provenance: where an installed agent came from ──


OTHER_DIGEST = "sha256:" + "fedcba9876543210" * 4


def test_fetch_manifest_records_provenance(local_catalog, arena_home):
    loaded = load_index()
    _, path = fetch_manifest(resolve(loaded.index, "echo"), loaded.location)
    prov = catalog.read_provenance(path)
    assert prov == catalog.Provenance(index=str(CATALOG / "index.json"), images=())
    assert not catalog.trusted(prov)


def test_fetch_manifest_records_the_entrys_images(arena_home, tmp_path):
    root = tmp_path / "cat"
    import shutil

    shutil.copytree(CATALOG, root)
    data = json.loads((root / "index.json").read_text())
    data["agents"][0]["images"] = [{"ref": "humanbound-arena-echo:test", "digest": DIGEST}]
    (root / "index.json").write_text(json.dumps(data))
    loaded = load_index(str(root))
    _, path = fetch_manifest(resolve(loaded.index, "echo"), loaded.location)
    record = json.loads((path / catalog.PROVENANCE_FILE).read_text())
    assert record == {
        "index": str(root / "index.json"),
        "images": [{"ref": "humanbound-arena-echo:test", "digest": DIGEST}],
    }
    prov = catalog.read_provenance(path)
    assert prov.images == (catalog.ImagePin(ref="humanbound-arena-echo:test", digest=DIGEST),)
    assert prov.images[0].by_digest == "humanbound-arena-echo@" + DIGEST


def test_trusted_only_for_the_default_index(monkeypatch):
    from humanbound_cli.arena import paths

    assert catalog.trusted(catalog.Provenance(paths.DEFAULT_INDEX_URL))
    assert not catalog.trusted(None)
    assert not catalog.trusted(catalog.Provenance("/x/index.json"))
    assert not catalog.trusted(catalog.Provenance(str(CATALOG / "index.json")))
    assert not catalog.trusted(
        catalog.Provenance("https://raw.githubusercontent.com/someone/fork/main/index.json")
    )
    # A default-index URL with a different path or scheme is another catalog.
    assert not catalog.trusted(catalog.Provenance(paths.DEFAULT_INDEX_URL + "?x=1"))
    assert not catalog.trusted(
        catalog.Provenance(paths.DEFAULT_INDEX_URL.replace("https://", "http://"))
    )


def test_is_trusted_reads_the_install_record(tmp_path, monkeypatch):
    from humanbound_cli.arena import paths

    assert not catalog.is_trusted(tmp_path)
    (tmp_path / catalog.PROVENANCE_FILE).write_text(json.dumps({"index": "/x/index.json"}))
    assert not catalog.is_trusted(tmp_path)
    (tmp_path / catalog.PROVENANCE_FILE).write_text(
        json.dumps({"index": paths.DEFAULT_INDEX_URL, "images": []})
    )
    assert catalog.is_trusted(tmp_path)


def test_an_old_record_with_origin_still_reads(tmp_path):
    # installed.json from before the community tier was removed: origin is ignored.
    (tmp_path / catalog.PROVENANCE_FILE).write_text(
        json.dumps({"index": "/x/index.json", "origin": "first-party"})
    )
    assert catalog.read_provenance(tmp_path) == catalog.Provenance("/x/index.json", ())


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"index": 1}',
        '{"origin": "x"}',
        '{"index": "/x", "images": {}}',
        '{"index": "/x", "images": [{"ref": "a:1"}]}',
        '{"index": "/x", "images": [{"ref": "a:1", "digest": "sha256:abc"}]}',
        '{"index": "/x", "images": ["a:1"]}',
    ],
)
def test_read_provenance_tolerates_junk(tmp_path, text):
    (tmp_path / catalog.PROVENANCE_FILE).write_text(text)
    assert catalog.read_provenance(tmp_path) is None
    assert catalog.read_provenance(tmp_path / "missing") is None


# ── index images ──


def _entry(**changes):
    return dict(json.loads(INDEX_TEXT)["agents"][0], **changes)


def test_index_entry_images_are_optional():
    assert IndexEntry.model_validate(_entry()).images == []


def test_index_entry_images_parse():
    images = [
        {"ref": "ghcr.io/example/arena-echo:0.1.0", "digest": DIGEST},
        {"ref": "localhost:5000/x/db:16", "digest": OTHER_DIGEST},
        {"ref": "postgres", "digest": DIGEST},
    ]
    entry = IndexEntry.model_validate(_entry(images=images))
    assert [p.ref for p in entry.images] == [i["ref"] for i in images]
    assert [p.by_digest for p in entry.images] == [
        "ghcr.io/example/arena-echo@" + DIGEST,
        "localhost:5000/x/db@" + OTHER_DIGEST,
        "postgres@" + DIGEST,
    ]


@pytest.mark.parametrize(
    "image",
    [
        {"ref": "x:1"},
        {"digest": DIGEST},
        {"ref": "x:1", "digest": "sha256:abc"},
        {"ref": "x:1", "digest": "sha256:" + "A" * 64},
        {"ref": "x:1", "digest": "sha512:" + "a" * 64},
        {"ref": "x:1", "digest": DIGEST + "\n"},
        {"ref": "-x:1", "digest": DIGEST},
        {"ref": "--privileged", "digest": DIGEST},
        {"ref": "X:1", "digest": DIGEST},
        {"ref": "x:1\x1b[2J", "digest": DIGEST},
        {"ref": "x:1 y", "digest": DIGEST},
        {"ref": "x@" + DIGEST, "digest": DIGEST},
        {"ref": "", "digest": DIGEST},
        "x:1",
    ],
)
def test_index_entry_rejects_bad_images(image):
    with pytest.raises(ValueError):
        IndexEntry.model_validate(_entry(images=[image]))


def test_index_entry_rejects_duplicate_image_refs():
    images = [{"ref": "x:1", "digest": DIGEST}, {"ref": "x:1", "digest": OTHER_DIGEST}]
    with pytest.raises(ValueError, match="more than once"):
        IndexEntry.model_validate(_entry(images=images))


def test_index_entry_ignores_unknown_keys_such_as_origin():
    entry = IndexEntry.model_validate(_entry(origin="community", deprecated=True))
    assert not hasattr(entry, "origin")


def test_index_with_bad_images_is_a_catalog_error(arena_home, tmp_path):
    path = tmp_path / "index.json"
    path.write_text(_index_with({"images": [{"ref": "x:1", "digest": "nope"}]}))
    with pytest.raises(CatalogError, match="invalid"):
        load_index(str(path))


@pytest.mark.parametrize(
    "ref, repository",
    [
        ("x", "x"),
        ("x:1", "x"),
        ("org/x:1.0", "org/x"),
        ("localhost:5000/x", "localhost:5000/x"),
        ("localhost:5000/x:2", "localhost:5000/x"),
        ("ghcr.io/a/b/c:1", "ghcr.io/a/b/c"),
        ("x:1@" + DIGEST, "x"),
    ],
)
def test_repository_of(ref, repository):
    assert catalog.repository_of(ref) == repository


# ── arena dir permissions ──


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_ensure_arena_dir_is_private(arena_home):
    from humanbound_cli.arena import paths

    assert paths.ensure_arena_dir() == arena_home
    assert mode_of(arena_home) == 0o700
    os.chmod(arena_home, 0o755)
    paths.ensure_arena_dir()
    assert mode_of(arena_home) == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_install_and_cache_create_a_private_arena_dir(arena_home, monkeypatch):
    monkeypatch.setattr(
        catalog, "_transport", _fake_get({"https://x.example/index.json": INDEX_TEXT})
    )
    load_index("https://x.example/index.json")
    assert mode_of(arena_home) == 0o700
    os.chmod(arena_home, 0o755)
    monkeypatch.setenv("HB_ARENA_INDEX", str(CATALOG))
    loaded = load_index()
    fetch_manifest(resolve(loaded.index, "echo"), loaded.location)
    assert mode_of(arena_home) == 0o700


# ── what to say about an agent that is not running ──


def test_not_running_message_for_an_installed_agent_points_at_run(local_catalog):
    loaded = catalog.load_index()
    catalog.fetch_manifest(catalog.resolve(loaded.index, "echo"), loaded.location)
    assert catalog.not_running_message("echo") == "echo is not running → hb arena run echo"


def test_not_running_message_for_an_unknown_agent_points_at_the_catalog(arena_home):
    message = catalog.not_running_message("no-such-agent")
    assert message.startswith("no-such-agent is not running, and it is not installed")
    assert "hb arena ls" in message
    assert "hb arena run no-such-agent" not in message


@pytest.mark.parametrize("bad", ["", "Bad Id", "../x", "echo\n"])
def test_not_running_message_for_an_invalid_id(arena_home, bad):
    message = catalog.not_running_message(bad)
    assert "is not a valid agent id" in message
    assert "hb arena ls" in message
