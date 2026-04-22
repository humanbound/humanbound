# CI/CD Integration

Integrate Humanbound security testing into your continuous integration and deployment pipelines. When the project has a default integration configured (via `hb connect --endpoint`), CI/CD pipelines only need `hb test` with no endpoint flags.

## GitHub Actions Example

```yaml
# .github/workflows/security-test.yml
name: AI Security Tests
on: [push]

jobs:
  security-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Humanbound CLI
        run: pip install humanbound

      - name: Run Security Tests
        env:
          HUMANBOUND_API_KEY: ${{ secrets.HB_API_KEY }}
        run: |
          hb test --wait --fail-on high

      - name: Export Results
        if: always()
        run: hb logs --format json -o security-results.json

      - name: Upload Artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: security-results
          path: security-results.json
```

## Fail-On Thresholds

Use the `--fail-on` flag to automatically fail CI builds when vulnerabilities of a certain severity are found:

| Threshold | Description |
|---|---|
| `--fail-on critical` | Fail only on critical severity findings |
| `--fail-on high` | Fail on high or critical findings |
| `--fail-on medium` | Fail on medium, high, or critical findings |
| `--fail-on low` | Fail on low, medium, high, or critical findings |
| `--fail-on any` | Fail on any finding (including info) |

## GitLab CI Example

```yaml
# .gitlab-ci.yml
security-test:
  stage: test
  image: python:3.10
  script:
    - pip install humanbound
    - hb test --wait --fail-on high
    - hb logs --format json -o security-results.json
  artifacts:
    paths:
      - security-results.json
    when: always
  variables:
    HUMANBOUND_API_KEY: $HB_API_KEY
```

!!! info "Tip"
    Always use `--wait` in CI/CD pipelines to ensure the test completes before the job finishes. Use `--fail-on` to enforce security quality gates.
