---
description: "Security posture (0–100) summarises an agent's defense rate, coverage, and finding severity into a single comparable score."
keywords:
  - security posture
  - posture score
  - AI agent security score
  - posture grade
  - coverage effectiveness
  - severity impact
  - hb posture command
  - organization posture
---

# Security Posture

The Humanbound security posture is a single 0–100 score (with A–F grade) that summarises an AI agent's severity impact (weighted sum of active findings by severity and status) and coverage effectiveness (ratio of tested threat classes with acceptable pass rates) into one comparable number. It is computed as `100 * (1 - severity_impact) * coverage_effectiveness`, viewed via `hb posture` (current score), `hb posture --trends` (history), or `hb posture --org` (aggregated across projects in two dimensions: Agent Security and Quality). The formula is:

```
posture = 100 * (1 - severity_impact) * coverage_effectiveness
```

- **Severity Impact**: Weighted sum of active findings (by severity and status)
- **Coverage Effectiveness**: Ratio of tested threat classes with acceptable pass rates

## View Current Posture

```bash
hb posture
```

## View Historical Trends

```bash
hb posture --trends
```

## Export as JSON

```bash
hb posture --json
```

## View Specific Project

```bash
hb posture --project <id>
```

## Organisation-Level Posture (3 Dimensions)

```bash
# Aggregate posture across all projects + inventory
hb posture --org
```

Org posture aggregates two dimensions:

- **Agent Security** -- posture across all security-tested projects
- **Quality** -- behavioral quality across all tested agents

## Include Coverage Breakdown

```bash
hb posture --coverage
```

## Posture Grades

| Grade | Range | Description |
|---|---|---|
| **A** | 90-100 | Excellent security posture with minimal vulnerabilities and comprehensive coverage |
| **B** | 75-89 | Good security posture with minor vulnerabilities or coverage gaps |
| **C** | 60-74 | Fair security posture requiring attention to identified issues |
| **D** | 40-59 | Poor security posture with significant vulnerabilities or coverage gaps |
| **F** | 0-39 | Critical security posture requiring immediate remediation |
