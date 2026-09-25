# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Build the humanbound-firewall policy file (agent.yaml) from a local scope.

Local runs and scope files describe an agent as
``{overall_business_scope, intents: {permitted, restricted}, more_info, capabilities}``;
the firewall reads ``scope.business``, ``scope.more_info``, top-level ``intents`` and a
``capabilities`` list. Logged-in exports come from the platform as-is and do not pass
through here.
"""

from __future__ import annotations

from pathlib import Path

from .extractors.capabilities import CAPABILITY_KEYS


def load_scope_file(path: str) -> dict:
    """Read a scope file (YAML or JSON, as `hb test --scope` takes) with its capabilities.

    Raises ValueError when the file cannot be parsed or declares unknown capabilities.
    """
    import yaml

    from .engine.scope import from_scope_file

    try:
        scope = from_scope_file(path)
        raw = yaml.safe_load(Path(path).read_text()) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Could not parse scope file {path}: {e}") from e
    if scope is None:
        raise ValueError(f"Could not read scope file: {path}")

    capabilities = raw.get("capabilities") if isinstance(raw, dict) else None
    if capabilities is not None:
        if not isinstance(capabilities, dict):
            raise ValueError(
                "'capabilities' in the scope file must be a mapping of name: true|false"
            )
        unknown = sorted(set(capabilities) - set(CAPABILITY_KEYS))
        if unknown:
            raise ValueError(
                f"Unknown capability key(s) in the scope file: {', '.join(unknown)}. "
                f"Valid: {', '.join(CAPABILITY_KEYS)}"
            )
        scope["capabilities"] = dict(capabilities)
    return scope


def build_agent_yaml(scope: dict) -> dict:
    """Map a local scope to the firewall's agent.yaml layout.

    Only capabilities the firewall knows are kept; a scope that declares none leaves the key
    out so the firewall applies its own default.
    """
    intents = scope.get("intents") or {}
    doc: dict = {
        "version": "1.0",
        "scope": {
            "business": scope.get("overall_business_scope") or "",
            "more_info": scope.get("more_info") or "",
        },
        "intents": {
            "permitted": _as_list(intents.get("permitted")),
            "restricted": _as_list(intents.get("restricted")),
        },
    }
    capabilities = scope.get("capabilities")
    if capabilities is not None:
        doc["capabilities"] = [k for k in CAPABILITY_KEYS if capabilities.get(k)]
    return doc


def dump_agent_yaml(doc: dict, source: str) -> str:
    """Render agent.yaml with a short header naming where it came from."""
    import yaml

    header = (
        f"# humanbound-firewall policy file, exported by hb guardrails from {source}.\n"
        "# Add settings: and tools: for your deployment.\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.split("\n") if line.strip()]
    return [str(v) for v in value or []]
