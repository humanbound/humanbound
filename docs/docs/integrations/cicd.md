---
description: "Run Humanbound in CI/CD — use the humanbound/actions GitHub Action or the hb CLI to gate builds on agent security, surface findings in the Security tab, and catch regressions."
keywords:
  - CI/CD security testing
  - GitHub Actions integration
  - humanbound/actions GitHub Action
  - GitLab CI integration
  - SARIF security tab
  - --fail-on threshold
  - security gate
  - automated security tests
  - pipeline integration
  - --wait CI flag
faq:
  - q: Is there a GitHub Action for Humanbound?
    a: "Yes. The official [`humanbound/actions`](https://github.com/marketplace/actions/humanbound-ai-agent-security-testing) Action wraps `hb test` — it installs the CLI, runs the scan, gates the build with `fail-on`, and uploads findings to the GitHub Security tab as SARIF. Reference it as `uses: humanbound/actions@v1`."
  - q: What does the --fail-on flag do in CI/CD?
    a: The `--fail-on` flag causes the `hb test` command to exit with a non-zero status code when vulnerabilities at or above the specified severity are found. Thresholds are `critical`, `high`, `medium`, `low`, and `any`, allowing you to configure how strict your security gate is.
  - q: What does --wait do and why should I use it in CI/CD?
    a: "`--wait` tells Humanbound to block until the test run completes before the command exits. Always use `--wait` in CI/CD pipelines to ensure results are available before the job finishes or artifacts are exported. (The GitHub Action passes `--wait` for you.)"
---

# CI/CD Integration

Gate your builds on agent security: run Humanbound's adversarial tests in your pipeline and
fail the build when findings cross a severity threshold. On **GitHub**, use the official
[`humanbound/actions`](https://github.com/marketplace/actions/humanbound-ai-agent-security-testing)
Action; on **GitLab** and other systems, run the `hb` CLI directly.

## How it works

1. **Your pipeline boots the agent** (or points at a running one) and hands its endpoint to Humanbound.
2. **Humanbound attacks it** — multi-turn adversarial conversations (OWASP-aligned prompt injection, tool misuse, data exfiltration, and more).
3. **An LLM judge scores every response** and records findings with severities.
4. **The result gates your build** — `fail-on` sets the exit code; on GitHub, findings also land in the Security tab as SARIF, with a severity summary on the run page.

## GitHub Actions

Use the [`humanbound/actions`](https://github.com/marketplace/actions/humanbound-ai-agent-security-testing)
Marketplace Action — it installs the CLI, runs the scan, gates the build, writes a severity
summary to the run page, and uploads findings to the **Security tab** as SARIF.

```yaml
# .github/workflows/security-test.yml
name: AI Security Tests
on: [pull_request]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - run: docker compose up -d agent # boot your agent, reachable on localhost

      - uses: humanbound/actions@v1
        with:
          # Your agent's config — inline here; a file or a build step also work.
          endpoint: |
            {
              "streaming": null,
              "chat_completion": {
                "endpoint": "http://localhost:8000/chat",
                "payload": { "content": "$PROMPT" }
              }
            }
          # The attacker/judge LLM key (local mode). Use a repository secret.
          provider-api-key: ${{ secrets.OPENAI_API_KEY }}
          model: gpt-4.1
          fail-on: high # fail the build on high-severity findings
```

Findings gate the build via `fail-on`, land in **Security → Code scanning** as SARIF, and are
summarized on the workflow run page. **Local mode** (shown above — your own LLM key, no account)
works today; **platform mode** (`api-key`, results in the Humanbound dashboard) is coming soon.

!!! tip "Full reference"
    The Action supports many more inputs — scope discovery, test categories, SARIF controls,
    nightly deep scans, and artifacts. See the
    [Marketplace listing](https://github.com/marketplace/actions/humanbound-ai-agent-security-testing)
    for the complete inputs table and scenarios.

## Fail-On Thresholds

Use `fail-on` (Action input) or `--fail-on` (CLI flag) to fail the build when vulnerabilities of
a certain severity are found:

| Threshold | Description |
|---|---|
| `critical` | Fail only on critical severity findings |
| `high` | Fail on high or critical findings |
| `medium` | Fail on medium, high, or critical findings |
| `low` | Fail on low, medium, high, or critical findings |
| `any` | Fail on any finding (including info) |

## GitLab CI (and other CI systems)

Anywhere you can't use a GitHub Action, run the `hb` CLI directly. Install the engine extra
for local mode, point `--endpoint` at your agent, and gate with `--fail-on`:

```yaml
# .gitlab-ci.yml
security-test:
  stage: test
  image: python:3.12
  variables:
    HB_PROVIDER: openai
    HB_API_KEY: $OPENAI_API_KEY # attacker/judge LLM key (CI/CD variable)
    HB_MODEL: gpt-4.1
  script:
    - pip install "humanbound[engine]"
    - hb test --local --endpoint ./agent-config.json --wait --fail-on high
    - hb logs --format json -o security-results.json
  artifacts:
    paths:
      - security-results.json
    when: always
```

The same pattern works on Jenkins, CircleCI, and others — install `humanbound[engine]`, run
`hb test --local --endpoint <config> --wait --fail-on <severity>`, then export results with
`hb logs`. See the [CLI reference](../reference/commands.md) and
[Agent Configuration](../getting-started/agent-config.md) for the endpoint config format.

!!! tip
    Always use `--wait` in CI/CD so the test completes before the job finishes (the GitHub
    Action does this for you). Use `--fail-on` to enforce a security quality gate.

<!-- faq -->
