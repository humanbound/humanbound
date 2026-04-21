# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""PromptFoo adapter — converts evaluation results to hb-firewall format.

Handles the export format from: promptfoo export eval <id> -o results.json
"""

SIGNATURES = ["results", "evalId"]


def convert(data: dict) -> list[dict]:
    logs = []
    results = data.get("results", {})

    for entry in results.get("results", []):
        # Extract prompt text
        prompt_obj = entry.get("prompt", {})
        if isinstance(prompt_obj, dict):
            prompt = prompt_obj.get("raw", prompt_obj.get("label", ""))
        else:
            prompt = str(prompt_obj)

        # Extract response text
        response_obj = entry.get("response", {})
        if isinstance(response_obj, dict):
            response = response_obj.get("output", "")
        else:
            response = str(response_obj)

        if not prompt:
            continue

        success = entry.get("success", True)
        score = entry.get("score", 1.0 if success else 0.0)

        # Extract fail reason from grading
        fail_category = ""
        grading = entry.get("gradingResult", {})
        if grading and not success:
            fail_category = grading.get("reason", "")[:80]

        # Map score to severity (0 = benign, 1 = severe)
        if isinstance(score, (int, float)) and score <= 1.0:
            severity = float((1.0 - score) * 100)
        else:
            severity = 50.0

        logs.append({
            "conversation": [{"u": prompt, "a": response}],
            "result": "pass" if success else "fail",
            "test_category": "adversarial",
            "fail_category": fail_category,
            "severity": severity,
            "confidence": 80.0,
            "gen_category": "promptfoo",
        })

    return logs
