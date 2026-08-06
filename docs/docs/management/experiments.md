---
description: "Experiments are individual test executions — they generate attack prompts, drive conversations with your agent, and produce security verdicts."
keywords:
  - experiments
  - hb experiments command
  - test execution tracking
  - experiment status
  - experiment logs
  - experiment report
  - hb logs filtering
  - CI/CD experiment wait
---

# Experiments

An experiment is one execution of `hb test` — it generates attack prompts, runs multi-turn conversations against your agent, and produces a set of verdicts that feed into the project's posture and findings. The `hb experiments` commands list past experiments, show details of a specific one, check status (single, watch, or all-experiments dashboard), wait for completion (useful in CI/CD), view filtered logs, generate HTML reports, terminate running tests, and delete old records.

## List Experiments

```bash
hb experiments list
```

## Show Experiment Details

```bash
hb experiments show <id>
```

## Check Experiment Status

```bash
# Single status check
hb experiments status <id>

# Live updates (refreshes every 10 seconds)
hb experiments status <id> --watch

# Dashboard: all experiments, polls every 60s until all complete
hb experiments status --all
```

## Wait for Completion

Block until an experiment completes (useful for CI/CD pipelines):

```bash
# Wait indefinitely
hb experiments wait <id>

# Wait with timeout (minutes)
hb experiments wait <id> --timeout 60
```

## View Experiment Logs

```bash
# View logs for a specific experiment
hb logs <id>

# Filter by verdict
hb logs <id> --verdict fail
hb logs <id> --verdict pass

# Export branded HTML report
hb logs <id> --format html -o report.html

# Export as JSON
hb logs <id> --format json --all -o results.json

# Project-wide logs with scope flags
hb logs --last 5                           # Last 5 experiments
hb logs --last 3 --verdict fail            # Failed logs from last 3
hb logs --category owasp_agentic           # Filter by test category
hb logs --days 7 --format json -o week.json
hb logs --from 2026-01-01 --until 2026-02-01 --format html -o jan.html
```

## Generate Experiment Report

```bash
# Generate HTML report (opens in browser by default)
hb experiments report <id>

# Save to file
hb experiments report <id> -o report.html

# Save without opening browser
hb experiments report <id> -o report.html --no-open
```

## Terminate Running Experiment

```bash
hb experiments terminate <id>
```

## Delete Experiment

```bash
# Delete with confirmation
hb experiments delete <id>

# Skip confirmation
hb experiments delete <id> --force
```
