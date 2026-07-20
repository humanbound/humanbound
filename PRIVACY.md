# Privacy and Telemetry

The Humanbound **CLI** (`hb`) and **documentation site** (`docs.humanbound.ai`)
collect anonymous usage data to help us understand how they're used and improve
them. This document is the authoritative description of what we collect, what we
don't, and how to disable or refuse it — for **both** surfaces.

> **Visiting from the docs site?** Jump to [Docs site](#docs-site-analytics) —
> the rest of this document is about the `hb` command-line tool.

## Scope

This document covers **two surfaces**:

- **The `hb` CLI** — anonymous usage telemetry (the bulk of this document).
- **The documentation site** (`docs.humanbound.ai`) — anonymous web analytics
  and an advertising pixel (the Reddit Pixel); see [Docs site](#docs-site-analytics).

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

- Telemetry is **on by default**. Before you log in, events carry an
  anonymous machine UUID and your IP address — used only to derive an
  approximate location (country, region, city, and coarse coordinates); the IP
  itself is not stored.
- **After you log in** with `hb login`, events are tied to an opaque user
  identifier (your Auth0 `sub`), and your account **email** is attached as a
  person property.
- Disable with `hb telemetry disable`, `HB_TELEMETRY_DISABLED=1`, or
  `DO_NOT_TRACK=1`.
- Automatically disabled in CI, editable dev installs, and when stdout is
  piped (non-TTY).
- Data goes to PostHog EU Cloud and is retained for 1 year.

## What we collect

Every event includes these baseline properties that we set explicitly:

| Property | Example | Why |
|---|---|---|
| `source` | `cli` | Distinguishes CLI events from Humanbound Platform events in the shared analytics project |
| `hb_version` | `2.0.4` | Correlate behavior to releases |
| `is_authenticated` | `true` / `false` | Funnel state |
| `distinct_id` | `tlm_<uuid>` / `auth0\|abc123` | Anonymous machine ID until you log in, then a stable opaque identifier so events can be attributed to your Humanbound account |

In addition, the PostHog Python client library automatically attaches a small
set of properties to every event it sends. Most are technical metadata; one
is a derived, approximate location:

- `$os`, `$os_version` (e.g. `Mac OS X`, `15.5`)
- `$python_version`, `$python_runtime` (e.g. `3.12.10`, `CPython`)
- `$lib`, `$lib_version` (always `posthog-python` plus the SDK version)
- `$geoip_*` — an approximate location PostHog derives from the request's source
  IP at ingestion: country, region, and city, plus coarse map coordinates and
  related fields, accurate only to roughly city level. PostHog discards the raw
  IP ("Discard client IP data"). Applies to every event while telemetry is
  enabled, including before login.

We do not have ability to opt out of these PostHog-attached properties individually;
disabling telemetry entirely (see below) stops all of them.

For events sent **while you're logged in**, we additionally attach your
account **email** as a PostHog person property (`$set: { email }`), read
locally from `~/.humanbound/credentials.json`. Anonymous, pre-login events
never carry an email.

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

- Hostnames, OS usernames
- File paths, repository paths, endpoint URLs, API base URLs
- Test prompts, model responses, finding text, configuration file contents
- Environment variable *values* (we only check the *presence* of CI sentinels)
- Authentication tokens, API keys, or refresh tokens
- Names, organization names, billing details

Your IP address is used transiently for geolocation but **not stored** — see
[What we collect](#what-we-collect).

## Identity

**Before you log in:** every event carries an anonymous machine UUID stored
in `~/.humanbound/telemetry.json` (mode 0600). Different machines get
different UUIDs. While telemetry is enabled, each event's source IP is used
transiently for geolocation (see [What we collect](#what-we-collect)); the IP
is not stored or linked to the UUID.

**When you run `hb login` successfully:** we send PostHog's `$identify` call
to associate the prior anonymous UUID with an **opaque user identifier**
(your Auth0 `sub`, e.g. `auth0|abc123`), and subsequent events attach your
account email as a person property (`$set: { email }`). From that point on,
telemetry events from your machine are tagged with this opaque identifier
instead of the anonymous UUID. PostHog stitches the prior anonymous timeline
to your account so we can measure CLI→Platform conversion.

If you'd rather not associate telemetry events with your account at all, the
supported path is to **not log in to the CLI**. Local mode (`hb test --local`,
basic `hb posture`, etc.) works without login and never associates events
with your account.

**Logging out:** `hb logout` reverts the CLI to the anonymous machine UUID,
but this is **not** re-anonymization — login permanently aliases that UUID to
your account in PostHog and stores your email as a person property, so events
from this machine stay associated with your account. The UUID is not reset on
logout.

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
- Retention: **1 year** from event ingestion.

## Sub-processors

We share data with the following third-party processors:

| Processor | Purpose | Location | Terms |
|---|---|---|---|
| PostHog | Product analytics; receives the request IP for geolocation (discarded after deriving an approximate location) and, for logged-in CLI users, the account email | EU (Frankfurt) | [posthog.com/terms](https://posthog.com/terms), [posthog.com/dpa](https://posthog.com/dpa) |
| Reddit | Advertising measurement, docs site (with advertising consent) | United States | [Advertising Data Processing Agreement](https://business.reddithelp.com/s/article/Reddit-Advertising-Data-Processing-Agreement) |

PostHog acts as a Data Processor under GDPR Art. 28. Our use of PostHog is
governed by their published Terms of Service and Data Processing Addendum
(linked above). They store and process the telemetry data on our behalf
and, per their published terms, do not use it for their own purposes.

**Reddit** receives docs-site advertising data — a page-visit signal plus
standard ad signals (see [Advertising](#advertising-reddit-pixel)) — **only when
you accept advertising cookies**. Any transfer to the United States is governed
by the international-transfer terms in Reddit's
[Advertising Data Processing Agreement](https://business.reddithelp.com/s/article/Reddit-Advertising-Data-Processing-Agreement).

## Docs site analytics

The documentation site (`docs.humanbound.ai`) sends **anonymous** web analytics
to the same PostHog project as the CLI. There is no login on the docs site, so
nothing is ever tied to an account, an email, or a name.

- **Cookieless by default:** until you accept **Analytics** in the cookie
  banner, PostHog stores nothing on your device — no cookies, no local storage —
  and each visit is a fresh anonymous session. Your IP address is never
  recorded as an event property (`ip: false`, with `$ip`/`$ip_address` on a
  denylist) and server-side IP geolocation is disabled (`$geoip_disable: true`).
- **With consent:** we keep a first-party identifier in your browser's local
  storage to recognize returning visits, and PostHog derives an approximate
  location from your IP, then discards it (as in
  [What we collect](#what-we-collect)). Withdraw anytime via the banner to
  return to the cookieless, IP-free behavior above.
- **What we collect:** page views and traffic source only, tagged `source: docs`,
  plus derived location once you've consented (see above). Autocapture is off,
  so individual clicks and form inputs are never captured. *(The optional
  advertising pixel below is different — see Advertising.)*
- **Do Not Track:** if your browser sends a `DNT` signal, no analytics are sent.
- **Region & processor:** PostHog EU Cloud (Frankfurt) — same processor and DPA
  as [Sub-processors](#sub-processors) above.

### Advertising (Reddit Pixel)

The docs site uses the **Reddit Pixel** to measure the effectiveness of our
advertising on Reddit. It runs **only with your consent** and is handled
separately from the anonymous analytics above:

- **Separate consent.** It is gated on its own **Advertising** cookie category —
  distinct from Analytics — so you can accept analytics but reject advertising.
  Nothing loads and nothing is sent unless you accept advertising cookies (legal
  basis: your consent, GDPR Art. 6(1)(a)).
- **What it sends:** a page-visit signal only. The docs site has no login or
  forms, so no email or account data is involved.
- **What it collects:** once loaded with your consent, the pixel collects standard
  advertising signals — your IP address, browser/device information, screen size,
  and a Reddit click identifier. Unlike our own analytics, these are shared with
  **Reddit, Inc.** (United States) — see [Sub-processors](#sub-processors).
- **Withdrawing consent:** change or withdraw your choice anytime via the cookie
  banner ("Manage").

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
