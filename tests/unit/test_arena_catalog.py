# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import json

import httpx
import pytest
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import catalog
from humanbound_cli.arena.catalog import CatalogError

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


def test_remove_installed(local_catalog):
    loaded = catalog.load_index()
    catalog.fetch_manifest(catalog.resolve(loaded.index, "echo"), loaded.location)
    assert catalog.remove_installed("echo") is True
    assert catalog.installed("echo") is None
    assert catalog.remove_installed("echo") is False


def test_unreachable_url_falls_back_to_cache(local_catalog, monkeypatch):
    catalog.load_index()  # populates the cache
    monkeypatch.setenv("HB_ARENA_INDEX", "https://arena.invalid/index.json")

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(catalog.httpx, "get", boom)
    loaded = catalog.load_index()
    assert loaded.stale is True
    assert loaded.index.agents[0].id == "echo"


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
