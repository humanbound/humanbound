# Privacy and Telemetry

The Humanbound CLI (`hb`) collects anonymous usage data to help us understand
how the tool is used and improve it. This document is the authoritative
description of what we collect, what we don't, and how to disable it.

## Scope

This document describes how the `hb` CLI handles **anonymous usage telemetry**.
For broader privacy questions about the Humanbound Platform — data collected
via `api.humanbound.ai`, account data, billing, support — contact
[privacy@humanbound.ai](mailto:privacy@humanbound.ai).

This document does **NOT** cover:

- Authentication tokens stored locally in `~/.humanbound/credentials.json`
- LLM provider API keys you configure (e.g. OpenAI, Anthropic) — those stay on
  your machine and are never sent to Humanbound
- Data you explicitly send to `api.humanbound.ai` by using `hb test`,
  `hb connect`, etc. while logged in (test configurations, scopes, findings,
  posture data) — covered by the platform privacy policy linked above
- Prompts and responses exchanged with your configured LLM provider during
  local-mode testing — those go directly from your machine to that provider
  and never touch Humanbound infrastructure

## TL;DR

- Telemetry is **on by default**. Before you log in, events carry only an
  anonymous machine UUID and no personal data.
- **After you log in** with `hb login`, events are associated with an opaque
  user identifier (your Auth0 `sub`) so we can measure CLI→Platform
  conversion.
- Disable with `hb telemetry disable`, `HB_TELEMETRY_DISABLED=1`, or
  `DO_NOT_TRACK=1`.
- Automatically disabled in CI, editable dev installs, and when stdout is
  piped (non-TTY).
- Data goes to PostHog EU Cloud (Frankfurt region) and is retained for
  24 months.

## What we collect

Every event includes these baseline properties that we set explicitly:

| Property | Example | Why |
|---|---|---|
| `source` | `cli` | Distinguishes CLI events from Humanbound Platform events in the shared analytics project |
| `hb_version` | `2.0.4` | Correlate behavior to releases |
| `is_authenticated` | `true` / `false` | Funnel state |
| `distinct_id` | `tlm_<uuid>` / `auth0\|abc123` | Anonymous machine ID until you log in, then a stable opaque identifier so events can be attributed to your Humanbound account |

In addition, the PostHog Python client library automatically attaches a small
set of properties to every event it sends. These are technical metadata only —
no personal data — and include:

- `$os`, `$os_version` (e.g. `Mac OS X`, `15.5`)
- `$python_version`, `$python_runtime` (e.g. `3.12.10`, `CPython`)
- `$lib`, `$lib_version` (always `posthog-python` plus the SDK version)
- `$geoip_disable: true` — PostHog's server-side IP geolocation is disabled on our project

We do not have ability to opt out of these PostHog-attached properties individually;
disabling telemetry entirely (see below) stops all of them.

The seven events:

| Event | When it fires | Event-specific properties |
|---|---|---|
| `install` | First enabled run on this machine | *(baseline only)* |
| `init` | After `hb connect` completes | `mode`, `success`, `duration_ms` |
| `test_start` | When `hb test` starts | `test_level`, `category`, `is_local` |
| `test_complete` | When `hb test` finishes | `test_level`, `category`, `is_local`, `outcome`, `duration_ms`, `finding_count` |
| `posture_view` | When posture is rendered | `is_local`, `mode`, `has_coverage` |
| `findings_view` | When findings list is rendered | `filter_applied` |
| `gated_command_hit` | When a platform-only feature is attempted without login | `command` (e.g. `hb monitor`) |

## What we don't collect

We explicitly **do not** send:

- Hostnames, OS usernames, IP addresses (PostHog disables server-side IP
  geolocation on our project)
- File paths, repository paths, endpoint URLs, API base URLs
- Test prompts, model responses, finding text, configuration file contents
- Environment variable *values* (we only check the *presence* of CI sentinels)
- Authentication tokens, API keys, or refresh tokens
- Names, organization names, billing details
- Your email address

## Identity

**Before you log in:** every event carries an anonymous machine UUID stored
in `~/.humanbound/telemetry.json` (mode 0600). Different machines get
different UUIDs. No personal data is associated with the UUID — it's a fresh
random value generated locally on first run.

**When you run `hb login` successfully:** we send PostHog's `$identify` call
to associate the prior anonymous UUID with an **opaque user identifier**
(your Auth0 `sub`, e.g. `auth0|abc123`). From that point on, telemetry events
from your machine are tagged with this opaque identifier instead of the
anonymous UUID. PostHog stitches the prior anonymous timeline to your account
so we can measure CLI→Platform conversion.

If you'd rather not associate telemetry events with your account at all, the
supported path is to **not log in to the CLI**. Local mode (`hb test --local`,
basic `hb posture`, etc.) works without login and never associates events
with your account.

## How to disable

Any of these works:

```bash
hb telemetry disable                  # Persistent, this machine
export HB_TELEMETRY_DISABLED=1        # One shell session
export DO_NOT_TRACK=1                 # Honored by many CLIs (see consoledonottrack.com)
```

Check current state:

```bash
hb telemetry status
```

Re-enable later:

```bash
hb telemetry enable
```

## Auto-disabled environments

Telemetry is automatically off (no event is sent, no UUID is generated) in
any of:

- CI environments: `CI`, `GITHUB_ACTIONS`, `BUILDKITE`, `JENKINS_HOME`,
  `TF_BUILD`, `GITLAB_CI`, `CIRCLECI`, `TRAVIS`
- Editable dev installs of this repo, or when `HUMANBOUND_DEV=1`
- When `stdout` is not a TTY (piped or redirected output)
- When `DO_NOT_TRACK=1` or `HB_TELEMETRY_DISABLED=1` is set

## Data destination and retention

- Destination: PostHog EU Cloud, region Frankfurt (`eu.i.posthog.com`)
- Retention: **24 months** from event ingestion. Events older than this are
  deleted from PostHog automatically per our project's retention configuration.

## Sub-processors

We share telemetry data with one third-party processor:

| Processor | Purpose | Location | Terms |
|---|---|---|---|
| PostHog | Product analytics ingestion and dashboard | EU (Frankfurt) | [posthog.com/terms](https://posthog.com/terms), [posthog.com/dpa](https://posthog.com/dpa) |

PostHog acts as a Data Processor under GDPR Art. 28. Our use of PostHog is
governed by their published Terms of Service and Data Processing Addendum
(linked above). They store and process the telemetry data on our behalf
and, per their published terms, do not use it for their own purposes.

## Docs site analytics

The documentation site (`docs.humanbound.ai`) sends **anonymous** web analytics
to the same PostHog project as the CLI. There is no login on the docs site, so
nothing is tied to an account and no personal data is collected.

- **Cookieless by default:** until you accept **Analytics** in the cookie
  banner, PostHog stores nothing on your device — no cookies, no local storage —
  and each visit is a fresh anonymous session.
- **With consent:** if you accept, we keep a first-party identifier in your
  browser's local storage to recognize returning visits. You can change or
  withdraw your choice anytime via the banner.
- **What we collect:** page views and traffic source only, tagged `source: docs`.
  Autocapture is off, so individual clicks and form inputs are never captured.
- **No IP storage:** server-side IP geolocation is disabled (`$geoip_disable`).
- **Do Not Track:** if your browser sends a `DNT` signal, no analytics are sent.
- **Region & processor:** PostHog EU Cloud (Frankfurt) — same processor and DPA
  as [Sub-processors](#sub-processors) above.

## Your rights under GDPR

For events sent **after you log in** (`hb login`), the data is associated
with your account via an opaque user identifier and therefore qualifies as
personal data under GDPR. You have the right to:

- **Access** the data we hold about you (Art. 15)
- **Correct** inaccurate data (Art. 16)
- **Delete** your data — the "right to be forgotten" (Art. 17)
- **Restrict** processing (Art. 18)
- **Export** your data in a portable, machine-readable format (Art. 20)
- **Object** to processing (Art. 21)

To exercise any of these rights, email
[privacy@humanbound.ai](mailto:privacy@humanbound.ai) from the email
address associated with your Humanbound account. We respond within 30
days as required by GDPR.

For events sent **before you log in** (anonymous `tlm_<uuid>` identifier),
these rights have no practical mechanism — your data is not linked to any
identifier we can trace back to you. The most effective "right to be
forgotten" for anonymous data is to:

1. Delete your local `~/.humanbound/telemetry.json` file
2. Run `hb telemetry disable` to prevent further events

After those two steps, no further anonymous events from your machine reach
PostHog, and the historical anonymous events cannot be associated with you
by us or by PostHog.

## Changes to this policy

This document lives in the repository and is versioned alongside the CLI.
Material changes are noted in `CHANGELOG.md`.

## Questions or requests

Privacy questions: [privacy@humanbound.ai](mailto:privacy@humanbound.ai)
GDPR data subject requests: same address.
