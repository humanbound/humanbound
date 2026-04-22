# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""PyRIT (Microsoft) adapter — converts red teaming scan results to humanbound-firewall format."""

SIGNATURES = ["redteaming_data"]

SEVERITY_MAP = {
    "very low": 10,
    "low": 30,
    "medium": 50,
    "high": 75,
    "very high": 95,
}


def convert(data: dict) -> list[dict]:
    logs = []
    for entry in data.get("redteaming_data", []):
        conv = []
        for msg in entry.get("conversation", []):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                conv.append({"u": content, "a": ""})
            elif role == "assistant" and conv:
                conv[-1]["a"] = content

        if not conv:
            continue

        attack_success = entry.get("attack_success", False)
        risk_cat = entry.get("risk_category", "")

        # Extract max severity from risk_assessment
        severity = 0
        risk_assessment = entry.get("risk_assessment", {})
        for cat_info in risk_assessment.values():
            if isinstance(cat_info, dict):
                label = cat_info.get("severity_label", "").lower()
                severity = max(severity, SEVERITY_MAP.get(label, 0))

        logs.append(
            {
                "conversation": conv,
                "result": "fail" if attack_success else "pass",
                "test_category": "adversarial",
                "fail_category": risk_cat if attack_success else "",
                "severity": float(severity),
                "confidence": 90.0,
                "gen_category": entry.get("attack_technique", ""),
            }
        )

    return logs
