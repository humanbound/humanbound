# Projects

Projects represent AI agents under test. Each project contains configuration, scope definitions, and associated test experiments.

## List Projects

```bash
hb projects list
```

## Set Active Project

```bash
hb projects use <id>
```

## Show Project Details

```bash
# Show current project
hb projects show

# Show specific project
hb projects show <id>

# Alternative: show active project
hb projects current
```

## Update Project

```bash
# Update current project
hb projects update --name "New Name"

# Update specific project
hb projects update <id> --description "Updated description"

# Set the agent's capability surface
hb projects update --capabilities tools=on,memory=off
hb projects update --capabilities all=off,tools=on,reasoning_model=on
```

### `--capabilities` flag

Declares which agentic features the project uses, so the platform can target the
right test categories. Accepts comma-separated `key=value` pairs.

- **Keys:** `tools`, `memory`, `inter_agent`, `reasoning_model`, plus the shorthand
  `all` which sets every key in one step.
- **Values:** `on` / `off`, `true` / `false`, `1` / `0`, `yes` / `no` (case-insensitive).
  Bare keys (e.g. `tools`) imply `on`.
- **Order matters:** pairs apply left-to-right, so `all=off,tools=on` resets the set
  and then enables `tools`.

Updating capabilities archives the project's existing datasets (so the test coverage
plan is regenerated). A confirm prompt is shown unless `--yes` / `-y` is passed.

## Delete Project

```bash
# Delete with confirmation
hb projects delete <id>

# Skip confirmation
hb projects delete <id> --force
```

## Project Status

Check if anything is running on the project — experiments, campaigns, monitoring state.

```bash
# One-shot status check
hb projects status

# Watch mode — polls every 3 minutes until idle
hb projects status -w
```

Shows: active/idle state, running experiments, posture grade, monitoring status, active campaign.

## Generate Project Report

```bash
# Generate HTML report (opens in browser by default)
hb projects report

# Save to file
hb projects report -o report.html

# Save without opening browser
hb projects report -o report.html --no-open
```

!!! warning "Warning"
    Deleting a project will also delete all associated experiments, logs, and findings. This action cannot be undone.
