---
description: "Assessments are point-in-time snapshots of a project's security state — posture, findings, and coverage produced by every ASCAM activity."
---

# Assessments

Assessments are snapshots of a project's security state at a point in time. Each ASCAM activity (assess, investigate, monitor) produces an assessment that captures posture, findings, and coverage at that moment.

## List Assessments

```bash
hb assessments list
```

## View Assessment Details

```bash
hb assessments show <assessment-id>
```

## Generate Assessment Report

```bash
# Generate HTML report (opens in browser by default)
hb assessments report <assessment-id>

# Save to file
hb assessments report <assessment-id> -o report.html

# Save without opening browser
hb assessments report <assessment-id> -o report.html --no-open
```

!!! info "Note"
    Assessments are created automatically by ASCAM activities. Use `hb assessments list` to see history and `hb assessments report <id>` to generate a detailed report for any past assessment.
