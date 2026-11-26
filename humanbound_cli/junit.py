# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""JUnit XML export for adversarial test logs.

Almost every CI system renders JUnit XML natively (GitHub Actions via test
reporter actions, GitLab merge requests, Jenkins, Azure DevOps, CircleCI,
Buildkite), so a red-team run can show up next to the unit tests. Each judged
conversation becomes one ``<testcase>``; conversations are grouped into one
``<testsuite>`` per attack category, so a report reads like
"prompt_injection: 2 failures out of 14".

Verdict mapping:

- ``pass``  -> passing test case
- ``fail``  -> ``<failure>``: the agent did something it shouldn't have
- ``error`` -> ``<error>``: the conversation could not be run or judged,
  which may hide a finding, so it must not read as green
- anything else -> ``<skipped>`` with the raw verdict in the message

The input is the list of log dicts the CLI already handles: local
``logs.jsonl`` entries (``LogEntry`` shape, with a ``conversation`` of
``{"u", "a"}`` turns) and platform log records (which may carry flat
``prompt``/``response`` fields instead).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .engine.schemas import severity_to_label

#: Longest explanation kept in a ``failure``/``error`` message attribute.
#: The full text always goes in the element body; CI UIs show the message
#: on one line, so a short one reads better.
MESSAGE_MAX_CHARS = 200

_UNCATEGORIZED = "uncategorized"

# Characters XML 1.0 forbids even when escaped. LLM output can contain them
# (stray NULs, ANSI escapes), and a single one makes the whole report
# unparseable, so the CI job would silently show no tests at all.
_ILLEGAL_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return _ILLEGAL_XML_CHARS.sub("�", str(value))


def _one_line(text: str, limit: int = MESSAGE_MAX_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def severity_label(severity: Any) -> str:
    """Return a label (critical/high/medium/low/info) for a log's severity.

    Logs carry a 0-100 score; some sources already carry the label.
    """
    number = _number(severity)
    if number is not None:
        return severity_to_label(number)
    if isinstance(severity, str) and severity.strip():
        return severity.strip().lower()
    return "info"


def _category(log: Mapping[str, Any]) -> str:
    for key in ("gen_category", "test_category"):
        value = log.get(key)
        if value:
            return str(value)
    return _UNCATEGORIZED


def _case_name(log: Mapping[str, Any], index: int) -> str:
    for key in ("thread_id", "id", "test_name"):
        value = log.get(key)
        if value:
            return str(value)
    return f"conversation-{index}"


def _transcript(log: Mapping[str, Any]) -> str:
    """Render the conversation as plain text, one turn per block."""
    lines: list[str] = []
    conversation = log.get("conversation") or []
    if isinstance(conversation, list) and conversation:
        for turn_no, turn in enumerate(conversation, start=1):
            if isinstance(turn, Mapping):
                user, agent = turn.get("u", ""), turn.get("a", "")
            else:
                user, agent = getattr(turn, "u", ""), getattr(turn, "a", "")
            lines.append(f"[turn {turn_no}] user:\n{user}")
            lines.append(f"[turn {turn_no}] agent:\n{agent}")
    elif log.get("prompt") or log.get("response"):
        lines.append(f"user:\n{log.get('prompt', '')}")
        lines.append(f"agent:\n{log.get('response', '')}")
    return "\n\n".join(lines)


def _finding_body(log: Mapping[str, Any], label: str) -> str:
    parts = [f"severity: {label}"]
    number = _number(log.get("severity"))
    if number is not None:
        parts[0] += f" ({number:g}/100)"
    if log.get("fail_category"):
        parts.append(f"category: {log['fail_category']}")
    confidence = _number(log.get("confidence"))
    if confidence is not None:
        parts.append(f"judge confidence: {confidence:g}")
    if log.get("explanation"):
        parts.append("")
        parts.append(str(log["explanation"]))
    return _clean("\n".join(parts))


def _add_property(props: ET.Element, name: str, value: Any) -> None:
    if value is None or value == "":
        return
    ET.SubElement(props, "property", name=name, value=_clean(value))


def _build_case(log: Mapping[str, Any], index: int, category: str) -> tuple[ET.Element, str]:
    """Build one ``<testcase>``; returns it with its outcome
    (passed/failure/error/skipped)."""
    exec_t = _number(log.get("exec_t")) or 0.0
    case = ET.Element(
        "testcase",
        name=_clean(_case_name(log, index)),
        classname=_clean(f"humanbound.{category}"),
        time=f"{max(exec_t, 0.0):.3f}",
    )

    label = severity_label(log.get("severity"))
    props = ET.SubElement(case, "properties")
    _add_property(props, "verdict", log.get("result"))
    _add_property(props, "severity", label)
    _add_property(props, "severity_score", log.get("severity"))
    _add_property(props, "fail_category", log.get("fail_category"))
    _add_property(props, "confidence", log.get("confidence"))
    if not len(props):
        case.remove(props)

    verdict = str(log.get("result") or "").strip().lower()
    explanation = _one_line(_clean(log.get("explanation")))
    fail_category = _clean(log.get("fail_category")) or category

    if verdict == "fail":
        outcome = "failure"
        message = f"[{label.upper()}] {fail_category}"
        if explanation:
            message += f": {explanation}"
        node = ET.SubElement(case, "failure", message=message, type=fail_category)
        node.text = _finding_body(log, label)
    elif verdict == "error":
        outcome = "error"
        message = explanation or "conversation could not be run or judged"
        node = ET.SubElement(case, "error", message=message, type=fail_category)
        node.text = _finding_body(log, label)
    elif verdict == "pass":
        outcome = "passed"
    else:
        outcome = "skipped"
        ET.SubElement(
            case, "skipped", message=f"unknown verdict: {_clean(log.get('result')) or '(none)'}"
        )

    transcript = _transcript(log)
    if transcript:
        out = ET.SubElement(case, "system-out")
        out.text = _clean(transcript)

    return case, outcome


def logs_to_junit(
    logs: Iterable[Mapping[str, Any]],
    *,
    suite_name: str = "humanbound",
    timestamp: datetime | None = None,
) -> str:
    """Render adversarial test logs as a JUnit XML document.

    Args:
        logs: log entries, local (``LogEntry`` dicts) or platform records.
        suite_name: name of the root ``<testsuites>`` element, usually the
            experiment name.
        timestamp: when the run happened; defaults to now (UTC).

    Returns:
        The XML document as a string, with an XML declaration.
    """
    stamp = (timestamp or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()

    root = ET.Element("testsuites", name=_clean(suite_name))
    suites: OrderedDict[str, ET.Element] = OrderedDict()
    counts: dict[str, dict[str, float]] = {}
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}

    for index, log in enumerate(logs, start=1):
        category = _category(log)
        if category not in suites:
            suites[category] = ET.SubElement(
                root, "testsuite", name=_clean(category), timestamp=stamp
            )
            counts[category] = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}

        case, outcome = _build_case(log, index, category)
        suites[category].append(case)

        bucket = counts[category]
        bucket["tests"] += 1
        bucket["time"] += float(case.get("time", "0"))
        if outcome == "failure":
            bucket["failures"] += 1
        elif outcome == "error":
            bucket["errors"] += 1
        elif outcome == "skipped":
            bucket["skipped"] += 1

    for category, suite in suites.items():
        bucket = counts[category]
        suite.set("tests", str(int(bucket["tests"])))
        suite.set("failures", str(int(bucket["failures"])))
        suite.set("errors", str(int(bucket["errors"])))
        suite.set("skipped", str(int(bucket["skipped"])))
        suite.set("time", f"{bucket['time']:.3f}")
        for key in totals:
            totals[key] += bucket[key]

    root.set("tests", str(int(totals["tests"])))
    root.set("failures", str(int(totals["failures"])))
    root.set("errors", str(int(totals["errors"])))
    root.set("skipped", str(int(totals["skipped"])))
    root.set("time", f"{totals['time']:.3f}")

    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
