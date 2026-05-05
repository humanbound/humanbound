# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""HTML report generator — platform-branded, self-contained.

Uses the same template and styling as the platform's report_base.html.
Same look-and-feel, same methodology text, same branding.
Data comes from local experiment results instead of database queries.
"""

import base64
import os
from datetime import datetime, timezone
from html import escape
from string import Template

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

GRADE_COLORS = {
    "A": "#22c55e",
    "B": "#84cc16",
    "C": "#eab308",
    "D": "#f97316",
    "F": "#ef4444",
}

GRADE_BOUNDARIES = [
    (90, "A"),
    (75, "B"),
    (60, "C"),
    (40, "D"),
    (0, "F"),
]

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def _score_to_grade(score):
    for threshold, grade in GRADE_BOUNDARIES:
        if score >= threshold:
            return grade
    return "F"


def _grade_color(grade):
    return GRADE_COLORS.get(grade, "#6b7280")


def _sanitize(text):
    if text is None:
        return ""
    return escape(str(text))


def _get_logo_data_uri():
    try:
        path = os.path.join(TEMPLATES_DIR, "logo.svg")
        with open(path, "rb") as f:
            return "data:image/svg+xml;base64," + base64.b64encode(f.read()).decode()
    except Exception:
        return ""


def _severity_to_label(severity):
    if isinstance(severity, str):
        return severity
    if severity >= 75:
        return "critical"
    elif severity >= 50:
        return "high"
    elif severity >= 25:
        return "medium"
    elif severity >= 1:
        return "low"
    return "info"


# ── Visual Helpers (ported from platform) ──────────────────────────


def _build_donut(label, score, grade):
    color = _grade_color(grade)
    circumference = 226.2
    filled = circumference * (score / 100.0)
    return (
        f'<div class="posture-item">'
        f'<svg width="100" height="100" viewBox="0 0 100 100">'
        f'<circle class="donut-ring" cx="50" cy="50" r="36"/>'
        f'<circle class="donut-fill" cx="50" cy="50" r="36" '
        f'stroke="{color}" stroke-dasharray="{filled:.1f} {circumference:.1f}" '
        f'transform="rotate(-90 50 50)"/>'
        f'<text x="50" y="46" text-anchor="middle" font-size="22" font-weight="800" '
        f'fill="{color}" font-family="-apple-system, sans-serif">{score:.0f}</text>'
        f'<text x="50" y="60" text-anchor="middle" font-size="12" font-weight="700" '
        f'fill="{color}" font-family="-apple-system, sans-serif">{grade}</text>'
        f"</svg>"
        f'<div class="donut-label">{label}</div>'
        f"</div>"
    )


def _build_severity_bar(by_severity):
    total = sum(by_severity.values())
    if total == 0:
        return ""
    bar = '<div class="severity-bar">'
    for sev in SEVERITY_ORDER:
        count = by_severity.get(sev, 0)
        if count == 0:
            continue
        pct = count / total * 100
        bar += f'<div class="seg seg-{sev}" style="width:{pct:.1f}%">{count}</div>'
    bar += "</div>"
    return bar


def _render_conversation(conversation):
    if not conversation:
        return ""
    html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:12px; margin-top:8px; font-size:12px;">'
    for i, turn in enumerate(conversation):
        u = turn.get("u", "")
        a = turn.get("a", "")
        if u:
            html += (
                f'<div style="margin-bottom:8px;">'
                f'<div style="color:#64748b; font-size:10px; font-weight:600; text-transform:uppercase; margin-bottom:2px;">Turn {i + 1} &mdash; Tester</div>'
                f'<div style="color:#1e293b; background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:8px;">{_sanitize(u)}</div>'
                f"</div>"
            )
        if a:
            html += (
                f'<div style="margin-bottom:8px;">'
                f'<div style="color:#64748b; font-size:10px; font-weight:600; text-transform:uppercase; margin-bottom:2px;">Turn {i + 1} &mdash; Agent</div>'
                f'<div style="color:#374151; background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:8px;">{_sanitize(a)}</div>'
                f"</div>"
            )
    html += "</div>"
    return html


def _mask_orchestrator_name(test_category):
    if not test_category:
        return "Security Test"
    parts = test_category.strip("/").split("/")
    family = parts[1].title() if len(parts) > 1 else "Security"
    orch = parts[-1] if len(parts) > 2 else parts[-1]
    display = orch.replace("_", " ").title()
    return f"{family} / {display}"


# ── Main Report Generator ─────────────────────────────────────────


def generate_html_report(experiment, logs):
    """Generate a platform-branded HTML report from experiment data + logs.

    Args:
        experiment: dict with keys: id, name, status, test_category, testing_level, results, created_at
        logs: list of log dicts

    Returns:
        Complete self-contained HTML string.
    """
    # Load template
    template_path = os.path.join(TEMPLATES_DIR, "report_base.html")
    with open(template_path) as f:
        template_str = f.read()

    results = experiment.get("results") or {}
    stats = results.get("stats") or {}
    posture_data = results.get("posture") or {}
    insights = results.get("insights") or []
    exec_t = results.get("exec_t") or {}

    name = experiment.get("name", "Security Test")
    test_category = experiment.get("test_category", "")
    testing_level = experiment.get("testing_level", "")
    created_at = experiment.get("created_at", "")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    total = stats.get("total", stats.get("pass", 0) + stats.get("fail", 0))
    passed = stats.get("pass", stats.get("pass_", 0))
    failed = stats.get("fail", 0)

    posture_score = posture_data.get("posture", 0) if posture_data else 0
    posture_grade = (
        posture_data.get("grade", _score_to_grade(posture_score)) if posture_data else "F"
    )
    defense_rate = (passed / (passed + failed)) if (passed + failed) > 0 else 0

    # ── Build report body ──────────────────────────────────

    body = ""

    # Posture section
    body += '<div class="section">\n<h2>Security Posture</h2>\n'
    body += '<div class="posture-row">\n'
    body += _build_donut("Overall", posture_score, posture_grade)

    domain = posture_data.get("domain", "security") if posture_data else "security"
    if domain == "security":
        body += _build_donut("Security", posture_score, posture_grade)
    else:
        body += _build_donut("Quality", posture_score, posture_grade)
    body += "</div>\n"

    # Stats cards
    body += '<div class="card-grid">\n'
    body += f'<div class="card"><div class="label">Conversations</div><div class="value">{total}</div></div>\n'
    body += f'<div class="card"><div class="label">Passed</div><div class="value" style="color:#16a34a">{passed}</div></div>\n'
    body += f'<div class="card"><div class="label">Failed</div><div class="value" style="color:#dc2626">{failed}</div></div>\n'
    body += f'<div class="card"><div class="label">Defense Rate</div><div class="value">{defense_rate * 100:.1f}%</div></div>\n'
    body += "</div>\n</div>\n"

    # Severity distribution
    if insights:
        by_severity = {}
        for ins in insights:
            if ins.get("result") != "fail":
                continue
            sev = _severity_to_label(ins.get("severity", 0))
            by_severity[sev] = by_severity.get(sev, 0) + ins.get("count", 1)

        if by_severity:
            body += '<div class="section">\n<h2>Severity Distribution</h2>\n'
            body += _build_severity_bar(by_severity)
            body += "</div>\n"

    # Insights table
    if insights:
        fail_insights = [i for i in insights if i.get("result") == "fail"]
        if fail_insights:
            body += '<div class="section">\n<h2>Findings</h2>\n'
            body += "<table>\n<tr><th>Severity</th><th>Category</th><th>Count</th><th>Explanation</th></tr>\n"
            for ins in sorted(
                fail_insights,
                key=lambda x: (
                    SEVERITY_ORDER.index(_severity_to_label(x.get("severity", 0)))
                    if _severity_to_label(x.get("severity", 0)) in SEVERITY_ORDER
                    else 99
                ),
            ):
                sev = _severity_to_label(ins.get("severity", 0))
                cat = _sanitize(ins.get("category", ""))
                count = ins.get("count", 1)
                explanation = _sanitize(ins.get("explanation", ""))
                body += f'<tr><td><span class="badge badge-{sev}">{sev}</span></td><td>{cat}</td><td>{count}</td><td>{explanation}</td></tr>\n'
            body += "</table>\n</div>\n"

    # Breached categories
    breached = posture_data.get("breached", []) if posture_data else []
    defended = posture_data.get("defended", []) if posture_data else []
    if breached or defended:
        body += '<div class="section">\n<h2>Category Coverage</h2>\n'
        body += "<table>\n<tr><th>Category</th><th>Status</th></tr>\n"
        for cat in breached:
            body += f'<tr><td>{_sanitize(cat)}</td><td><span class="badge badge-fail">Breached</span></td></tr>\n'
        for cat in defended:
            body += f'<tr><td>{_sanitize(cat)}</td><td><span class="badge badge-pass">Defended</span></td></tr>\n'
        body += "</table>\n</div>\n"

    # Conversation appendix (failed logs only, max 20)
    fail_logs = [l for l in logs if l.get("result") == "fail"]
    if fail_logs:
        body += '<div class="section">\n<h2>Appendix — Failed Conversations</h2>\n'
        body += f'<p class="section-intro">Showing {min(len(fail_logs), 20)} of {len(fail_logs)} failed conversations.</p>\n'
        for i, log in enumerate(fail_logs[:20], 1):
            sev = _severity_to_label(log.get("severity", 0))
            cat = _sanitize(log.get("fail_category", ""))
            explanation = _sanitize(log.get("explanation", ""))
            body += '<div style="margin-bottom:20px; padding:16px; border:1px solid #e2e8f0; border-radius:8px;">\n'
            body += '<div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">'
            body += f'<span class="badge badge-{sev}">{sev}</span> '
            body += f"<strong>{cat}</strong></div>\n"
            body += (
                f'<p style="font-size:13px; color:#475569; margin-bottom:8px;">{explanation}</p>\n'
            )
            body += _render_conversation(log.get("conversation", []))
            body += "</div>\n"
        body += "</div>\n"

    # ── Fill template ──────────────────────────────────────

    cover_meta = (
        f"<strong>Test:</strong> {_sanitize(name)}<br>"
        f"<strong>Category:</strong> {_mask_orchestrator_name(test_category)}<br>"
        f"<strong>Level:</strong> {_sanitize(testing_level)}<br>"
        f"<strong>Date:</strong> {_sanitize(created_at)}<br>"
        f"<strong>Generated:</strong> {generated_at}"
    )

    template = Template(template_str)
    html = template.safe_substitute(
        title=f"{_sanitize(name)} — Humanbound Report",
        logo_uri=_get_logo_data_uri(),
        cover_title="AI Agent Security Report",
        cover_subtitle=_mask_orchestrator_name(test_category),
        cover_meta=cover_meta,
        context_section="",
        body=body,
        report_subject=_sanitize(name),
        generated_at=generated_at,
    )

    return html
