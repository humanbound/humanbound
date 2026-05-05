# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Parser for the --capabilities flag value.

Accepted syntax:
    tools=on,memory=off
    tools=true,memory=false
    tools                    (bare key implies on)
    tools=1,memory=0
    all=off,tools=on         (left-to-right merge; all=on/off shorthand)
"""

from __future__ import annotations

from humanbound_cli.extractors.capabilities import CAPABILITY_KEYS

_TRUE = {"on", "true", "1", "yes"}
_FALSE = {"off", "false", "0", "no"}
_VALID_KEYS = set(CAPABILITY_KEYS) | {"all"}


def parse_capabilities_spec(spec: str) -> dict[str, bool]:
    """Parse a --capabilities value into a dict of {capability: bool}.

    Raises ValueError on unknown keys, unparseable values, or empty spec.
    For 'all=on/off', expands to all four CAPABILITY_KEYS. Pairs apply
    left-to-right; later pairs override earlier ones.
    """
    if not spec or not spec.strip():
        raise ValueError("--capabilities requires at least one key=value pair")

    result: dict[str, bool] = {}

    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        if "=" in item:
            key, _, val = item.partition("=")
            key = key.strip().lower()
            val = val.strip().lower()
        else:
            key = item.lower()
            val = "on"

        if key not in _VALID_KEYS:
            raise ValueError(
                f"Unknown capability: {key!r}. Valid: {', '.join(sorted(_VALID_KEYS))}"
            )

        if val in _TRUE:
            bool_val = True
        elif val in _FALSE:
            bool_val = False
        else:
            raise ValueError(
                f"Unparseable value {val!r} for {key}. "
                f"accepted forms: on/off, true/false, 1/0, yes/no"
            )

        if key == "all":
            for k in CAPABILITY_KEYS:
                result[k] = bool_val
        else:
            result[key] = bool_val

    return result
