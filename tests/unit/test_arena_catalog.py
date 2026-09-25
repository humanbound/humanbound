# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import json

import httpx
import pytest
import yaml
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import catalog
from humanbound_cli.arena.catalog import CatalogError
from humanbound_cli.arena.manifest import ManifestError

CATALOG = ARENA_FIXTURES / "catalog"


@pytest.fixture
def local_catalog(arena_home, monkeypatch):
    monkeypatch.setenv("HB_ARENA_INDEX", str(CATALOG))
    return CATALOG


def test_loads_index_from_a_local_directory(local_catalog):
    loaded = catalog.load_index()
    assert loaded.stale is False
    assert loaded.location == str(CATALOG / "index.json")
    assert {e.id for e in loaded.index.agents} == {"echo"}


def test_resolve_picks_the_highest_version_by_default(local_catalog):
    index = catalog.load_index().index
    assert catalog.resolve(index, "echo").version == "0.1.0"
    assert catalog.resolve(index, "echo:0.0.9").version == "0.0.9"


def test_resolve_suggests_close_matches(local_catalog):
    index = catalog.load_index().index
    with pytest.raises(CatalogError, match="Did you mean: echo"):
        catalog.resolve(index, "ecko")


def test_resolve_unknown_version_lists_available(local_catalog):
    index = catalog.load_index().index
    with pytest.raises(CatalogError, match="0.0.9, 0.1.0"):
        catalog.resolve(index, "echo:9.9.9")


def test_fetch_manifest_caches_it_under_arena_dir(local_catalog, arena_home):
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo")
    manifest, agent_dir = catalog.fetch_manifest(entry, loaded.location)
    assert manifest.id == "echo"
    assert agent_dir == arena_home / "agents" / "echo" / "0.1.0"
    assert (agent_dir / "arena.yaml").exists()
    found = catalog.installed("echo")
    assert found is not None and found[0].version == "0.1.0"
    assert [m.id for m in catalog.list_installed()] == ["echo"]


def test_fetch_manifest_rejects_index_manifest_mismatch(local_catalog):
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo:0.0.9")  # manifest file says 0.1.0
    with pytest.raises(CatalogError, match="mismatch"):
        catalog.fetch_manifest(entry, loaded.location)


def test_read_manifest_does_not_write_to_disk(local_catalog, arena_home):
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo")
    manifest = catalog.read_manifest(entry, loaded.location)
    assert manifest.id == "echo"
    assert manifest.version == "0.1.0"
    assert catalog.installed("echo") is None
    assert catalog.list_installed() == []
    assert not (arena_home / "agents").exists()


def test_read_manifest_rejects_index_manifest_mismatch(local_catalog, arena_home):
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo:0.0.9")  # manifest file says 0.1.0
    with pytest.raises(CatalogError, match="mismatch"):
        catalog.read_manifest(entry, loaded.location)
    assert catalog.installed("echo") is None


def test_remove_installed(local_catalog):
    loaded = catalog.load_index()
    catalog.fetch_manifest(catalog.resolve(loaded.index, "echo"), loaded.location)
    assert catalog.remove_installed("echo") is True
    assert catalog.installed("echo") is None
    assert catalog.remove_installed("echo") is False


def _index_fixture_text() -> str:
    return (CATALOG / "index.json").read_text(encoding="utf-8")


def test_unreachable_url_falls_back_to_cache(arena_home, monkeypatch):
    url = "https://arena.example/index.json"
    monkeypatch.setenv("HB_ARENA_INDEX", url)
    text = _index_fixture_text()

    def ok(location, *a, **k):
        return httpx.Response(200, text=text, request=httpx.Request("GET", location))

    monkeypatch.setattr(catalog.httpx, "get", ok)
    catalog.load_index()  # populates the cache, keyed on `url`

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(catalog.httpx, "get", boom)
    loaded = catalog.load_index()
    assert loaded.stale is True
    assert loaded.index.agents[0].id == "echo"


def test_cache_from_one_url_is_not_served_for_a_different_url(arena_home, monkeypatch):
    text = _index_fixture_text()

    def ok(location, *a, **k):
        return httpx.Response(200, text=text, request=httpx.Request("GET", location))

    monkeypatch.setattr(catalog.httpx, "get", ok)
    monkeypatch.setenv("HB_ARENA_INDEX", "https://arena.example/a/index.json")
    catalog.load_index()  # populates the cache, keyed on the "a" URL

    monkeypatch.setenv("HB_ARENA_INDEX", "https://arena.example/b/index.json")

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(catalog.httpx, "get", boom)
    with pytest.raises(CatalogError, match="cannot load the arena catalog"):
        catalog.load_index()


def test_mistyped_local_path_raises_immediately_even_with_a_populated_cache(
    local_catalog, arena_home, monkeypatch
):
    catalog.load_index()  # populates the cache from the valid local path
    monkeypatch.setenv("HB_ARENA_INDEX", str(CATALOG.parent / "does-not-exist"))
    with pytest.raises(CatalogError, match="cannot load the arena catalog"):
        catalog.load_index()


def test_unreachable_without_cache_is_an_error(arena_home, monkeypatch):
    monkeypatch.setenv("HB_ARENA_INDEX", "https://arena.invalid/index.json")

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(catalog.httpx, "get", boom)
    with pytest.raises(CatalogError, match="cannot load the arena catalog"):
        catalog.load_index()


def test_index_needing_a_newer_hb_is_rejected(arena_home, tmp_path, monkeypatch):
    (tmp_path / "index.json").write_text(
        json.dumps({"schema_version": 1, "min_hb_version": "999.0.0", "agents": []})
    )
    monkeypatch.setattr(catalog, "__version__", "2.10.0")
    monkeypatch.setenv("HB_ARENA_INDEX", str(tmp_path))
    with pytest.raises(CatalogError, match="newer hb"):
        catalog.load_index()


def test_version_key_tolerates_prerelease_suffixes():
    assert catalog.version_key("2.11.0rc1") == (2, 11, 0)
    assert catalog.version_key("1.10.0") > catalog.version_key("1.9.9")


def test_version_key_pads_short_versions():
    assert catalog.version_key("2") == (2, 0, 0)
    assert catalog.version_key("2") == catalog.version_key("2.0.0")


# ── invalid content ──────────────────────────────────────────────────────


def test_invalid_index_json_raises_catalog_error(arena_home, tmp_path, monkeypatch):
    (tmp_path / "index.json").write_text("not valid json{{{", encoding="utf-8")
    monkeypatch.setenv("HB_ARENA_INDEX", str(tmp_path))
    with pytest.raises(CatalogError, match="invalid"):
        catalog.load_index()


def test_index_missing_required_keys_raises_catalog_error(arena_home, tmp_path, monkeypatch):
    (tmp_path / "index.json").write_text(json.dumps({"agents": "not-a-list"}), encoding="utf-8")
    monkeypatch.setenv("HB_ARENA_INDEX", str(tmp_path))
    with pytest.raises(CatalogError, match="invalid"):
        catalog.load_index()


def test_corrupt_cache_file_raises_catalog_error_not_a_leak(arena_home, monkeypatch):
    cache = catalog._cache_file()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{corrupt", encoding="utf-8")

    monkeypatch.setenv("HB_ARENA_INDEX", "https://arena.invalid/index.json")

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(catalog.httpx, "get", boom)
    with pytest.raises(CatalogError, match="cannot load the arena catalog"):
        catalog.load_index()


# ── _join: no local-file reads from remote catalogs ─────────────────────


def test_join_relative_resolves_against_url_base():
    assert (
        catalog._join("https://x.example/dir/index.json", "agents/echo/arena.yaml")
        == "https://x.example/dir/agents/echo/arena.yaml"
    )


def test_join_absolute_manifest_url_against_remote_base_does_not_read_local_files():
    assert catalog._join("https://x/i.json", "/etc/passwd") == "https://x/etc/passwd"


def test_join_local_base_still_resolves_relative_paths_on_disk():
    assert catalog._join("/a/b/index.json", "agents/echo/arena.yaml") == str(
        __import__("pathlib").Path("/a/b/agents/echo/arena.yaml")
    )


# ── fetch_manifest: compose path safety + atomic install ────────────────


def test_fetch_manifest_rejects_absolute_compose_path(local_catalog, arena_home, monkeypatch):
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo")
    manifest_text = (CATALOG / "agents/echo/arena.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(manifest_text)
    data["source"] = {"compose": "/etc/passwd", "service": "echo"}
    bad_text = yaml.safe_dump(data)

    def fake_read_text(location):
        if location == catalog._join(loaded.location, entry.manifest_url):
            return bad_text
        raise AssertionError(f"unexpected read: {location}")

    monkeypatch.setattr(catalog, "_read_text", fake_read_text)
    with pytest.raises(CatalogError, match="compose"):
        catalog.fetch_manifest(entry, loaded.location)


def test_fetch_manifest_rejects_compose_path_with_dotdot(local_catalog, arena_home, monkeypatch):
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo")
    manifest_text = (CATALOG / "agents/echo/arena.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(manifest_text)
    data["source"] = {"compose": "../../evil-compose.yml", "service": "echo"}
    bad_text = yaml.safe_dump(data)

    def fake_read_text(location):
        if location == catalog._join(loaded.location, entry.manifest_url):
            return bad_text
        raise AssertionError(f"unexpected read: {location}")

    monkeypatch.setattr(catalog, "_read_text", fake_read_text)
    with pytest.raises(CatalogError, match="compose"):
        catalog.fetch_manifest(entry, loaded.location)


def test_fetch_manifest_writes_compose_before_manifest_and_fetches_both_first(
    local_catalog, arena_home, monkeypatch
):
    """Atomic install: if the compose fetch fails, nothing is written at all."""
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo")
    manifest_text = (CATALOG / "agents/echo/arena.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(manifest_text)
    data["source"] = {"compose": "docker-compose.yml", "service": "echo"}
    manifest_with_compose = yaml.safe_dump(data)
    manifest_loc = catalog._join(loaded.location, entry.manifest_url)
    compose_loc = catalog._join(manifest_loc, "docker-compose.yml")

    def fake_read_text(location):
        if location == manifest_loc:
            return manifest_with_compose
        if location == compose_loc:
            raise OSError("compose unreachable")
        raise AssertionError(f"unexpected read: {location}")

    monkeypatch.setattr(catalog, "_read_text", fake_read_text)
    with pytest.raises(CatalogError, match="compose"):
        catalog.fetch_manifest(entry, loaded.location)

    target = catalog.agent_dir("echo", "0.1.0")
    assert not target.exists() or not (target / "arena.yaml").exists()


def test_fetch_manifest_removes_stale_compose_file_when_switching_to_image(
    local_catalog, arena_home
):
    loaded = catalog.load_index()
    entry = catalog.resolve(loaded.index, "echo")
    target = catalog.agent_dir("echo", "0.1.0")
    target.mkdir(parents=True, exist_ok=True)
    (target / "docker-compose.yml").write_text("stale: true", encoding="utf-8")

    manifest, agent_dir = catalog.fetch_manifest(entry, loaded.location)  # image-based fixture
    assert not (agent_dir / "docker-compose.yml").exists()


# ── installed()/remove_installed(): validate agent_id ────────────────────


def test_installed_rejects_invalid_agent_id(arena_home):
    assert catalog.installed("..") is None
    assert catalog.installed("not/a/valid id") is None


def test_remove_installed_rejects_dotdot_and_deletes_nothing(arena_home):
    agents_root = arena_home / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    sibling = agents_root.parent / "sentinel.txt"
    sibling.write_text("keep me", encoding="utf-8")

    with pytest.raises(CatalogError):
        catalog.remove_installed("..")

    assert sibling.exists()
    assert sibling.read_text(encoding="utf-8") == "keep me"


# ── list_installed(): tolerate one broken cached manifest ───────────────


def test_list_installed_skips_entries_with_a_broken_cached_manifest(local_catalog, arena_home):
    loaded = catalog.load_index()
    catalog.fetch_manifest(catalog.resolve(loaded.index, "echo"), loaded.location)

    broken_dir = arena_home / "agents" / "broken" / "0.1.0"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "arena.yaml").write_text("not: [valid, arena.yaml", encoding="utf-8")

    found = catalog.list_installed()
    assert [m.id for m in found] == ["echo"]
