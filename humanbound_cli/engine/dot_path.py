# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Dot-path lookup into nested JSON, shared by every config field that points into
an agent's messages (telemetry extraction maps, stream response rules)."""


def get_path(data, path):
    """Value at `path` in nested dicts/lists, or None if it is not there.

    "a.b" reads dict keys, "items[0]" a list index, "items[*]" the list itself.
    """
    if not path or data is None:
        return None

    try:
        parts = path.split(".")
        current = data

        for part in parts:
            # Handle array notation like "items[*]" or "items[0]"
            if "[" in part and "]" in part:
                key = part.split("[")[0]
                index_part = part.split("[")[1].split("]")[0]

                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return None

                # Handle wildcard [*] - return the list itself for iteration
                if index_part == "*":
                    return current if isinstance(current, list) else None
                # Handle specific index
                else:
                    idx = int(index_part)
                    if isinstance(current, list) and 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return None
            else:
                # Regular dict navigation
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None

        return current

    except Exception:
        return None
