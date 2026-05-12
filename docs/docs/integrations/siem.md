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

## Microsoft Sentinel

The Humanbound Sentinel Connector deploys a dedicated Azure Function into the customer's Azure subscription. Webhook events are pushed to a Log Analytics custom table (`AISecurityEvents_CL`) and surfaced through pre-built Sentinel content:

- **CISO Dashboard** -- 5-tab workbook: Executive Summary, Findings, Drift & Resilience, ASCAM Lifecycle, Incidents
- **4 Analytic Rules** -- Auto-create Sentinel incidents for critical findings, regressions, posture drops, and drift
- **6 Hunting Queries** -- OWASP risk analysis, regression patterns, posture trends, drift timeline, campaign ROI, remediation velocity
- **AI Estate Coverage** -- Dashboard tiles showing actively monitored, paused, and silent projects

### End-to-End Deployment

Deploy the full Sentinel integration with a single command. `hb sentinel deploy` handles everything: infrastructure, connector code, webhook creation, signing secret configuration, and connectivity verification.

```bash
# Deploy everything and auto-connect (one command, zero manual steps)
$ hb sentinel deploy --resource-group rg-humanbound

# Custom location and workspace name
$ hb sentinel deploy --rg rg-demo --location eastus --workspace la-demo

# Deploy infrastructure only, skip webhook setup
$ hb sentinel deploy --rg rg-humanbound --no-connect

# Export the script to review before running
$ hb sentinel deploy --rg rg-humanbound --export-only

# Save script to a specific file
$ hb sentinel deploy --rg rg-humanbound --output deploy.sh
```

The deploy command runs end-to-end: prerequisite check (az + func) -> Azure login -> resource group -> Bicep deployment -> function code publish -> validation (4 automated checks) -> webhook creation -> signing secret configuration -> test ping. After it completes, open the CISO Dashboard in Sentinel -- events flow immediately.

!!! info "Requirements"
    Azure CLI (`az`), Azure Functions Core Tools (`func`), and Humanbound login (`hb login`). Use `--no-connect` to skip the login requirement and deploy infrastructure only. Run `hb sentinel` with no subcommand for install instructions.

### Connect & Manage

If you used `--no-connect` or need to reconnect to a different connector, use the individual commands:

```bash
# Register webhook pointing to your connector (only needed with --no-connect)
$ hb sentinel connect --url https://func-hb-connector-xxx.azurewebsites.net/api/ingest

# Verify connectivity
$ hb sentinel test

# Check connector health and recent deliveries
$ hb sentinel status

# Backfill historical events
$ hb sentinel sync --since 2025-01-01

# Remove the webhook
$ hb sentinel disconnect
```

### Data Sovereignty

The connector runs in **your** Azure subscription. Event data never passes through Humanbound infrastructure -- it flows directly from the webhook to your Log Analytics workspace via the Logs Ingestion API with managed identity authentication.

## Other SIEMs

Webhook events can be routed to any SIEM or automation platform that accepts HTTPS webhooks:

- **Splunk** -- Use an HTTP Event Collector (HEC) endpoint as the webhook URL
- **Google Chronicle** -- Route via a Cloud Function or direct ingestion API
- **Jira / ServiceNow** -- Use automation rules to create tickets from webhook payloads
- **Slack / Teams** -- Forward high-severity events to security channels via incoming webhooks
- **Custom** -- Any HTTPS endpoint that returns 2xx. Humanbound retries 3 times with exponential backoff.

!!! warning "Limit"
    10 webhooks per organisation. Each webhook can filter by event type and/or project to control delivery volume.
