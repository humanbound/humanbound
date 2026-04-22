# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Generic Humanbound-branded HTML report builder.

Constructs self-contained HTML pages from typed sections, reusing the
design system from report.py (dark theme, Inter font, badges, cards,
tables, donut charts, print styles).

Usage:
    from .report_builder import ReportBuilder

    rb = ReportBuilder(title="AI Inventory", subtitle="42 assets discovered")
    rb.add_kv("Summary", {"Total Assets": 42, "Shadow": 12})
    rb.add_table("Assets", columns=["Name", "Vendor"], rows=[["Bot", "MS"]])
    rb.add_posture(score=78, grade="C", label="Shadow AI Posture")
    html = rb.render()
    rb.save("inventory-report.html")
"""

import os
import webbrowser
from datetime import datetime, timezone
from html import escape

LOGO_URL = "https://cdneunorth.blob.core.windows.net/data/humanbound_logo.png"
TAGLINE = "Build safer, more trusted AI."


def _esc(val) -> str:
    return escape(str(val)) if val is not None else ""


# ---------------------------------------------------------------------------
# Shared standards / risk-model reference (used in report appendices)
# ---------------------------------------------------------------------------

STANDARDS_REFERENCE_HTML = """\
<h3 style="margin-top:1.5rem">Threat Model</h3>
<p>
The security evaluation is based on a threat model comprising
<strong>15 threat classes</strong> across <strong>6 risk domains</strong>.
Each threat class is derived from, and cross-referenced against,
established international AI security frameworks — it is not an
ad-hoc classification but a standards-informed taxonomy.
</p>
<table style="margin:.75rem 0 1.25rem;font-size:.8rem">
<thead><tr>
  <th style="text-align:left;padding:.4rem .6rem">Risk Domain</th>
  <th style="text-align:left;padding:.4rem .6rem">Threat Classes</th>
  <th style="text-align:left;padding:.4rem .6rem">Primary Standards</th>
</tr></thead>
<tbody>
<tr>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">Data Security</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    Sensitive Data Exposure &middot; Data Residency Violation &middot; Training Data Contamination</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    OWASP LLM02 &middot; MITRE AML.T0040 &middot; GDPR Art.&nbsp;5, 32, 44-49</td>
</tr>
<tr>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">Intellectual Property</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    IP Leakage &middot; Model Replication Risk</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    OWASP LLM02, LLM10 &middot; MITRE AML.T0042, AML.T0044</td>
</tr>
<tr>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">Compliance &amp; Regulatory</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    Regulatory Non-Compliance &middot; Audit Trail Gap</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    EU AI Act Art.&nbsp;6, 9, 11, 12, 14 &middot; ISO 42001 &sect;6.1, 9.1 &middot; NIST AI RMF Govern</td>
</tr>
<tr>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">Supply Chain &amp; Technical</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    Unauthorized API Usage &middot; Unvetted Supply Chain &middot; Insecure Deployment</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    OWASP LLM01, LLM03, LLM06 &middot; MITRE AML.T0010, AML.T0051 &middot; NIST Map&nbsp;1.6</td>
</tr>
<tr>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">Governance &amp; Accountability</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    Ungoverned AI Adoption &middot; Decision Opacity</td>
  <td style="padding:.4rem .6rem;border-bottom:1px solid var(--border)">
    EU AI Act Art.&nbsp;4, 13, 14 &middot; ISO 42001 &sect;5.1, A.8.5 &middot; CSA AICM Domain&nbsp;1</td>
</tr>
<tr>
  <td style="padding:.4rem .6rem">Insider Threat Amplification</td>
  <td style="padding:.4rem .6rem">
    Insider AI Misuse &middot; Policy Violation &middot; Unauthorized Tool Proliferation</td>
  <td style="padding:.4rem .6rem">
    OWASP LLM02, LLM06 &middot; GDPR Art.&nbsp;5, 6 &middot; ISO 42001 A.8.2 &middot; CSA AICM Domain&nbsp;2</td>
</tr>
</tbody></table>

<h3 style="margin-top:1.5rem">Asset Categories</h3>
<p>
Discovery searches for <strong>9 categories</strong> of AI assets, classified
according to cloud-provider resource taxonomies (Azure Resource Graph types,
Microsoft Graph service principals, license SKUs) and mapped to functional
roles defined in ISO/IEC 22989:2022 (AI concepts and terminology) and the
NIST AI RMF actor/lifecycle model.
</p>
<table style="margin:.75rem 0 1.25rem;font-size:.8rem">
<thead><tr>
  <th style="text-align:left;padding:.4rem .6rem">Code</th>
  <th style="text-align:left;padding:.4rem .6rem">Category</th>
  <th style="text-align:left;padding:.4rem .6rem">What Is Detected</th>
</tr></thead>
<tbody>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-1</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">Copilot / Embedded AI</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">M365 Copilot, GitHub Copilot, vendor-embedded assistants</td></tr>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-2</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AI Platform</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">Azure OpenAI, Cognitive Services, AI Studio</td></tr>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-3</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">ML / Data Science</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">Machine Learning workspaces, training pipelines</td></tr>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-4</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AI Development Tool</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">Code assistants, prompt-engineering tools, AI SDKs</td></tr>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-5</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AI Assistant</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">Standalone chat assistants, third-party AI apps</td></tr>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-6</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AI Agent</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">Bot Service bots, Copilot Studio agents, autonomous agents</td></tr>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-7</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AI API / Endpoint</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">Model inference endpoints, LLM API keys in use</td></tr>
<tr><td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AC-8</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">AI Infrastructure</td>
    <td style="padding:.3rem .6rem;border-bottom:1px solid var(--border)">GPU compute, model registries, vector databases</td></tr>
<tr><td style="padding:.3rem .6rem">AC-9</td>
    <td style="padding:.3rem .6rem">Other AI</td>
    <td style="padding:.3rem .6rem">Unclassified AI-related services detected via heuristics</td></tr>
</tbody></table>

<h3 style="margin-top:1.5rem">Standards &amp; References</h3>
<p>
The threat model, asset taxonomy, and evaluation criteria are derived from
and cross-referenced against the following standards and frameworks:
</p>
<ul style="margin:.5rem 0 0 1.25rem;font-size:.8rem;line-height:1.8">
<li><strong>OWASP Top 10 for LLM Applications (2025)</strong> &mdash;
    LLM-specific vulnerability classification
    (<a href="https://owasp.org/www-project-top-10-for-large-language-model-applications/" target="_blank" rel="noopener">owasp.org</a>)</li>
<li><strong>MITRE ATLAS</strong> &mdash;
    Adversarial Threat Landscape for Artificial Intelligence Systems
    (<a href="https://atlas.mitre.org" target="_blank" rel="noopener">atlas.mitre.org</a>)</li>
<li><strong>NIST AI Risk Management Framework (AI 100-1, Jan 2023)</strong> &mdash;
    AI risk governance lifecycle
    (<a href="https://www.nist.gov/artificial-intelligence/executive-order-safe-secure-and-trustworthy-artificial-intelligence" target="_blank" rel="noopener">nist.gov</a>)</li>
<li><strong>ISO/IEC 42001:2023</strong> &mdash;
    Artificial Intelligence Management System standard</li>
<li><strong>ISO/IEC 22989:2022</strong> &mdash;
    AI concepts and terminology (informs asset categorisation)</li>
<li><strong>EU AI Act (Regulation 2024/1689)</strong> &mdash;
    European regulation on AI risk classification, transparency, and governance</li>
<li><strong>GDPR (Regulation 2016/679)</strong> &mdash;
    General Data Protection Regulation — data security and residency obligations</li>
<li><strong>CSA AI Controls Matrix (AICM)</strong> &mdash;
    Cloud Security Alliance controls for AI workloads
    (<a href="https://cloudsecurityalliance.org" target="_blank" rel="noopener">cloudsecurityalliance.org</a>)</li>
<li><strong>ETSI EN 304 223</strong> &mdash;
    Securing AI — characterisation of AI trustworthiness across 5 lifecycle phases
    (<a href="https://www.etsi.org" target="_blank" rel="noopener">etsi.org</a>)</li>
</ul>
"""


def _fmt(val, decimals=1) -> str:
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return "0"


# ---------------------------------------------------------------------------
# CSS — carried verbatim from report.py design system
# ---------------------------------------------------------------------------

_CSS = """\
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#1E2323;--bg-card:#161b22;--bg-surface:#0d1117;
  --text:#E6EDF3;--text-secondary:#8B949E;--text-dim:#6e7681;
  --border:#30363D;--accent:#FD9506;
  --success:#3FB950;--warning:#F0C000;--error:#F85149;
  --good:#58a6ff;
  --font-sans:'Inter',ui-sans-serif,system-ui,-apple-system,sans-serif;
  --font-mono:'JetBrains Mono','SF Mono','Fira Code',monospace;
}
body{
  font-family:var(--font-sans);background:var(--bg);color:var(--text);
  line-height:1.6;min-height:100vh;
}
.container{max-width:1100px;margin:0 auto;padding:2rem 1.5rem}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}

/* Header */
.report-header{
  display:flex;align-items:center;gap:1.5rem;
  padding:1.5rem 2rem;background:var(--bg-card);
  border:1px solid var(--border);border-radius:12px;margin-bottom:1.5rem;
}
.report-header img{height:36px}
.report-header h1{font-size:1.25rem;font-weight:600;flex:1}
.report-header .subtitle{font-size:.85rem;color:var(--text-secondary);margin-top:.25rem}
.meta-row{display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:.5rem;font-size:.8rem;color:var(--text-secondary)}
.meta-row span{display:flex;align-items:center;gap:.35rem}

/* Badges */
.badge{
  display:inline-block;padding:.2rem .65rem;border-radius:20px;
  font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.03em;
}
.badge-success{background:rgba(63,185,80,.15);color:var(--success);border:1px solid rgba(63,185,80,.3)}
.badge-good{background:rgba(88,166,255,.15);color:var(--good);border:1px solid rgba(88,166,255,.3)}
.badge-warning{background:rgba(240,192,0,.15);color:var(--warning);border:1px solid rgba(240,192,0,.3)}
.badge-error{background:rgba(248,81,73,.15);color:var(--error);border:1px solid rgba(248,81,73,.3)}
.badge-neutral{background:rgba(139,148,158,.15);color:var(--text-secondary);border:1px solid rgba(139,148,158,.3)}
.badge-accent{background:rgba(253,149,6,.15);color:var(--accent);border:1px solid rgba(253,149,6,.3)}

/* Section */
.section{margin-bottom:1.5rem}
.section-title{
  font-size:1rem;font-weight:600;margin-bottom:1rem;
  padding-bottom:.5rem;border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:.5rem;
}

/* Health overview - donut + metrics */
.health-grid{display:grid;grid-template-columns:200px 1fr;gap:1.5rem;align-items:center}
.donut-container{position:relative;width:160px;height:160px;margin:0 auto}
.donut-container svg{width:160px;height:160px;transform:rotate(-90deg)}
.donut-container circle{fill:none;stroke-width:14;stroke-linecap:round}
.donut-bg{stroke:var(--border)}
.donut-fill{transition:stroke-dashoffset .6s ease}
.donut-label{
  position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  text-align:center;
}
.donut-label .value{font-size:2rem;font-weight:700;line-height:1}
.donut-label .label{font-size:.7rem;color:var(--text-secondary);margin-top:.15rem}
.health-metrics{display:flex;flex-direction:column;gap:1rem}
.health-metric{
  display:flex;justify-content:space-between;align-items:center;
  padding:.75rem 1rem;background:var(--bg-card);
  border:1px solid var(--border);border-radius:8px;
}
.health-metric .name{font-size:.85rem;color:var(--text-secondary)}
.health-metric .val{font-size:1.1rem;font-weight:600}

/* Metric cards */
.cards-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}
.card{
  padding:1.25rem;background:var(--bg-card);
  border:1px solid var(--border);border-radius:10px;
}
.card .card-label{font-size:.8rem;color:var(--text-secondary);margin-bottom:.35rem;display:flex;align-items:center;gap:.5rem}
.card .card-value{font-size:1.5rem;font-weight:700}
.card .card-sub{font-size:.8rem;color:var(--text-secondary);margin-top:.25rem}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:.85rem}
thead th{
  text-align:left;padding:.6rem .75rem;
  background:var(--bg-surface);color:var(--text-secondary);
  font-weight:600;border-bottom:1px solid var(--border);
  font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;
}
tbody td{padding:.6rem .75rem;border-bottom:1px solid var(--border)}
tbody tr:hover{background:rgba(255,255,255,.02)}

/* Status banner */
.status-banner{
  padding:2rem;text-align:center;
  background:var(--bg-card);border:1px solid var(--border);border-radius:10px;
  margin-bottom:1.5rem;
}
.status-banner h2{font-size:1.1rem;margin-bottom:.5rem}
.status-banner p{color:var(--text-secondary);font-size:.9rem}
.status-banner.banner-success{border-color:rgba(63,185,80,.3)}
.status-banner.banner-success h2{color:var(--success)}
.status-banner.banner-warning{border-color:rgba(240,192,0,.3)}
.status-banner.banner-warning h2{color:var(--warning)}
.status-banner.banner-error{border-color:rgba(248,81,73,.3)}
.status-banner.banner-error h2{color:var(--error)}

/* Panel (rich text block) */
.panel{
  padding:1.25rem;background:var(--bg-card);
  border:1px solid var(--border);border-radius:10px;margin-bottom:1rem;
  font-size:.85rem;line-height:1.7;color:var(--text-secondary);
}
.panel h3{font-size:.95rem;font-weight:600;color:var(--text);margin-bottom:.75rem}

/* Footer */
.report-footer{
  text-align:center;padding:1.5rem 0;margin-top:2rem;
  border-top:1px solid var(--border);color:var(--text-dim);font-size:.75rem;
}

/* Print styles */
@media print{
  body{background:#fff;color:#1a1a1a;font-size:11pt}
  .container{max-width:100%;padding:0}
  .report-header,.card,.health-metric,.panel,.status-banner{
    background:#f8f9fa;border-color:#dee2e6;color:#1a1a1a;
  }
  .badge{border-width:1px}
  .donut-bg{stroke:#dee2e6}
  thead th{background:#f1f3f5;color:#495057}
  tbody td{border-color:#dee2e6}
}

/* Hero */
.hero{
  text-align:center;padding:2.5rem 2rem;
  background:var(--bg-card);border:1px solid var(--border);border-radius:12px;
  margin-bottom:1.5rem;
}
.hero .donut-container{width:180px;height:180px;margin:0 auto 1.5rem}
.hero .donut-container svg{width:180px;height:180px}
.hero .donut-label .value{font-size:2.5rem}
.hero .verdict{font-size:1.05rem;color:var(--text);max-width:640px;margin:0 auto 1.5rem;line-height:1.7}
.hero-metrics{display:flex;justify-content:center;gap:2.5rem;flex-wrap:wrap}
.hero-metric{text-align:center}
.hero-metric .hm-val{font-size:1.5rem;font-weight:700}
.hero-metric .hm-label{font-size:.75rem;color:var(--text-secondary);margin-top:.15rem}

/* Executive Summary */
.exec-summary{
  padding:1.5rem;background:var(--bg-card);
  border:2px solid var(--accent);border-radius:10px;
  margin-bottom:1.5rem;font-size:.9rem;line-height:1.8;color:var(--text);
}
.exec-summary h3{font-size:.95rem;font-weight:600;color:var(--accent);margin-bottom:.75rem}

/* Heatmap */
.heatmap-wrap{margin-bottom:1.5rem}
.heatmap{display:flex;gap:0;border-radius:8px;overflow:hidden;height:32px}
.heatmap-block{display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:600;color:#fff;min-width:2px}
.heatmap-legend{display:flex;gap:1.5rem;margin-top:.75rem;font-size:.8rem;color:var(--text-secondary)}
.heatmap-legend-item{display:flex;align-items:center;gap:.35rem}
.heatmap-dot{width:10px;height:10px;border-radius:2px}

/* Trend indicator */
.trend{
  display:flex;align-items:center;gap:1rem;
  padding:1rem 1.5rem;background:var(--bg-card);
  border:1px solid var(--border);border-radius:10px;margin-bottom:1.5rem;
}
.trend-arrow{font-size:1.75rem;line-height:1}
.trend-delta{font-size:1.25rem;font-weight:700}
.trend-ctx{font-size:.85rem;color:var(--text-secondary)}

/* Prioritised actions */
.actions-list{list-style:none;padding:0}
.action-item{
  display:grid;grid-template-columns:2.5rem 1fr auto;gap:1rem;
  padding:1rem 1.25rem;background:var(--bg-card);
  border:1px solid var(--border);border-radius:8px;margin-bottom:.75rem;align-items:start;
}
.action-num{
  font-size:1.1rem;font-weight:700;color:var(--accent);
  width:2.5rem;height:2.5rem;line-height:2.5rem;text-align:center;
  background:rgba(253,149,6,.1);border-radius:50%;
}
.action-body h4{font-size:.9rem;font-weight:600;margin-bottom:.25rem}
.action-body p{font-size:.8rem;color:var(--text-secondary);line-height:1.5;margin:0}
.action-effort{
  font-size:.7rem;padding:.2rem .6rem;border-radius:12px;font-weight:600;
  white-space:nowrap;align-self:center;
}
.effort-quick{background:rgba(63,185,80,.15);color:var(--success);border:1px solid rgba(63,185,80,.3)}
.effort-moderate{background:rgba(240,192,0,.15);color:var(--warning);border:1px solid rgba(240,192,0,.3)}
.effort-strategic{background:rgba(248,81,73,.15);color:var(--error);border:1px solid rgba(248,81,73,.3)}

/* Appendix */
.appendix{opacity:.7}
.appendix .section-title{font-size:.85rem}
.appendix .panel{border-style:dashed;font-size:.8rem}

/* Responsive */
@media(max-width:700px){
  .health-grid{grid-template-columns:1fr}
  .report-header{flex-direction:column;align-items:flex-start}
  .cards-grid{grid-template-columns:1fr}
  .hero-metrics{gap:1.5rem}
  .action-item{grid-template-columns:2rem 1fr}
  .action-effort{grid-column:2}
}

/* Print overrides for new components */
@media print{
  .hero,.exec-summary,.trend,.action-item{background:#f8f9fa;border-color:#dee2e6;color:#1a1a1a}
  .exec-summary{border-color:#FD9506}
  .appendix{opacity:.5}
  .heatmap-block{color:#fff!important}
}"""


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ReportBuilder:
    """Build a self-contained, Humanbound-branded HTML report from sections."""

    def __init__(self, title: str, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self._sections: list[str] = []

    # -- Section adders -----------------------------------------------------

    def add_kv(self, heading: str, data: dict):
        """Add a key-value summary card (grid of metric cards)."""
        cards = []
        for label, value in data.items():
            cards.append(
                f'<div class="card">'
                f'<div class="card-label">{_esc(label)}</div>'
                f'<div class="card-value">{_esc(value)}</div>'
                f"</div>"
            )
        self._sections.append(
            f'<div class="section">'
            f'<div class="section-title">{_esc(heading)}</div>'
            f'<div class="cards-grid">{"".join(cards)}</div>'
            f"</div>"
        )

    def add_table(
        self,
        heading: str,
        columns: list[str],
        rows: list[list[str]],
        col_styles: dict | None = None,
    ):
        """Add a data table.

        col_styles maps column index → inline CSS string applied to each <td>.
        """
        col_styles = col_styles or {}
        ths = "".join(f"<th>{_esc(c)}</th>" for c in columns)

        row_htmls = []
        for row in rows:
            tds = []
            for i, cell in enumerate(row):
                style = f' style="{col_styles[i]}"' if i in col_styles else ""
                tds.append(f"<td{style}>{cell}</td>")  # cell may contain pre-escaped HTML
            row_htmls.append(f"<tr>{''.join(tds)}</tr>")

        self._sections.append(
            f'<div class="section">'
            f'<div class="section-title">{_esc(heading)}</div>'
            f"<table><thead><tr>{ths}</tr></thead>"
            f"<tbody>{''.join(row_htmls)}</tbody></table>"
            f"</div>"
        )

    def add_posture(
        self, score: float, grade: str, label: str = "Posture Score", metrics: dict | None = None
    ):
        """Add a donut chart with score, grade, and optional side metrics."""
        score = float(score)
        circumference = 2 * 3.14159 * 66
        offset = circumference - (score / 100) * circumference

        if score >= 75:
            stroke_color = "var(--success)"
        elif score >= 50:
            stroke_color = "var(--warning)"
        else:
            stroke_color = "var(--error)"

        # Side metrics
        metrics_html = ""
        if metrics:
            items = []
            for name, val in metrics.items():
                items.append(
                    f'<div class="health-metric">'
                    f'<span class="name">{_esc(name)}</span>'
                    f'<span class="val">{_esc(val)}</span>'
                    f"</div>"
                )
            metrics_html = f'<div class="health-metrics">{"".join(items)}</div>'

        self._sections.append(
            f'<div class="section">'
            f'<div class="section-title">{_esc(label)}</div>'
            f'<div class="health-grid">'
            f'<div class="donut-container">'
            f'<svg viewBox="0 0 160 160">'
            f'<circle class="donut-bg" cx="80" cy="80" r="66"/>'
            f'<circle class="donut-fill" cx="80" cy="80" r="66" '
            f'stroke="{stroke_color}" '
            f'stroke-dasharray="{_fmt(circumference, 2)}" '
            f'stroke-dashoffset="{_fmt(offset, 2)}"/>'
            f"</svg>"
            f'<div class="donut-label">'
            f'<div class="value">{_fmt(score, 0)}</div>'
            f'<div class="label">Grade {_esc(grade)}</div>'
            f"</div></div>"
            f"{metrics_html}"
            f"</div></div>"
        )

    def add_panel(self, heading: str, content: str):
        """Add a rich text block (free-form HTML content)."""
        self._sections.append(
            f'<div class="section">'
            f'<div class="section-title">{_esc(heading)}</div>'
            f'<div class="panel">{content}</div>'
            f"</div>"
        )

    def add_status(self, message: str, level: str = "success"):
        """Add a status banner (success / warning / error)."""
        css_class = f"banner-{level}" if level in ("success", "warning", "error") else ""
        self._sections.append(
            f'<div class="status-banner {css_class}"><h2>{_esc(message)}</h2></div>'
        )

    def add_hero(self, score: float, grade: str, verdict: str, metrics: dict | None = None):
        """Large centred posture hero — donut + verdict + key metrics."""
        score = float(score)
        circumference = 2 * 3.14159 * 66
        offset = circumference - (score / 100) * circumference

        if score >= 75:
            stroke = "var(--success)"
        elif score >= 50:
            stroke = "var(--warning)"
        else:
            stroke = "var(--error)"

        metrics_html = ""
        if metrics:
            items = []
            for name, val in metrics.items():
                items.append(
                    f'<div class="hero-metric">'
                    f'<div class="hm-val">{_esc(str(val))}</div>'
                    f'<div class="hm-label">{_esc(name)}</div>'
                    f"</div>"
                )
            metrics_html = f'<div class="hero-metrics">{"".join(items)}</div>'

        self._sections.append(
            f'<div class="hero">'
            f'<div class="donut-container">'
            f'<svg viewBox="0 0 160 160">'
            f'<circle class="donut-bg" cx="80" cy="80" r="66"/>'
            f'<circle class="donut-fill" cx="80" cy="80" r="66" '
            f'stroke="{stroke}" '
            f'stroke-dasharray="{_fmt(circumference, 2)}" '
            f'stroke-dashoffset="{_fmt(offset, 2)}"/>'
            f"</svg>"
            f'<div class="donut-label">'
            f'<div class="value" style="color:{stroke}">{_fmt(score, 0)}</div>'
            f'<div class="label">Grade {_esc(grade)}</div>'
            f"</div></div>"
            f'<div class="verdict">{verdict}</div>'
            f"{metrics_html}"
            f"</div>"
        )

    def add_executive_summary(self, text: str):
        """Accent-bordered executive summary block."""
        self._sections.append(f'<div class="exec-summary"><h3>Executive Summary</h3>{text}</div>')

    def add_heatmap(self, heading: str, levels: dict):
        """Risk distribution bar with coloured proportional blocks."""
        colors = {
            "critical": "#F85149",
            "high": "#da6840",
            "medium": "#F0C000",
            "low": "#58a6ff",
            "unknown": "#6e7681",
        }
        total = sum(levels.values())
        if total == 0:
            return

        blocks, legend = [], []
        for level in ("critical", "high", "medium", "low", "unknown"):
            count = levels.get(level, 0)
            if count == 0:
                continue
            pct = (count / total) * 100
            color = colors.get(level, "#6e7681")
            label = str(count) if pct > 8 else ""
            blocks.append(
                f'<div class="heatmap-block" style="width:{pct:.1f}%;background:{color}">{label}</div>'
            )
            legend.append(
                f'<div class="heatmap-legend-item">'
                f'<div class="heatmap-dot" style="background:{color}"></div>'
                f"{level.title()} ({count})"
                f"</div>"
            )

        self._sections.append(
            f'<div class="section">'
            f'<div class="section-title">{_esc(heading)}</div>'
            f'<div class="heatmap-wrap">'
            f'<div class="heatmap">{"".join(blocks)}</div>'
            f'<div class="heatmap-legend">{"".join(legend)}</div>'
            f"</div></div>"
        )

    def add_trend(self, current: float, previous: float, previous_date: str = ""):
        """Score delta indicator with arrow and context."""
        delta = current - previous
        if delta > 0:
            arrow, color, word = "&#x25B2;", "var(--success)", "improved"
        elif delta < 0:
            arrow, color, word = "&#x25BC;", "var(--error)", "degraded"
        else:
            arrow, color, word = "&#x25C6;", "var(--text-secondary)", "unchanged"

        ctx = f"Score {word} by {abs(delta):.0f} points"
        if previous_date:
            ctx += f" since {_esc(previous_date)}"

        self._sections.append(
            f'<div class="trend">'
            f'<span class="trend-arrow" style="color:{color}">{arrow}</span>'
            f'<span class="trend-delta" style="color:{color}">{delta:+.0f}</span>'
            f'<span class="trend-ctx">{ctx}</span>'
            f"</div>"
        )

    def add_actions(self, heading: str, actions: list[dict]):
        """Numbered prioritised action items.

        Each *action* dict: ``title``, ``description``, ``effort``
        (``quick`` / ``moderate`` / ``strategic``).
        """
        items = []
        for i, action in enumerate(actions, 1):
            effort = action.get("effort", "moderate")
            items.append(
                f'<li class="action-item">'
                f'<div class="action-num">{i}</div>'
                f'<div class="action-body">'
                f"<h4>{action.get('title', '')}</h4>"
                f"<p>{action.get('description', '')}</p>"
                f"</div>"
                f'<span class="action-effort effort-{effort}">{effort.title()}</span>'
                f"</li>"
            )
        self._sections.append(
            f'<div class="section">'
            f'<div class="section-title">{_esc(heading)}</div>'
            f'<ul class="actions-list">{"".join(items)}</ul>'
            f"</div>"
        )

    def add_mermaid(self, heading: str, mermaid_def: str):
        """Add a Mermaid.js diagram section."""
        self._sections.append(
            f'<div class="section">'
            f'<div class="section-title">{_esc(heading)}</div>'
            f'<pre class="mermaid">{_esc(mermaid_def)}</pre>'
            f"</div>"
        )

    def add_appendix(self, heading: str, content: str):
        """Dimmed appendix section (methodology, notes)."""
        self._sections.append(
            f'<div class="section appendix">'
            f'<div class="section-title">{_esc(heading)}</div>'
            f'<div class="panel">{content}</div>'
            f"</div>"
        )

    # -- Rendering ----------------------------------------------------------

    def render(self) -> str:
        """Return the complete HTML document as a string."""
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        subtitle_html = ""
        if self.subtitle:
            subtitle_html = f'<div class="subtitle">{_esc(self.subtitle)}</div>'

        head = (
            f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            f'<meta charset="UTF-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f"<title>{_esc(self.title)} — Humanbound Report</title>\n"
            f'<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            f'<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
            f'&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">\n'
            f"<style>\n{_CSS}\n</style>\n"
            f'<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>\n'
            f'<script>mermaid.initialize({{startOnLoad:true,theme:"dark"}});</script>\n'
            f"</head>"
        )

        header = (
            f'<div class="container">\n'
            f'<div class="report-header">\n'
            f'  <img src="{LOGO_URL}" alt="Humanbound">\n'
            f'  <div style="flex:1">\n'
            f"    <h1>{_esc(self.title)}</h1>\n"
            f"    {subtitle_html}\n"
            f'    <div class="meta-row">'
            f"<span>{generated_at}</span>"
            f"<span>{_esc(TAGLINE)}</span>"
            f"</div>\n"
            f"  </div>\n"
            f"</div>"
        )

        footer = (
            f'<div class="report-footer">'
            f"Generated by <strong>Humanbound CLI</strong> on {generated_at}<br>"
            f'<a href="https://humanbound.ai">humanbound.ai</a>'
            f"</div>\n</div>"
        )

        parts = [head, "<body>", header]
        parts.extend(self._sections)
        parts.append(footer)
        parts.append("</body></html>")
        return "\n".join(parts)

    def save(self, path: str | None = None, open_browser: bool = True) -> str:
        """Write the report to *path* and optionally open in the default browser.

        Returns the absolute path of the written file.
        """
        if path is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
            slug = self.title.lower().replace(" ", "-")[:30]
            path = f"{slug}-report-{date_str}.html"

        # Treat "true" as flag — if path is literally True, generate default
        if path is True:
            date_str = datetime.now().strftime("%Y-%m-%d")
            slug = self.title.lower().replace(" ", "-")[:30]
            path = f"{slug}-report-{date_str}.html"

        abs_path = os.path.abspath(path)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(self.render())

        if open_browser:
            try:
                webbrowser.open(f"file://{abs_path}")
            except Exception:
                pass  # Non-critical — CLI will print path anyway

        return abs_path
