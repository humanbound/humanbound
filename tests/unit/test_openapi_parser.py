# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""OpenAPI $ref resolution for capability extraction."""

import json
from pathlib import Path

import pytest

from humanbound_cli.extractors.openapi import OpenAPIParser


def _write_spec(tmp_path: Path, spec: dict, name: str = "openapi.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_inline_parameters_still_work(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Inline", "version": "1.0.0"},
        "paths": {
            "/echo": {
                "post": {
                    "summary": "Echo",
                    "parameters": [
                        {
                            "name": "verbose",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean"},
                        }
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["text"],
                                    "properties": {
                                        "text": {"type": "string", "description": "msg"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    assert result is not None
    params = {p["name"]: p for p in result["operations"][0]["parameters"]}
    assert params["verbose"]["in"] == "query"
    assert params["verbose"]["type"] == "boolean"
    assert params["text"]["in"] == "body"
    assert params["text"]["required"] is True


def test_resolves_component_parameter_ref(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "RefParams", "version": "1.0.0"},
        "components": {
            "parameters": {
                "IdParam": {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "description": "Resource id",
                    "schema": {"type": "integer"},
                }
            }
        },
        "paths": {
            "/items/{id}": {
                "parameters": [{"$ref": "#/components/parameters/IdParam"}],
                "get": {
                    "operationId": "getItem",
                    "summary": "Get item",
                    "responses": {"200": {"description": "ok"}},
                },
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    assert result is not None
    params = result["operations"][0]["parameters"]
    assert len(params) == 1
    assert params[0]["name"] == "id"
    assert params[0]["in"] == "path"
    assert params[0]["required"] is True
    assert params[0]["type"] == "integer"
    assert params[0]["description"] == "Resource id"


def test_resolves_request_body_schema_ref(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "RefBody", "version": "1.0.0"},
        "components": {
            "schemas": {
                "Message": {
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string", "description": "user text"},
                        "temperature": {"type": "number"},
                    },
                }
            }
        },
        "paths": {
            "/chat": {
                "post": {
                    "summary": "Chat",
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Message"}}
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    params = {p["name"]: p for p in result["operations"][0]["parameters"]}
    assert params["content"]["in"] == "body"
    assert params["content"]["required"] is True
    assert params["content"]["type"] == "string"
    assert params["temperature"]["type"] == "number"


def test_resolves_nested_schema_property_ref(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Nested", "version": "1.0.0"},
        "components": {
            "schemas": {
                "Prompt": {"type": "string", "description": "prompt text"},
                "Request": {
                    "type": "object",
                    "properties": {
                        "prompt": {"$ref": "#/components/schemas/Prompt"},
                    },
                },
            }
        },
        "paths": {
            "/run": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Request"}}
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    params = result["operations"][0]["parameters"]
    assert params[0]["name"] == "prompt"
    assert params[0]["type"] == "string"
    assert params[0]["description"] == "prompt text"


def test_allof_merges_properties(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "AllOf", "version": "1.0.0"},
        "components": {
            "schemas": {
                "Base": {
                    "type": "object",
                    "properties": {"role": {"type": "string"}},
                    "required": ["role"],
                },
                "Ext": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Base"},
                        {
                            "type": "object",
                            "properties": {"content": {"type": "string"}},
                        },
                    ]
                },
            }
        },
        "paths": {
            "/x": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Ext"}}
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    names = {p["name"] for p in result["operations"][0]["parameters"]}
    assert names == {"role", "content"}


def test_cyclic_allof_does_not_discard_spec(tmp_path):
    """Mutually-referential allOf must not RecursionError / return None from parse()."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "CycleAllOf", "version": "1.0.0"},
        "components": {
            "schemas": {
                "A": {
                    "allOf": [{"$ref": "#/components/schemas/B"}],
                    "properties": {"a": {"type": "string"}},
                },
                "B": {
                    "allOf": [{"$ref": "#/components/schemas/A"}],
                    "properties": {"b": {"type": "string"}},
                },
            }
        },
        "paths": {
            "/x": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/A"}}
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    assert result is not None
    names = {p["name"] for p in result["operations"][0]["parameters"]}
    assert names == {"a", "b"}


def test_operation_parameter_overrides_path_level_same_name_in(tmp_path):
    """OpenAPI 3: operation-level (name, in) wins over path-level."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Override", "version": "1.0.0"},
        "components": {
            "parameters": {
                "SharedId": {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "description": "shared",
                    "schema": {"type": "integer"},
                }
            }
        },
        "paths": {
            "/items/{id}": {
                "parameters": [{"$ref": "#/components/parameters/SharedId"}],
                "get": {
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "description": "overridden",
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                },
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    params = result["operations"][0]["parameters"]
    assert len(params) == 1
    assert params[0]["name"] == "id"
    assert params[0]["type"] == "string"
    assert params[0]["description"] == "overridden"


def test_allof_fanout_is_cached_not_exponential(tmp_path):
    """Sibling allOf branches that re-enter the same $ref must not explode runtime."""
    schemas = {
        f"N{i}": {
            "allOf": [
                {"$ref": f"#/components/schemas/N{i + 1}"},
                {"$ref": f"#/components/schemas/N{i + 1}"},
            ],
            "properties": {f"p{i}": {"type": "string"}},
        }
        for i in range(20)
    }
    schemas["N20"] = {"properties": {"leaf": {"type": "string"}}}
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "FanOut", "version": "1.0.0"},
        "components": {"schemas": schemas},
        "paths": {
            "/x": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/N0"}}
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    import time

    started = time.perf_counter()
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    elapsed = time.perf_counter() - started
    assert result is not None
    assert elapsed < 1.0, f"fan-out walk too slow: {elapsed:.3f}s"
    names = {p["name"] for p in result["operations"][0]["parameters"]}
    assert "leaf" in names
    assert "p0" in names


def test_cyclic_ref_does_not_loop(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Cycle", "version": "1.0.0"},
        "components": {
            "parameters": {
                "A": {"$ref": "#/components/parameters/B"},
                "B": {"$ref": "#/components/parameters/A"},
            }
        },
        "paths": {
            "/loop": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/A"}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    assert result is not None
    # Cycle is skipped, not fatal.
    assert result["operations"][0]["parameters"] == []


def test_broken_ref_is_skipped(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Broken", "version": "1.0.0"},
        "paths": {
            "/x": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/Missing"}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    assert result["operations"][0]["parameters"] == []


def test_swagger2_parameter_ref(tmp_path):
    spec = {
        "swagger": "2.0",
        "info": {"title": "Swagger", "version": "1.0.0"},
        "host": "api.example.com",
        "basePath": "/v1",
        "schemes": ["https"],
        "parameters": {
            "Q": {
                "name": "q",
                "in": "query",
                "type": "string",
                "required": True,
            }
        },
        "paths": {
            "/search": {
                "get": {
                    "summary": "Search",
                    "parameters": [{"$ref": "#/parameters/Q"}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    assert result["servers"] == ["https://api.example.com/v1"]
    params = result["operations"][0]["parameters"]
    assert params[0]["name"] == "q"
    assert params[0]["type"] == "string"


def test_resolves_response_ref_description(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Resp", "version": "1.0.0"},
        "components": {
            "responses": {
                "NotFound": {"description": "Missing resource"},
            }
        },
        "paths": {
            "/x": {
                "get": {
                    "responses": {
                        "404": {"$ref": "#/components/responses/NotFound"},
                    }
                }
            }
        },
    }
    result = OpenAPIParser(str(_write_spec(tmp_path, spec))).parse()
    assert result["operations"][0]["responses"]["404"] == "Missing resource"


def test_to_intents_includes_ref_backed_operations(tmp_path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Intents", "version": "1.0.0"},
        "components": {
            "parameters": {
                "IdParam": {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            }
        },
        "paths": {
            "/agents/{id}": {
                "get": {
                    "summary": "Fetch agent",
                    "parameters": [{"$ref": "#/components/parameters/IdParam"}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    intents = OpenAPIParser(str(_write_spec(tmp_path, spec))).to_intents()
    assert "Fetch agent" in intents["permitted"]


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("yaml") is None,
    reason="PyYAML not installed",
)
def test_yaml_spec_with_refs(tmp_path):
    import yaml

    spec = {
        "openapi": "3.0.3",
        "info": {"title": "YAML", "version": "1.0.0"},
        "components": {
            "parameters": {
                "Token": {
                    "name": "token",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                }
            }
        },
        "paths": {
            "/secure": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/Token"}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    path = tmp_path / "openapi.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    result = OpenAPIParser(str(path)).parse()
    assert result["operations"][0]["parameters"][0]["name"] == "token"
