---
description: "Stream security events to your SIEM — findings, posture changes, and drift detections delivered in real time as HMAC-signed webhook events."
---

# SIEM Integration

Humanbound delivers security events in real time to your SOC tooling. Every finding, posture change, drift detection, and ASCAM phase transition is emitted as a structured, HMAC-signed webhook event that any SIEM, ticketing system, or automation platform can consume.

## Webhook Architecture

Webhooks are configured at the organisation level. Each webhook specifies a delivery URL, a shared signing secret, and optional filters by event type or project. When a security event occurs, Humanbound:

1. Persists the event to an immutable audit log (`webhookevents` table)
2. Dispatches to all matching webhooks in a background thread
3. Signs the payload with HMAC-SHA256 (`X-Humanbound-Signature: sha256=...`)
4. Retries up to 3 times with exponential backoff on failure

### Event Types

The platform emits 14 event types:

| Event | Description |
|---|---|
| `finding.created` | New security vulnerability discovered. Severity varies by finding. |
| `finding.regressed` | Previously fixed finding has reappeared. Always high severity. |
| `finding.assigned` | Finding assigned to a team member for remediation. |
| `finding.acknowledged` | Team acknowledges a finding and begins investigation. |
| `finding.resolution_verified` | Fix verified through re-testing. Finding resolved. |
| `finding.resolution_failed` | Re-test shows the fix was ineffective. |
| `posture.grade_changed` | Security posture grade changed (e.g., B -> D). High if degraded. |
| `drift.detected` | Statistical behavioral drift detected in agent responses. |
| `campaign.completed` | ASCAM campaign finished with before/after posture delta. |
| `ascam.activity_started` | ASCAM activity transitioned (e.g., Assess -> Investigate). |
| `ascam.paused` | Continuous monitoring paused for a project. Medium severity. |
| `ascam.resumed` | Continuous monitoring resumed for a project. |
| `quality.degraded` | Quality score dropped below threshold. |
| `quality.regression` | Previously fixed quality issue has reappeared. |

### Payload Structure

Every event is delivered as a ticketing-friendly JSON envelope with top-level `severity`, `title`, and `description` fields -- ready for SIEM rule mapping without parsing nested objects:

```json
{
  "event_type": "finding.created",
  "organisation_id": "uuid",
  "project_id": "uuid",
  "timestamp": 1707840000,
  "severity": "critical",
  "title": "New critical finding: Prompt Injection via System Override",
  "description": "New critical finding: Prompt Injection via System Override [LLM01]",
  "category": "prompt_injection",
  "owasp_category": "LLM01",
  "data": { /* event-specific payload */ }
}
```

### Signature Verification

Verify the `X-Humanbound-Signature` header by computing HMAC-SHA256 over the raw request body using your webhook secret:

```python
import hmac, hashlib

def verify(body: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
```

## SIEMs

Webhook events can be routed to any SIEM or automation platform that accepts HTTPS webhooks:

- **Splunk** -- Use an HTTP Event Collector (HEC) endpoint as the webhook URL
- **Google Chronicle** -- Route via a Cloud Function or direct ingestion API
- **Jira / ServiceNow** -- Use automation rules to create tickets from webhook payloads
- **Slack / Teams** -- Forward high-severity events to security channels via incoming webhooks
- **Custom** -- Any HTTPS endpoint that returns 2xx. Humanbound retries 3 times with exponential backoff.

!!! warning "Limit"
    10 webhooks per organisation. Each webhook can filter by event type and/or project to control delivery volume.
