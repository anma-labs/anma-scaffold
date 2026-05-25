# ANMA — AI-Native Modular Architecture

**Structured contracts that let AI agents understand your codebase in ~250 tokens instead of 5,000-20,000.**

---

## The Problem

AI coding agents waste 70-80% of their context window just *understanding* your codebase before they write a single line of code. Every file read, every dependency traced, every interface guessed — it all burns tokens and produces hallucinations.

Traditional codebases force agents to:
- Read thousands of lines of source to infer interfaces
- Guess at error types and validation rules
- Navigate tangled dependency graphs by trial and error
- Lose context across sessions with no institutional memory

The result: expensive, slow, unreliable AI-assisted development.

## The Solution

ANMA replaces implicit knowledge with explicit YAML contracts. Each module declares exactly what it provides, what it consumes, its invariants, its errors, and its assumptions — in a format optimized for AI consumption.

```yaml
# ~30 lines. An AI agent knows everything it needs.
module: user-auth
version: 1
status: stable

provides:
  - id: register
    input: { email: string, password: string, display_name: string }
    output: { user_id: uuid, token: string }
    errors: [EMAIL_TAKEN, WEAK_PASSWORD, INVALID_EMAIL]
    invariants:
      - "auto-sends verification email"
      - "password must be at least 8 characters"
```

No ambiguity. No guessing. No wasted tokens.

## Real Numbers

This repo ships with 3 example modules (14 interfaces, ~350 tokens each) so you can explore the contract format and run the linter immediately.

At scale, a production test scaffolded 18 modules with 104 interfaces in a single Claude Code session:

| Metric | Value |
|--------|-------|
| Input tokens per session | ~14,600 |
| Cache read tokens | ~32.8M |
| Total API cost | $31 |
| Modules scaffolded | 18 |
| Interfaces implemented | 104 |
| Tests generated | 239 |
| Time (API) | 91 minutes |

The contracts themselves are ~250 tokens each. A traditional codebase of comparable size would require 5,000-20,000 tokens per module just for an agent to orient itself.

## How It Works

```
your-project/
  CONVENTIONS.yaml      # Universal rules (error format, naming, lifecycle)
  MANIFEST.yaml         # Module registry with status and ownership
  GRAPH.yaml            # Auto-generated dependency graph
  CLAUDE.md             # AI agent instructions
  modules/
    user-auth/
      CONTRACT.yaml     # What this module provides and consumes
      STATE.yaml        # Current work status and blockers
      MEMORY.yaml       # Accumulated knowledge (max 20 entries)
      CHANGELOG.yaml    # Version history
      TESTS.yaml        # Contract-derived test cases
      ASSUMPTIONS.yaml  # Implementation details (separate from contract)
    todo-api/
      CONTRACT.yaml
      ...
  BUS/                  # Inter-module communication
    requests/           # Cross-module change requests
    deltas/             # Contract change notifications
  tools/                # Linting, scaffolding, analysis scripts
```

An agent picking up any module reads 6 files and has full context. No history needed. No onboarding. Design for replacement, not continuity.

CLAUDE.md is the agent instruction file — it works with Claude Code, Cursor, Copilot, or any LLM that reads project files.

## 5-Minute Quickstart

### 1. Clone and explore

```bash
git clone <this-repo> my-project
cd my-project
```

### 2. Run the linter

```bash
python3 tools/lint_contracts.py
```

You should see all 3 example modules pass with 0 errors.

### 3. Scaffold a new module

```bash
python3 tools/new_module.py my-feature --manager core-manager --consumes user-auth
```

This creates `modules/my-feature/` with all 6 required files and updates MANIFEST.yaml.

### 4. Define your contract

Edit `modules/my-feature/CONTRACT.yaml`:

```yaml
module: my-feature
version: 1
status: draft
type: regular

purpose: "What this module does in one sentence"

provides:
  - id: do_something
    input: { user_id: uuid, data: string }
    output: { result_id: uuid }
    errors: [INVALID_DATA, UNAUTHORIZED]
    invariants:
      - "what callers can depend on"

consumes:
  - module: user-auth
    interfaces: [verify_token]
```

### 5. Regenerate the dependency graph

```bash
python3 tools/gen_graph.py
```

### 6. Lint again

```bash
python3 tools/lint_contracts.py --strict
```

Zero warnings = ready to implement.

## Before/After: Token Cost Comparison

### Before ANMA (traditional codebase)

```
Agent reads auth/controllers/user.py          → 850 tokens
Agent reads auth/models/user.py               → 420 tokens
Agent reads auth/serializers.py               → 380 tokens
Agent reads auth/urls.py                      → 120 tokens
Agent reads auth/middleware.py                → 290 tokens
Agent reads auth/tests/test_user.py           → 640 tokens
Agent reads auth/exceptions.py               → 180 tokens
Agent reads requirements.txt (partial)        → 200 tokens
Agent reads settings.py (partial)             → 350 tokens
Agent infers error types (hallucination risk) → ???
                                    Total: ~3,400+ tokens (one module)
```

### After ANMA

```
Agent reads modules/user-auth/CONTRACT.yaml   → 250 tokens
                                    Total: 250 tokens (complete understanding)
```

**~14x reduction per module.** For 18 modules, that's ~61,000 tokens saved per session — enough to fit 3-4 more modules in context or skip an expensive context window entirely.

## Tools

ANMA ships with 23 Python scripts in `tools/`:

| Tool | Purpose |
|------|---------|
| `lint_contracts.py` | Validate all contracts (23 checks) |
| `new_module.py` | Scaffold a new module with all 6 files |
| `new_manager.py` | Create a new manager group |
| `remove_module.py` | Safely remove a module |
| `gen_graph.py` | Regenerate GRAPH.yaml from contracts |
| `gen_contract.py` | Generate contract from template |
| `gen_tests.py` | Generate test cases from contracts |
| `gen_claude_md.py` | Regenerate CLAUDE.md from MANIFEST |
| `gen_product_spec.py` | Generate product spec from contracts |
| `graph_viz.py` | Visualize dependency graph (DOT format) |
| `verify_contract.py` | Deep contract verification |
| `compat_matrix.py` | Cross-module compatibility check |
| `plan_migration.py` | Plan contract migrations |
| `contract_diff.py` | Diff contracts between versions |
| `impact.py` | Analyze impact of contract changes |
| `dashboard.py` | Project health dashboard |
| `bus_archive.py` | Archive processed BUS messages |
| `rename_project.py` | Rename the project across all files |
| `smoke_test.py` | Quick validation smoke test |
| `test_linter.py` | Test the linter itself |
| `yaml_editor.py` | Programmatic YAML editing |
| `session_log.py` | Log session activity |
| `anma.py` | Unified CLI for all tools |

### Unified CLI

```bash
python3 tools/anma.py lint              # Run linter
python3 tools/anma.py scaffold my-mod   # New module
python3 tools/anma.py graph             # Regenerate graph
python3 tools/anma.py dashboard         # Project overview
python3 tools/anma.py impact user-auth  # What breaks if auth changes?
```

## Core Concepts

### Contracts over Code
CONTRACT.yaml is the single source of truth. Agents read contracts, not source code. If the contract says an interface returns `EMAIL_TAKEN`, that's what it returns — no need to grep through error handlers.

### Design for Replacement
Any agent can take over any module by reading its 6 files. No onboarding, no tribal knowledge, no context from previous sessions required.

### Explicit Dependencies
GRAPH.yaml shows exactly what depends on what. No hidden imports, no circular dependencies, no surprises. Direct dependencies for synchronous calls, BUS for async fan-out.

### Memory with Limits
MEMORY.yaml keeps institutional knowledge — but capped at 20 entries, 100 chars each. Forces curation over accumulation. Decisions supersede discoveries.

### Contract Lifecycle
Modules progress through: `draft` → `stable` → `frozen`. Frozen contracts can only be extended, never modified. This protects downstream consumers.

## Designed For

- **5-80 modules.** Small enough that one person can hold the full graph in their head. Large enough that unstructured projects fall apart. Most real software lives in this range.
- **1-4 developers.** Teams where every person touches multiple modules and nobody has time to write onboarding docs. The contracts *are* the docs.
- **AI agents as primary code consumers.** Contracts are structured for machine parsing first. Humans can read them fine — but the token budgets, the 6-file recovery pattern, and the explicit dependency graph exist because agents need them.

ANMA is not designed for monoliths, microservice meshes with hundreds of services, or projects where humans never use AI tooling. It's a deliberate fit for the middle ground where most teams actually operate.

## Requirements

- Python 3.8+
- PyYAML (`pip install pyyaml`)

No other dependencies. ANMA is a convention and a set of scripts, not a framework you install.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Documentation

- [Quickstart Guide](docs/QUICKSTART.md) — Set up in 5 minutes
- [Architecture Overview](docs/ARCHITECTURE.md) — How ANMA works
- [Contract Guide](docs/CONTRACT-GUIDE.md) — Writing effective contracts
