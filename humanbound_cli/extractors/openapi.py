# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""OpenAPI/Swagger specification parser for extracting bot capabilities."""

import json
from pathlib import Path
from typing import Any


class OpenAPIParser:
    """Parse OpenAPI/Swagger specifications to extract bot capabilities."""

    def __init__(self, spec_path: str):
        """Initialize the parser.

        Args:
            spec_path: Path to the OpenAPI spec file (JSON or YAML).
        """
        self.spec_path = Path(spec_path).resolve()

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

            return self._extract_from_spec(spec)

        except Exception:
            return None

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
        params = []

        # Combine path-level and operation-level parameters
        all_params = path_item.get("parameters", []) + operation.get("parameters", [])

        for param in all_params:
            if not isinstance(param, dict):
                continue

            # Handle $ref (simplified - doesn't resolve refs)
            if "$ref" in param:
                continue

            params.append(
                {
                    "name": param.get("name", ""),
                    "in": param.get("in", ""),
                    "required": param.get("required", False),
                    "description": param.get("description", "")[:200],
                    "type": param.get("schema", {}).get("type", param.get("type", "string")),
                }
            )

        # Extract request body parameters (OpenAPI 3.x)
        request_body = operation.get("requestBody", {})
        if request_body:
            content = request_body.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema", {})

            if schema.get("properties"):
                for name, prop in schema.get("properties", {}).items():
                    params.append(
                        {
                            "name": name,
                            "in": "body",
                            "required": name in schema.get("required", []),
                            "description": prop.get("description", "")[:200],
                            "type": prop.get("type", "string"),
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
            if isinstance(response, dict):
                responses[str(status)] = response.get("description", "")[:200]

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
