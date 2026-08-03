# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""OpenAPI/Swagger specification parser for extracting bot capabilities."""

import json
from pathlib import Path
from typing import Any


class OpenAPIParser:
    """Parse OpenAPI/Swagger specifications to extract bot capabilities."""

    _MAX_REF_DEPTH = 32  # stack-depth backstop for allOf/$ref walks (not the cycle guard)

    def __init__(self, spec_path: str):
        """Initialize the parser.

        Args:
            spec_path: Path to the OpenAPI spec file (JSON or YAML).
        """
        self.spec_path = Path(spec_path).resolve()
        self._spec: dict[str, Any] | None = None
        # Cache complete schema property walks keyed by $ref string. Truncated
        # (cycle/depth) results must not be cached — see _walk_schema.
        self._props_cache: dict[str, tuple[dict[str, Any], list[str]]] = {}

    def parse(self) -> dict[str, Any] | None:
        """Parse the OpenAPI specification.

        Returns:
            Dictionary with extracted information or None if parsing failed.
        """
        try:
            content = self.spec_path.read_text(encoding="utf-8")
            suffix = self.spec_path.suffix.lower()

            if suffix == ".json":
                spec = json.loads(content)
            elif suffix in (".yaml", ".yml"):
                try:
                    import yaml

                    spec = yaml.safe_load(content)
                except ImportError:
                    # Try to parse as JSON anyway (some .yaml files are actually JSON)
                    try:
                        spec = json.loads(content)
                    except json.JSONDecodeError:
                        return None
            else:
                # Try JSON first, then YAML
                try:
                    spec = json.loads(content)
                except json.JSONDecodeError:
                    try:
                        import yaml

                        spec = yaml.safe_load(content)
                    except (ImportError, Exception):
                        return None

            if not isinstance(spec, dict):
                return None
            self._spec = spec
            self._props_cache.clear()
            return self._extract_from_spec(spec)

        except Exception:
            return None

    def _resolve_ref(
        self,
        node: Any,
        *,
        seen: frozenset[str] | None = None,
        depth: int = 0,
    ) -> Any:
        """Resolve a local JSON Pointer ``$ref`` against the loaded spec.

        Only document-local refs (``#/...``) are supported. Broken refs, cycles,
        and over-deep chains return ``None`` so extraction can skip them without
        aborting the whole parse.
        """
        if not isinstance(node, dict) or "$ref" not in node:
            return node
        if self._spec is None or depth >= self._MAX_REF_DEPTH:
            return None

        ref = node.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return None

        seen = seen or frozenset()
        if ref in seen:
            return None

        target: Any = self._spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(target, dict) and part in target:
                target = target[part]
            else:
                return None

        if isinstance(target, dict) and "$ref" in target:
            return self._resolve_ref(target, seen=seen | {ref}, depth=depth + 1)
        return target

    def _deref(self, node: Any) -> Any:
        """Return ``node`` with a single level of ``$ref`` resolved when present."""
        if isinstance(node, dict) and "$ref" in node:
            return self._resolve_ref(node)
        return node

    def _schema_properties(self, schema: Any) -> tuple[dict[str, Any], list[str]]:
        """Collect properties + required names from a schema, following refs/allOf."""
        properties, required, _ = self._walk_schema(schema)
        return properties, required

    def _walk_schema(
        self, schema: Any, *, seen: frozenset[str] = frozenset(), depth: int = 0
    ) -> tuple[dict[str, Any], list[str], bool]:
        """Walk a schema, returning (properties, required, complete).

        ``complete`` is False when a cycle or the depth cap truncated the walk;
        truncated results must not be cached, since the same schema may be
        reachable by a shorter path elsewhere in the document.
        """
        if depth >= self._MAX_REF_DEPTH:
            return {}, [], False

        ref_key = None
        if isinstance(schema, dict) and isinstance(schema.get("$ref"), str):
            ref_key = schema["$ref"]
            if ref_key in seen:
                return {}, [], False
            cached = self._props_cache.get(ref_key)
            if cached is not None:
                return dict(cached[0]), list(cached[1]), True
            seen = seen | {ref_key}

        schema = self._deref(schema)
        if not isinstance(schema, dict):
            return {}, [], True

        properties: dict[str, Any] = {}
        required: list[str] = []
        complete = True

        for part in schema.get("allOf") or []:
            part_props, part_req, part_complete = self._walk_schema(
                part, seen=seen, depth=depth + 1
            )
            complete = complete and part_complete
            properties.update(part_props)
            for name in part_req:
                if name not in required:
                    required.append(name)

        raw_props = schema.get("properties") or {}
        if isinstance(raw_props, dict):
            for name, prop in raw_props.items():
                resolved_prop = self._deref(prop)
                if isinstance(resolved_prop, dict):
                    properties[name] = resolved_prop

        for name in schema.get("required") or []:
            if isinstance(name, str) and name not in required:
                required.append(name)

        if ref_key is not None and complete:
            self._props_cache[ref_key] = (dict(properties), list(required))
        return properties, required, complete

    def _param_type(self, param: dict[str, Any]) -> str:
        schema = param.get("schema")
        if isinstance(schema, dict):
            resolved = self._deref(schema)
            if isinstance(resolved, dict) and resolved.get("type"):
                return str(resolved["type"])
        return str(param.get("type", "string"))

    def _extract_from_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Extract relevant information from parsed spec.

        Args:
            spec: Parsed OpenAPI specification.

        Returns:
            Dictionary with extracted information.
        """
        result = {
            "title": "",
            "description": "",
            "version": "",
            "operations": [],
            "servers": [],
        }

        # Handle both OpenAPI 3.x and Swagger 2.x
        info = spec.get("info", {})
        result["title"] = info.get("title", "")
        result["description"] = info.get("description", "")[:2000]
        result["version"] = info.get("version", "")

        # Extract servers (OpenAPI 3.x)
        servers = spec.get("servers", [])
        result["servers"] = [s.get("url", "") for s in servers if isinstance(s, dict)]

        # Extract base path (Swagger 2.x)
        if not result["servers"]:
            host = spec.get("host", "")
            base_path = spec.get("basePath", "")
            schemes = spec.get("schemes", ["https"])
            if host:
                result["servers"] = [f"{schemes[0]}://{host}{base_path}"]

        # Extract operations from paths
        paths = spec.get("paths", {})
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            for method in ["get", "post", "put", "delete", "patch", "options", "head"]:
                operation = path_item.get(method)
                if not operation:
                    continue

                op_info = {
                    "path": path,
                    "method": method.upper(),
                    "operationId": operation.get("operationId", ""),
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", "")[:500],
                    "tags": operation.get("tags", []),
                    "parameters": self._extract_parameters(operation, path_item),
                    "responses": self._extract_responses(operation),
                }

                result["operations"].append(op_info)

        return result

    def _extract_parameters(self, operation: dict, path_item: dict) -> list[dict]:
        """Extract parameters from an operation.

        Args:
            operation: Operation object.
            path_item: Path item object (for shared parameters).

        Returns:
            List of parameter definitions.
        """
        params: list[dict] = []
        seen: dict[tuple[str, str], int] = {}

        # Path-level first, then operation-level — OpenAPI 3: same (name, in)
        # at operation level overrides the path-level parameter.
        all_params = path_item.get("parameters", []) + operation.get("parameters", [])

        for param in all_params:
            if not isinstance(param, dict):
                continue

            resolved = self._deref(param)
            if not isinstance(resolved, dict) or "name" not in resolved:
                # Broken or cyclic $ref — skip rather than aborting the parse.
                continue

            entry = {
                "name": resolved.get("name", ""),
                "in": resolved.get("in", ""),
                "required": resolved.get("required", False),
                "description": str(resolved.get("description", ""))[:200],
                "type": self._param_type(resolved),
            }
            key = (str(entry["name"]), str(entry["in"]))
            if key in seen:
                params[seen[key]] = entry
            else:
                seen[key] = len(params)
                params.append(entry)

        # Extract request body parameters (OpenAPI 3.x)
        request_body = operation.get("requestBody", {})
        request_body = self._deref(request_body) or {}
        if isinstance(request_body, dict) and request_body:
            content = request_body.get("content", {})
            if not isinstance(content, dict):
                content = {}
            json_content = content.get("application/json", {})
            if not isinstance(json_content, dict):
                json_content = {}
            schema = json_content.get("schema", {})
            properties, required = self._schema_properties(schema)

            for name, prop in properties.items():
                params.append(
                    {
                        "name": name,
                        "in": "body",
                        "required": name in required,
                        "description": str(prop.get("description", ""))[:200],
                        "type": str(prop.get("type", "string")),
                    }
                )

        return params

    def _extract_responses(self, operation: dict) -> dict[str, str]:
        """Extract response descriptions from an operation.

        Args:
            operation: Operation object.

        Returns:
            Dictionary of status code to description.
        """
        responses = {}

        for status, response in operation.get("responses", {}).items():
            if not isinstance(response, dict):
                continue
            resolved = self._deref(response)
            if isinstance(resolved, dict):
                responses[str(status)] = str(resolved.get("description", ""))[:200]

        return responses

    def to_intents(self) -> dict[str, list[str]]:
        """Convert parsed spec to permitted/restricted intents.

        Returns:
            Dictionary with permitted and restricted intent lists.
        """
        result = self.parse()
        if not result:
            return {"permitted": [], "restricted": []}

        permitted = []
        for op in result.get("operations", []):
            summary = op.get("summary") or op.get("operationId") or f"{op['method']} {op['path']}"
            permitted.append(summary)

        return {
            "permitted": permitted,
            "restricted": ["Operations not defined in the API specification"],
        }
