# Security policy

Humanbound takes the security of its open-source software seriously. If you
believe you've found a security vulnerability in the `humanbound` package,
please report it privately using one of the channels below.

## Reporting a vulnerability

**Please do not open a public GitHub Issue.** Report vulnerabilities via either:

- **Email:** [security@humanbound.ai](mailto:security@humanbound.ai)
- **GitHub Security Advisories:** the "Report a vulnerability" button on the
  repository's *Security* tab (private, end-to-end)

A clear report will include:

1. The affected version of `humanbound` (and `humanbound-cli` if the old name)
2. A description of the issue and its impact
3. Steps to reproduce or a minimal proof-of-concept
4. Any suggested mitigation

## What happens next

| Timeline | What to expect |
|---|---|
| Within 72 hours | Acknowledgement that the report was received |
| Within 7 days | Initial triage and severity assessment |
| As soon as practical | Coordinated fix, with credit to the reporter unless anonymity is preferred |
| 90 days (default) | Public disclosure window — earlier if a fix has shipped, later if actively exploited and a mitigation is still being prepared |

## Scope

In scope:
- The `humanbound` Python package (engine, SDK, CLI) and its release artifacts on PyPI
- Source code in this repository
- Build and release pipelines (`.github/workflows/`)

Out of scope:
- Vulnerabilities in third-party dependencies (report upstream; we'll track)
- Services at `humanbound.ai` (those have their own disclosure channel — see
  [docs.humanbound.ai/community/](https://docs.humanbound.ai/community/))
- Issues requiring physical access to a user's machine or stolen API keys

## Disclosure policy

Humanbound follows a **coordinated disclosure** model. We request a 90-day
embargo from the date of the fix unless otherwise agreed. Researchers who
follow this policy will be acknowledged in release notes unless they opt out.

## More information

See [docs.humanbound.ai/community/security/](https://docs.humanbound.ai/community/)
for the full policy and supported-version matrix.
