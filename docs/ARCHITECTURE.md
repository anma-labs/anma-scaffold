# ANMA Architecture

## Overview

ANMA (AI-Native Modular Architecture) structures projects as a collection of modules, each fully described by YAML contracts. The architecture optimizes for AI agent comprehension — not human developer ergonomics (though it helps there too).

## Core Principle

**Design for replacement, not continuity.**

Any agent — human or AI — can take over any module by reading its 6 files. No tribal knowledge, no onboarding sessions, no context from previous conversations.

## File Hierarchy

```
project-root/
│
├── CONVENTIONS.yaml       # Universal rules: error format, naming, lifecycle
├── MANIFEST.yaml          # Module registry: what exists, who owns it
├── GRAPH.yaml             # Dependency graph (auto-generated)
├── CLAUDE.md              # AI agent instructions
│
├── modules/
│   └── <module-name>/
│       ├── CONTRACT.yaml  # Interface specification (the source of truth)
│       ├── STATE.yaml     # Current status, task, blockers
│       ├── MEMORY.yaml    # Accumulated decisions and discoveries
│       ├── CHANGELOG.yaml # What changed and when
│       ├── TESTS.yaml     # Contract-derived test expectations
│       ├── ASSUMPTIONS.yaml # Implementation details
│       └── BUS/
│           ├── requests/  # Incoming change requests from other modules
│           └── deltas/    # Outgoing contract change notifications
│
├── BUS/                   # Project-wide inter-module communication
│   ├── requests/
│   └── deltas/
│
└── tools/                 # Linting, scaffolding, analysis (23 scripts)
```

## Context Loading Order

When an agent starts work on a module, it reads files in this order:

1. **CONVENTIONS.yaml** — learn the universal rules
2. **MANIFEST.yaml** — understand what modules exist and their status
3. **GRAPH.yaml** — see how modules depend on each other
4. **CONTRACT.yaml** — read the target module's interface spec
5. **STATE.yaml** — check current work status and blockers
6. **MEMORY.yaml** — absorb accumulated institutional knowledge

This order is not optional. It ensures agents build context from general → specific, never guessing at interfaces.

## The 6 Module Files

### CONTRACT.yaml (Source of Truth)

Declares what the module provides and what it consumes.

```yaml
module: user-auth
version: 1
status: stable

provides:
  - id: register
    input: { email: string, password: string }
    output: { user_id: uuid, token: string }
    errors: [EMAIL_TAKEN, WEAK_PASSWORD]
    invariants:
      - "auto-sends verification email"

consumes:
  - module: notifications
    interfaces: [send_notification]
    via: BUS
```

Key fields:
- **provides** — interfaces this module exposes. Each has typed inputs, outputs, possible errors, and behavioral invariants.
- **consumes** — interfaces from other modules this one depends on. Specifies direct (synchronous) or BUS (async) consumption.
- **contract_rules** — what changes are allowed: `allowed`, `notify`, `breaking`, or `forbidden`.
- **status** — lifecycle stage: `draft` → `stable` → `frozen`.

### STATE.yaml (Work Status)

```yaml
module: user-auth
current_task: "implement password reset flow"
status: in_progress
blockers:
  - "waiting on notifications module for email template support"
```

Updated by agents as they work. Other agents check this before filing cross-module requests.

### MEMORY.yaml (Institutional Knowledge)

```yaml
module: user-auth
entries:
  - "decision: bcrypt over argon2 — library availability on Cloud Run"
  - "warning: Apple OAuth returns relay emails, must handle in register"
```

Capped at 20 entries, 100 characters each. Decisions supersede discoveries. Agents curate actively — delete stale entries before adding.

### CHANGELOG.yaml (History)

Records contract changes with version numbers.

### TESTS.yaml (Contract-Derived Tests)

Test cases derived directly from contract invariants. Each interface has test cases with inputs and expected outputs or errors.

### ASSUMPTIONS.yaml (Implementation Details)

Things that are true about how the module is built but are NOT part of the contract. Implementation can change without breaking consumers.

## Dependencies

### Direct Dependencies (`consumes`)

For synchronous, frequent, stable interfaces. Module A directly calls module B's interface.

```yaml
consumes:
  - module: user-auth
    interfaces: [verify_token]
```

### BUS Dependencies (`via: BUS`)

For async, one-time, or fan-out communication. Module A publishes an event; interested modules subscribe.

```yaml
consumes:
  - module: todo-api
    interfaces: [complete_todo]
    via: BUS
```

**Rule of thumb:** Direct when synchronous/frequent/stable. BUS when one-time/fire-and-forget/cross-cutting.

## Multi-Agent Workflows

ANMA supports a three-level agent hierarchy: **module agents** → **managers** → **orchestrator**.

- **Module agents** work on a single module. They read the module's 6 files, implement interfaces, and write to MEMORY.yaml and STATE.yaml. They never touch another module's files.
- **Managers** scope which modules an agent can touch. A manager owns a group of related modules and coordinates work within that group — sequencing tasks, resolving intra-group dependencies, and reviewing contract changes.
- **The orchestrator** delegates across managers. It handles project-wide concerns: cross-cutting migrations, contract freezes, dependency conflicts between manager groups.

This maps to MANIFEST.yaml:

```yaml
managers:
  core-manager: { owns: [user-auth, todo-api, notifications] }

orchestrator: active
```

The hierarchy maps naturally to subagent systems like Claude Code's `.claude/agents/`, where each agent file can be scoped to a manager's module set. The linter enforces manager assignments (P5: every module has a manager, no manager owns more than 7 modules).

**Current status:** The hierarchy is designed and the linter validates it. Multi-agent orchestration across managers hasn't been demonstrated end-to-end yet — working examples will be added when validated in production.

## Contract Lifecycle

```
draft → stable → frozen
                    ↓
            breaking-change (temporary, while migrating)
                    ↓
              deprecated (end of life)
```

- **draft** — actively being designed. Changes are expected.
- **stable** — consumers can depend on it. Changes require notification.
- **frozen** — can only be extended. Modifications and removals are forbidden.
- **breaking-change** — temporary state during migration.
- **deprecated** — scheduled for removal.

## Error Conventions

All errors follow a consistent shape:

```yaml
{ code: "EMAIL_TAKEN", message: "An account with this email already exists", details: null }
```

Naming patterns:
- `{ENTITY}_NOT_FOUND` — resource doesn't exist
- `{ACTION}_FAILED` — operation didn't succeed
- `INVALID_{FIELD}` — input validation failure
- Cross-cutting: `RATE_LIMITED`, `UNAUTHORIZED`, `FORBIDDEN`

## Granularity Rules

- Minimum 3 interfaces per module (if fewer, merge with another)
- Maximum 7 interfaces per module (beyond that, consider splitting)
- Split threshold: 12 interfaces — must split

These constraints keep modules right-sized for AI agent context windows.
