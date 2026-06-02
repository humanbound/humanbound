---
description: "Generate branded HTML security reports at four detail levels — executive, summary, detailed, and forensic — for stakeholders inside and outside your team."
keywords:
  - security reports
  - HTML security report
  - project report
  - organisation report
  - assessment report
  - experiment report
  - compliance reports
  - DORA compliance
---

# Reports

Humanbound generates branded HTML security reports at four levels of scope — Project (an agent's standing posture and threat landscape), Organisation (executive overview across all projects), Assessment (one test run with full conversation evidence), and Experiment (deep dive into a single orchestrator's run with methodology context). Each report is rendered by the backend, opens automatically in your browser, and includes a methodology section, technology disclaimer, legal notice, and print-ready CSS for compliance submissions (DORA, PCI-DSS, ISO/IEC 42001, NIS2, EU AI Act).

All reports include:

- **Methodology section** — testing approach, posture scoring, continuous monitoring
- **Technology disclaimer** — LLM stochastic nature, limitations
- **Legal notice** — copyright, confidentiality, no tampering
- **Print-ready CSS** — use browser "Print to PDF" for compliance submissions

## Report Levels

### Project Report

The standing security posture of an agent — findings, threat landscape, monitoring status, and assessment history.

```bash
# Current project
hb projects report

# Save without opening browser
hb projects report --no-open

# Custom output path
hb projects report -o ./reports/q1-security.html
```

**Includes:** Agent scope (permitted/restricted operations), posture donuts (overall + security + quality), findings with severity and threat class, threat landscape, assessment history (last 90 days), human feedback audit summary.

### Organisation Report

Executive overview across all projects in the organisation.

```bash
hb orgs report
hb orgs report -o org-report.html
```

**Includes:** Organisation posture donuts, findings summary with severity bar, all projects with grade, score, last assessed date, and monitoring status.

### Assessment Report

What happened in a specific test run — results, findings, and full conversation evidence.

```bash
# Get assessment ID from list
hb assessments

# Generate report
hb assessments report <assessment-id>
hb assessments report abc123 -o assessment.html
```

**Includes:** Overview (tests, pass rate, status), test suite (engines, level, language), posture before/after donuts, findings, and a full appendix of every test conversation with verdict, severity, explanation, and multi-turn dialogue.

### Experiment Report

Deep dive into a single test engine's run, with orchestrator-specific methodology context.

```bash
# Get experiment ID from list
hb experiments list

# Generate report
hb experiments report <experiment-id>
hb experiments report abc123 -o experiment.html
```

**Includes:** Orchestrator-specific context (OWASP methodology for adversarial, QA evaluation dimensions for behavioral), metrics (TPI, reliability, pass rate), vulnerabilities identified, and full conversation appendix with feedback badges.

## Options

| Option | Description |
|--------|-------------|
| `-o`, `--output PATH` | Custom output file path |
| `--no-open` | Save file without opening in browser |

## For Compliance

Reports are designed for submission to auditors and compliance frameworks including DORA, PCI-DSS, ISO/IEC 42001, NIS2, and the EU AI Act.

- **Project reports** prove ongoing monitoring and scope definition
- **Assessment reports** provide test evidence with full conversation logs
- **Experiment reports** document specific testing methodology

Use browser "Print to PDF" to generate PDF versions suitable for formal submissions.
