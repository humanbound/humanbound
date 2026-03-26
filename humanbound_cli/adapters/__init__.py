"""Log adapters — convert external framework results to hb-firewall format.

Auto-detects format from file structure. Add new adapters by creating a module
with SIGNATURES (list of keys to match) and convert(data) → list[dict].
"""

import json
from pathlib import Path

from . import promptfoo, pyrit

_ADAPTERS = {
    "promptfoo": promptfoo,
    "pyrit": pyrit,
}


def detect_format(data: dict) -> str:
    """Auto-detect framework from file structure."""
    for name, adapter in _ADAPTERS.items():
        sigs = getattr(adapter, "SIGNATURES", [])
        if sigs and all(k in data for k in sigs):
            return name
    return ""


def convert_file(file_path: str, format_tag: str = "") -> list[dict]:
    """Convert an external log file to hb-firewall standard format.

    Args:
        file_path: path to JSON file
        format_tag: explicit format (e.g. "promptfoo", "pyrit"). Auto-detects if empty.

    Returns:
        list of logs in standard format:
        [{"conversation": [...], "result": "pass"|"fail", "test_category": "...",
          "fail_category": "...", "severity": float, "confidence": float}, ...]
    """
    path = Path(file_path)

    if path.suffix == ".jsonl":
        with open(path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        # JSONL: treat as list of individual results
        data = {"_jsonl_entries": lines}
    else:
        with open(path) as f:
            data = json.load(f)

    tag = format_tag or detect_format(data)
    if not tag:
        available = ", ".join(_ADAPTERS.keys())
        raise ValueError(
            f"Unrecognized format in '{file_path}'. "
            f"Specify format: --import {file_path}:<format> "
            f"(available: {available})")

    if tag not in _ADAPTERS:
        available = ", ".join(_ADAPTERS.keys())
        raise ValueError(f"Unknown format '{tag}'. Available: {available}")

    return _ADAPTERS[tag].convert(data)


def list_formats() -> list[str]:
    return list(_ADAPTERS.keys())
