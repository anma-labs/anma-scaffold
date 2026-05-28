# ANMA — AI-Native Modular Architecture

**Plain-YAML module contracts that help AI coding agents understand your codebase in ~350 tokens instead of 5,000–20,000.**

No hallucinated interfaces. No undeclared dependencies. No silent integration bugs.

ANMA is a lightweight scaffold for AI-assisted software development. Each module gets a compact, machine-readable contract that declares what it provides, what it consumes, which errors it can raise, and which behaviors must never change.

Built for **Claude Code**. Contracts are plain YAML, so any AI tool can read them, but the full design → contract → implementation workflow is optimized for Claude Code.

---

## Why ANMA Exists

AI coding agents often waste context reverse-engineering a codebase before they can safely change it. For a single auth module, an agent may need to inspect controllers, models, serializers, routes, middleware, tests, settings, exceptions, and dependencies just to infer the real interface.

```text
Agent reads auth/controllers/user.py          → 850 tokens
Agent reads auth/models/user.py               → 420 tokens
Agent reads auth/serializers.py               → 380 tokens
Agent reads auth/urls.py                      → 120 tokens
Agent reads auth/middleware.py                → 290 tokens
Agent reads auth/tests/test_user.py           → 640 tokens
Agent reads auth/exceptions.py                → 180 tokens
Agent reads requirements.txt (partial)        → 200 tokens
Agent reads settings.py (partial)             → 350 tokens
Agent infers error types                      → hallucination risk
                                             Total: ~3,400+ tokens
```

ANMA replaces that discovery step with one explicit contract:

```yaml
module: user-auth
version: 1
status: draft

provides:
  - id: register
    input:
      email: string
      password: string
      display_name: string
    output:
      user_id: uuid
      token: string
    errors:
      - EMAIL_TAKEN
      - WEAK_PASSWORD
      - INVALID_EMAIL
    invariants:
      - "auto-sends verification email"
      - "password must be at least 8 characters"

  - id: login
    input:
      email: string
      password: string
    output:
      user_id: uuid
      token: string
    errors:
      - INVALID_CREDENTIALS
      - ACCOUNT_LOCKED
    invariants:
      - "same error for wrong password and non-existent email"

consumes: []
```

```text
Agent reads modules/user-auth/CONTRACT.yaml   → ~350 tokens
                                             Total: ~350 tokens
```

The result: the agent sees the module’s inputs, outputs, errors, invariants, and dependencies without guessing from implementation details.

---

## What ANMA Gives You

- **Explicit module boundaries** — every interface, dependency, error, and invariant is declared.
- **Lower token usage** — agents read compact contracts instead of entire implementation trees.
- **Less hallucination** — agents do not invent missing interfaces or guess error names.
- **Safer implementation** — the linter checks contracts before code gets written.
- **Recoverable AI sessions** — modules carry enough state for Claude to resume later.
- **Change impact analysis** — see what breaks before modifying a contract.

---

## When to Use ANMA

Use Claude alone for quick scripts, isolated files, and small prototypes.

Use **Claude + ANMA** when your project has multiple modules that depend on each other and you want AI-assisted development to stay coherent across sessions, features, and implementation passes.

| Scenario | Claude alone | Claude + ANMA |
|---|---|---|
| **1–3 files** | Works great | Usually overkill |
| **5+ modules** | May re-infer interfaces differently across sessions | Reads declared contracts |
| **Adding a feature later** | Re-reads source and guesses architecture | Reads contracts and checks impact |
| **Stopping mid-project** | Requires re-explaining context | Resumes from `STATE.yaml` and `MEMORY.yaml` |
| **Integration bugs** | Often found at runtime | Caught earlier by linted contracts |
| **Token usage at scale** | Thousands of tokens per module | Hundreds of tokens per module |

ANMA is best for projects that have enough moving parts to need architectural memory — roughly **5–80 modules** and **1–4 developers**. For tiny scripts or one-off prototypes, it is probably more structure than you need.

---

## Quickstart

Choose the workflow that matches how much control you want.

| Path | Best for | Summary |
|---|---|---|
| **Path 1: Conversational** | Founders, product builders, and non-specialists | Claude designs and implements the project with you in one conversation. |
| **Path 2: Terminal** | Developers who want local control | You manage the repo and use Claude Code to implement from contracts. |

### Path 1: Conversational Workflow

Open [Claude](https://claude.ai) with Claude Opus 4.6+. Upload any product specs, design docs, wireframes, research files, or reference material, then start with:

```text
Clone https://github.com/nxy/anma-scaffold and read CLAUDE.md and CONVENTIONS.yaml.
Let me know when you're ready to build a project with me.
```

Claude reads the architecture rules and becomes your contract architect. Then describe what you want to build:

```text
I want to build a URL shortener. Users create API keys, shorten URLs with
custom slugs, track clicks with analytics, and use rate limiting.
```

Claude identifies module boundaries, drafts contracts, defines interfaces, declares errors, and captures invariants. When the contracts look right, continue with:

```text
Set up the project and implement all modules.
```

When implementation is complete:

```text
Create app.py that wires all modules together.
```

### Path 2: Terminal Workflow

Clone the scaffold and install the only dependency:

```bash
git clone https://github.com/nxy/anma-scaffold my-project
cd my-project
pip install pyyaml
```

Ask Claude to draft contracts from `CLAUDE.md`, `CONVENTIONS.yaml`, and your project description. Then import and validate them:

```bash
python3 tools/init_project.py
python3 tools/import_contracts.py ~/Downloads/*-CONTRACT.yaml
```

Target **0 errors** before implementation. Then run Claude Code:

```bash
claude
```

Prompt it to implement from the contracts:

```text
Read all module contracts and implement them.
```

If implementation reveals a missing dependency, missing error code, or unclear invariant, revise the contract and re-import it:

```bash
python3 tools/import_contracts.py revised-CONTRACT.yaml --force
```

Contract gaps are not failures. They are ANMA catching integration problems before they become silent runtime bugs.

---

## Working Over Time

ANMA is useful after the first implementation, not just during project setup.

To add a feature months later, describe the change normally:

```text
I want to add a waitlist to my event RSVP project. When an event is full,
guests join a queue and get notified when a spot opens.
```

Claude reads the existing contracts, understands how the current modules fit together, updates the relevant contracts, and implements the change without guessing at hidden interfaces.

To resume after a break, start Claude Code again and say:

```text
Continue where we left off.
```

Claude can recover from `STATE.yaml`, `MEMORY.yaml`, and the existing contracts instead of needing you to re-explain the project from scratch.

---

## Project Structure

Each ANMA module is a directory with six small files. An agent usually needs only `CONTRACT.yaml`, `STATE.yaml`, and `MEMORY.yaml` to recover module context.

```text
your-project/
  CONVENTIONS.yaml      # Universal rules: naming, errors, budgets, architecture
  MANIFEST.yaml         # Module registry with status and ownership
  GRAPH.yaml            # Auto-generated dependency graph
  CLAUDE.md             # Agent instructions auto-read by Claude Code

  modules/
    user-auth/
      CONTRACT.yaml     # What this module provides and consumes
      STATE.yaml        # Current work status and blockers
      MEMORY.yaml       # Short institutional memory
      CHANGELOG.yaml    # Version history
      TESTS.yaml        # Contract-derived test cases
      ASSUMPTIONS.yaml  # Implementation details outside the contract

  BUS/                  # Async inter-module communication
  tools/                # Scripts for linting, scaffolding, and analysis
```

Contracts define **what the code must do**. Assumptions describe **how the current implementation does it**. That separation lets you replace implementation details without breaking dependent modules.

Contracts move through a simple lifecycle:

```text
draft → stable → frozen
```

Frozen contracts can only be extended, not modified, which protects modules that already depend on them.

---

## CLI Tools

```bash
python3 tools/anma.py init                       # Clear examples and start fresh
python3 tools/anma.py import contracts/*.yaml    # Import contract files
python3 tools/anma.py lint                       # Validate contracts
python3 tools/anma.py lint --strict              # Require zero warnings
python3 tools/anma.py module add billing         # Scaffold a new module
python3 tools/anma.py graph                      # Regenerate dependency graph
python3 tools/anma.py dashboard                  # Show project health
python3 tools/anma.py impact user-auth           # Show what changes if auth changes
```

Run the full CLI help:

```bash
python3 tools/anma.py
```

Standalone scripts are also available, for example:

```bash
python3 tools/lint_contracts.py
```

---

## Real-World Results

In a [4-module URL shortener demo](https://github.com/nxy/anma-demo-url-shortener), contracts caught 5 integration bugs during implementation, including undeclared dependencies, missing error codes, and absent BUS events.

A larger production test scaffolded 18 modules with 104 interfaces in one Claude Code session:

| Metric | Result |
|---|---:|
| Modules scaffolded | 18 |
| Interfaces implemented | 104 |
| Tests generated | 239 |
| Input tokens per session | ~14,600 |
| Total API cost | $31 |
| Time | 91 minutes |

This repository includes 3 example modules with 14 interfaces so you can inspect the format immediately.

---

## FAQ

### How is ANMA different from OpenAPI or Swagger?

OpenAPI describes HTTP endpoints. ANMA describes internal module boundaries: interfaces, invariants, errors, dependencies, state, memory, assumptions, and change impact. Use OpenAPI for your public API and ANMA for your internal architecture.

### Do I have to use Claude?

The full workflow is built and tested for Claude Code. The contract format is plain YAML, so other LLMs can read it, but the end-to-end workflow is optimized for Claude Code.

### Is this just documentation?

No. Documentation describes what code does. ANMA contracts prescribe what code must do. Because contracts are machine-readable and linted, they can break the build when interfaces, errors, dependencies, or invariants are inconsistent.

### Is ANMA a framework?

No. ANMA is a convention plus a set of scripts. It does not replace your web framework, database, runtime, or deployment stack.

### What is ANMA probably overkill for?

One-off scripts, tiny prototypes, projects with only a few files, and teams that do not plan to use AI agents during design or implementation.

---

## Requirements

- Python 3.8+
- PyYAML

Install PyYAML:

```bash
pip install pyyaml
```

No other dependencies are required.

---

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md) — the 7 design principles
- [Contract Guide](docs/CONTRACT-GUIDE.md) — writing effective contracts
- [Quickstart Guide](docs/QUICKSTART.md) — detailed setup walkthrough

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[BSL 1.1](LICENSE) — free to use for any project. You cannot use it to build a competing scaffold product.

The license converts to Apache 2.0 on May 23, 2029.
