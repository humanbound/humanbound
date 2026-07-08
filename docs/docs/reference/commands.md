---
description: "Complete hb CLI reference — every command and flag, grouped by workflow — auth, projects, test, redteam, posture, logs, MCP."
keywords:
  - hb command reference
  - humanbound CLI reference
  - hb commands list
  - humanbound CLI commands
  - CLI cheatsheet
  - command index
---

# Command Reference

The complete `hb` CLI reference, organised into eight categories: global flags, authentication (login / logout / whoami / orgs), projects, experiments (test execution), results (logs / posture / coverage / findings / assessments / reports), security (guardrails / campaigns / monitor), configuration (providers / api-keys / members), and help & shell (docs / completion / --help). Each table lists every command with its purpose; use `hb <command> --help` for full flag documentation.

## Global

| Command | Description |
|---|---|
| `hb --version` | Print CLI version |
| `hb --base-url URL` | Use custom API endpoint (on-prem installations) |

## Authentication

| Command | Description |
|---|---|
| `hb login` | Authenticate via OAuth browser flow |
| `hb logout` | Clear local credentials and optionally revoke session |
| `hb whoami` | Show current user, org, and project |
| `hb switch <org-id>` | Switch active organisation context |
| `hb orgs list` | List organisations you have access to |
| `hb orgs current` | Show the currently selected organisation |
| `hb orgs subscription` | Show subscription details (plan, quota, features) |

## Projects

| Command | Description |
|---|---|
| `hb connect` | Connect your agent or scan a cloud platform |
| `hb connect -l system` | Connect with deeper testing level (unit/system/acceptance) |
| `hb connect --no-test` | Connect and create project but skip the auto-test step |
| `hb connect --test-category <path>` | Choose which test family the auto-test runs (default: `humanbound/adversarial/owasp_agentic`) |
| `hb connect --scope ./scope.yaml` | Use a pre-made scope file as input; the backend analyses it and proposes additive intents before project creation |
| `hb connect --vendor <id>` | Discover and onboard a hosted-platform agent (currently `openai`); credential from env or a hidden prompt; requires login; mutually exclusive with `--endpoint` |
| `hb projects list` | List all projects in current org |
| `hb projects use <id>` | Set active project for subsequent commands |
| `hb projects show [id]` | Show project details (current or specific) |
| `hb projects current` | Show active project information |
| `hb projects status` | Show project activity (running experiments, posture, monitoring) |
| `hb projects status -w` | Watch project activity, poll every 3 minutes until idle |
| `hb projects update` | Update project name or description |
| `hb projects delete <id>` | Delete project and all associated data |

## Experiments

| Command | Description |
|---|---|
| `hb test` | Create and run new security test experiment |
| `hb experiments list` | List all experiments for current project |
| `hb experiments show <id> [--config]` | Show detailed experiment information; `--config` prints the configuration the run used (bot integration, scope, context) as reusable JSON |
| `hb experiments status [id] [--all]` | Check experiment status (single, watch, or all-experiments dashboard) |
| `hb experiments wait <id>` | Block until experiment completes (CI/CD) |
| `hb experiments terminate <id>` | Stop running experiment |
| `hb experiments delete <id>` | Delete experiment and logs |
| `hb status [--all]` | Check status of latest experiment or all experiments (alias) |

## Results

| Command | Description |
|---|---|
| `hb logs` | List logs from the latest experiment |
| `hb logs <experiment-id>` | View logs for a specific experiment |
| `hb logs --assessment <id>` | List logs for a specific assessment |
| `hb logs --finding <id>` | List logs linked to a specific finding |
| `hb logs --verdict pass\|fail` | Filter by verdict |
| `hb logs --category <name>` | Filter by test category (substring match) |
| `hb logs --from DATE --until DATE` | Filter by date range (ISO 8601) |
| `hb logs --days N` | Shorthand for last N days |
| `hb logs --last N` | Show logs from last N experiments |
| `hb logs --format json\|html\|table` | Output format (default: table) |
| `hb logs -o FILE` | Save output to file |
| `hb logs upload <file>` | Upload conversation logs for evaluation |
| `hb posture` | View security posture score and grade |
| `hb posture --trends` | View historical posture timeline |
| `hb coverage` | View test coverage summary and gaps |
| `hb findings` | List persistent vulnerability findings (--page, --size, -o \<file\>) |
| `hb findings update <id>` | Update finding status or severity |
| `hb findings assign <id>` | Assign finding to a team member |
| `hb assessments` | List past security assessments |
| `hb assessments show [id]` | View assessment detail (posture trajectory, drift, coverage, duration); defaults to the latest |
| `hb assessments terminate [id]` | Stop a running assessment (defaults to the current/latest) |
| `hb assessments report <id>` | Generate assessment HTML report with full test logs (-o, --no-open) |
| `hb projects report` | Generate project HTML security report (-o, --no-open) |
| `hb orgs report` | Generate organisation-wide HTML report (-o, --no-open) |
| `hb experiments report <id>` | Generate experiment HTML report with methodology context (-o, --no-open) |

## Security

| Command | Description |
|---|---|
| `hb guardrails` | Export learned security rules and patterns |
| `hb campaigns` | _Deprecated_ — use `hb assessments` |
| `hb campaigns terminate` | _Deprecated_ — use `hb assessments terminate` |
| `hb monitor` | Start, pause, or resume continuous monitoring |

## Configuration

| Command | Description |
|---|---|
| `hb providers list` | List configured LLM providers |
| `hb providers add` | Add new LLM provider configuration |
| `hb providers update <id>` | Update provider credentials or settings |
| `hb providers remove <id>` | Remove provider configuration |
| `hb api-keys list` | List API keys for programmatic access |
| `hb api-keys create` | Create new API key (shown once) |
| `hb api-keys update <id>` | Update key name or activation status |
| `hb api-keys delete <id>` | Revoke and delete API key |
| `hb members list` | List organisation members |
| `hb members invite` | Invite new member to organisation |
| `hb members delete <id>` | Remove member from organisation |

## Help & Shell

| Command | Description |
|---|---|
| `hb docs` | Open online documentation or specific topic |
| `hb completion [bash\|zsh\|fish]` | Generate shell tab-completion script |
| `hb --help` | Show CLI help and available commands |
| `hb <command> --help` | Show help for specific command |
