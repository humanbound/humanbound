---
description: "Assessments are point-in-time snapshots of a project's security state — posture, findings, and coverage produced by every ASCAM activity."
keywords:
  - assessments
  - ASCAM assessments
  - assessment snapshot
  - hb assessments command
  - assessment history
  - assessment report
---

# Assessments

Assessments are snapshots of a project's security state at a point in time. Each ASCAM activity (assess, investigate, monitor) produces an assessment automatically, capturing posture, findings, and coverage at that moment. You can also compose your own: pick a list of tests and create-and-run a custom assessment from them directly, no separate staging step required.

## List Assessments

```bash
hb assessments
```

## View Assessment Details

```bash
hb assessments show <assessment-id>
```

## Create a Custom Assessment

Run an assessment from your own choice of tests instead of waiting for the next ASCAM cycle:

`-t/--test-category` takes full test-category paths — the same values `hb test`
accepts. Repeat the flag or comma-separate to run several. A category the
backend doesn't recognise is rejected with a `400` before anything runs.

```bash
# Create and run in one step
hb assessments create -t humanbound/adversarial/owasp_agentic

# Several categories at once (a security one and a quality one)
hb assessments create -t humanbound/adversarial/owasp_agentic -t humanbound/behavioral/qa

# Pin a testing depth (defaults to unit)
hb assessments create -t humanbound/adversarial/owasp_agentic --testing-level unit

# Block until the assessment reaches a terminal status
hb assessments create -t humanbound/adversarial/owasp_agentic --wait

# Skip the confirmation prompt (required alongside --json)
hb assessments create -t humanbound/adversarial/owasp_agentic --yes --json
```

Findings land in the same place as any other assessment: `hb findings` and the
UI. Custom assessments are **windowless**, though — they run exactly the tests
you chose and never measure a posture window, so `hb assessments show` reports
`—` for posture and drift. The `Findings:` line is their outcome. The findings
they surface still count toward the project's posture.

Only one assessment per domain runs at a time. A second custom assessment in the
same domain — or any assessment while a generated (ASCAM or `hb test`) run is
active — is rejected with a message naming the conflicting run, and the command
exits `1`.

`--wait` polls until the assessment reaches a terminal status — `completed`, `failed`, or `broken` — and exits `0` for `completed`, `1` otherwise.

## Clone a Custom Assessment

Re-run a past custom assessment with the same tests and testing level:

```bash
hb assessments clone <assessment-id>

# Block until it reaches a terminal status
hb assessments clone <assessment-id> --wait

# Skip the confirmation prompt (required alongside --json)
hb assessments clone <assessment-id> --yes --json
```

`clone` only works on custom assessments (those created via `hb assessments create`) — the tests and level are read from the source assessment's discovery plan.

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
    Assessments come from two sources: ASCAM activities create them automatically, or you compose your own with `hb assessments create` (and re-run one later with `hb assessments clone`). Use `hb assessments` to see history and `hb assessments report <id>` to generate a detailed report for any past assessment.
