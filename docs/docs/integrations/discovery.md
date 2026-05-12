---
description: "Discover and assess AI services across your cloud environment — a client-side scan that surfaces shadow AI and feeds findings into the platform."
---

# AI Discovery

Discover and assess AI services across your cloud environment. The discovery pipeline scans your tenant client-side, sends results to the Humanbound platform for security evaluation (38 evidence signals, 15 SAI threat classes), and produces an assessed inventory with posture scoring and model lifecycle tracking.

## Discovery

Run `hb discover` to scan your cloud environment for AI services. The scanner authenticates via device-code flow, queries multiple API layers (service principals, sign-in logs, resource graph, Copilot Studio agents, Azure OpenAI deployments), and sends results to the platform for analysis.

```bash
# Scan and display results
$ hb discover

# Scan, save to inventory, and export HTML report
$ hb discover --save --report

# Verbose mode (show raw API responses from each layer)
$ hb discover --verbose

# Output as JSON
$ hb discover --json
```

The discovery report includes:

- **Deployed Agents** -- Copilot Studio agents with channel, auth, and network details
- **AI Endpoints** -- Azure OpenAI deployments with model lifecycle badges (retired, deprecated, retiring soon)
- **AI Adoption** -- Licensed and consented AI services (M365 Copilot, etc.)
- **In Development** -- ML projects and staged resources
- **Resource Topology** -- Interactive Mermaid diagram showing connections between agents, endpoints, models, and channels
- **Security Evaluations** -- Per-service threat analysis with SAI threat classes, risk scores, and remediation guidance
- **Posture Estimate** -- Organisation-level AI discovery posture score

## Cloud Connectors

Register cloud connectors for persistent discovery. Connectors store encrypted credentials and enable re-discovery (scheduled or on-demand).

```bash
# Register a Microsoft connector
$ hb connectors create --tenant-id <id> --client-id <id> --client-secret

# Register with explicit vendor and display name
$ hb connectors create --vendor microsoft --tenant-id <id> --client-id <id> --name "Production"

# List connectors
$ hb connectors

# Export connectors as HTML report
$ hb connectors --report

# Test connectivity
$ hb connectors test <connector-id>

# Update credentials, name, or status
$ hb connectors update <connector-id> --client-secret
$ hb connectors update <connector-id> --name "New Name" --status disabled

# Remove a connector
$ hb connectors delete <connector-id>
```

## AI Inventory

After running `hb discover --save`, discovered assets are persisted to your AI inventory. Use the inventory commands to view, govern, and onboard assets for security testing.

```bash
# List all inventory assets
$ hb inventory

# Export as HTML report
$ hb inventory --report

# Filter by category, vendor, risk, or sanctioned status
$ hb inventory --category copilot_studio_agent --risk-level high
$ hb inventory --vendor microsoft --sanctioned
$ hb inventory --unsanctioned --risk-level critical

# View asset details (with optional HTML report)
$ hb inventory view <asset-id>
$ hb inventory view <asset-id> --report

# Update governance fields
$ hb inventory update <asset-id> --sanctioned --owner "security@company.com"
$ hb inventory update <asset-id> --department "Engineering" --business-purpose "Customer support"
$ hb inventory update <asset-id> --has-policy --has-risk-assessment

# View AI discovery posture (with optional HTML report)
$ hb inventory posture
$ hb inventory posture --report

# Onboard an asset into a security testing project
$ hb inventory onboard <asset-id>

# Archive an asset
$ hb inventory archive <asset-id>
```

## Model Lifecycle

Discovery tracks model lifecycle status across all endpoints. Models approaching end-of-life are flagged with badges in both the CLI output and HTML report:

- **RETIRED** -- Model is no longer available. Migrate immediately.
- **DEPRECATED** -- Model is deprecated with a known retirement date.
- **RETIRING SOON** -- Model retirement within 90 days. Plan migration.

Lifecycle warnings appear in the hero metrics, executive summary, endpoints table, and resource topology diagram.
