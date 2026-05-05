# Command Reference

Complete reference of all available commands, organized by category.

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
| `hb connect --repo <path>` `[PREVIEW]` | Also infers the capability surface from source patterns |
| `hb projects list` | List all projects in current org |
| `hb projects use <id>` | Set active project for subsequent commands |
| `hb projects show [id]` | Show project details (current or specific) |
| `hb projects current` | Show active project information |
| `hb projects status` | Show project activity (running experiments, posture, monitoring) |
| `hb projects status -w` | Watch project activity, poll every 3 minutes until idle |
| `hb projects update` | Update project name, description, or capability surface (`--capabilities`) |
| `hb projects delete <id>` | Delete project and all associated data |

## Experiments

| Command | Description |
|---|---|
| `hb test` | Create and run new security test experiment |
| `hb experiments list` | List all experiments for current project |
| `hb experiments show <id>` | Show detailed experiment information |
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
| `hb assessments show <id>` | View assessment detail (posture before/after, drift, test count) |
| `hb assessments report <id>` | Generate assessment HTML report with full test logs (-o, --no-open) |
| `hb projects report` | Generate project HTML security report (-o, --no-open) |
| `hb orgs report` | Generate organisation-wide HTML report (-o, --no-open) |
| `hb experiments report <id>` | Generate experiment HTML report with methodology context (-o, --no-open) |

## Security

| Command | Description |
|---|---|
| `hb guardrails` | Export learned security rules and patterns |
| `hb campaigns` | View current ASCAM campaign plan |
| `hb campaigns terminate` | Stop running campaign |
| `hb monitor` | Start, pause, or resume continuous monitoring |

## SIEM / Sentinel

| Command | Description |
|---|---|
| `hb sentinel` | Show Sentinel setup instructions and available commands |
| `hb sentinel deploy --rg <name>` | Deploy infrastructure, create webhook, set signing secret, and verify -- fully end-to-end |
| `hb sentinel deploy --rg <name> --no-connect` | Deploy infrastructure only, skip webhook setup |
| `hb sentinel connect --url <url>` | Register webhook manually (only needed with --no-connect) |
| `hb sentinel test` | Send a test event to verify connectivity |
| `hb sentinel status` | Check connector health and recent deliveries |
| `hb sentinel sync` | Replay historical events to Sentinel for backfill |
| `hb sentinel disconnect` | Remove the Sentinel webhook and local configuration |

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
