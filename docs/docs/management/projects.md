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
```

## Delete Project

```bash
# Delete with confirmation
hb projects delete <id>

# Skip confirmation
hb projects delete <id> --force
```

!!! warning "Warning"
    Deleting a project will also delete all associated experiments, logs, and findings. This action cannot be undone.
