# ANMA — AI-Native Modular Architecture

**Structured contracts that let AI agents understand your codebase in ~350 tokens instead of 5,000-20,000.**

**No hallucinated interfaces. No undeclared dependencies. No silent integration bugs.**

Built for Claude Code. Contracts are plain YAML — readable by any AI tool, but the full design-to-implementation workflow is optimized for Claude Code.

---

## The Problem

AI coding agents burn most of their context window just *understanding* your codebase before writing a single line of code:

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

## The Solution

Replace all of that with one contract:

```yaml
module: user-auth
version: 1
status: draft

provides:
  - id: register
    input: { email: string, password: string, display_name: string }
    output: { user_id: uuid, token: string }
    errors: [EMAIL_TAKEN, WEAK_PASSWORD, INVALID_EMAIL]
    invariants:
      - "auto-sends verification email"
      - "password must be at least 8 characters"

  - id: login
    input: { email: string, password: string }
    output: { user_id: uuid, token: string }
    errors: [INVALID_CREDENTIALS, ACCOUNT_LOCKED]
    invariants:
      - "same error for wrong password and non-existent email"

consumes: []
```

```
Agent reads modules/user-auth/CONTRACT.yaml   → 350 tokens
                                    Total: 350 tokens (complete understanding)
```

**~10x reduction.** No ambiguity. No guessing. No wasted tokens.

Tell an agent "implement all interfaces in this contract" and it knows every input, output, error, and behavioral guarantee without reading a single line of source code.

## Getting Started

**Path 1** if you want Claude to handle everything in one conversation.
**Path 2** if you're a developer who wants control over each step.

### Path 1: Conversational (recommended)

Open [Claude](https://claude.ai) (Opus 4.6+) and start a conversation.

If you have research files, design docs, wireframes, or reference material —
upload them now. Claude uses them to write better contracts.

> "Clone https://github.com/nxy/anma-scaffold and read the CLAUDE.md and
> CONVENTIONS.yaml. Let me know when you're ready to build a project with me."

Claude clones the repo, reads the architecture rules, and becomes your contract
architect. Now describe what you want to build:

> "I want to build a URL shortener. Users create API keys, shorten URLs with
> custom slugs, click tracking with analytics, and rate limiting."

Claude designs the module contracts — identifying boundaries (auth, links,
analytics, rate-limiter), defining interfaces with inputs, outputs, errors,
and invariants. It asks clarifying questions and iterates with you until the
design is right.

When the contracts look good:

> "Set up the project and implement all modules."

Claude handles the rest — clears examples, imports contracts, validates them
against the linter, and implements each module. If it discovers contract gaps
during implementation (an undeclared dependency, a missing error code), it
flags them, revises the contracts, and updates the code.

When implementation is done:

> "Create app.py that wires all modules together."

Claude reads the contracts, knows every interface, and builds the application.

### Path 2: Terminal (developer workflow)

For developers who want hands-on control at each step.

```bash
git clone https://github.com/nxy/anma-scaffold my-project
cd my-project
pip install pyyaml
```

**1. Design contracts.** Upload `CLAUDE.md` and `CONVENTIONS.yaml` to
[Claude](https://claude.ai) and describe what you're building. Claude drafts
contracts following the ANMA format and provides them as downloadable files.

**2. Import and validate.**

```bash
python3 tools/init_project.py                                 # clear examples
python3 tools/import_contracts.py ~/Downloads/*-CONTRACT.yaml  # import, sync, lint
```

One command creates module directories, copies contracts, generates all
supporting files, and runs the linter. If there are errors, fix the contracts
and re-import. Target 0 errors before moving to implementation.

**3. Implement with Claude Code.**

```bash
claude
> Read all module contracts and implement them.
```

Claude Code reads CLAUDE.md, knows the architecture, and implements each module.
It handles dependency ordering, updates STATE.yaml with progress, and captures
decisions in MEMORY.yaml.

**4. Discover and revise.**

If implementation surfaces contract gaps, revise and re-import:

```bash
python3 tools/import_contracts.py revised-CONTRACT.yaml --force
```

Contracts catching integration bugs is ANMA working as designed.

**5. Wire and ship.**

```bash
> Create app.py that wires all modules together.
```

Both paths produce the same result: a project with explicit contracts,
validated dependencies, and code that matches the spec.

## Real Numbers

In a 4-module demo (URL shortener), contracts caught 5 integration bugs during implementation — undeclared dependencies, missing error codes, absent BUS events — that would have been silent failures without ANMA.

At scale, a production test scaffolded 18 modules with 104 interfaces in a single Claude Code session:

| Metric | Value |
|--------|-------|
| Modules scaffolded | 18 |
| Interfaces implemented | 104 |
| Tests generated | 239 |
| Input tokens per session | ~14,600 |
| Total API cost | $31 |
| Time | 91 minutes |

This repo ships with 3 example modules (14 interfaces, ~350 tokens each) so you can explore the format immediately.

## How It Works

Each module is a directory with 6 small files — small enough for an agent to read in full. An agent recovering a module reads 3 of them (CONTRACT + STATE + MEMORY, ~400 tokens total). The others are generated by the tooling.

```
your-project/
  CONVENTIONS.yaml      # Universal rules (naming, error format, token budgets)
  MANIFEST.yaml         # Module registry with status and ownership
  GRAPH.yaml            # Auto-generated dependency graph
  CLAUDE.md             # Agent instructions (auto-read by Claude Code)
  modules/
    user-auth/
      CONTRACT.yaml     # What this module provides and consumes
      STATE.yaml        # Current work status and blockers
      MEMORY.yaml       # Accumulated knowledge (max 20 entries, 100 chars each)
      CHANGELOG.yaml    # Version history
      TESTS.yaml        # Contract-derived test cases
      ASSUMPTIONS.yaml  # Implementation details (separate from contract)
  BUS/                  # Async inter-module communication
  tools/                # 26 scripts for linting, scaffolding, and analysis
```

Contracts prescribe what code must do. Assumptions describe how it's built today. The separation means you can swap implementations without breaking the contract.

Modules progress through a lifecycle: `draft` → `stable` → `frozen`. Frozen contracts can only be extended, never modified — protecting every module that depends on them.

## Tools

```bash
python3 tools/anma.py init                       # Clear examples, start fresh
python3 tools/anma.py import contracts/*.yaml    # Import contract files
python3 tools/anma.py lint                       # Validate (23 checks + 7 principles)
python3 tools/anma.py lint --strict              # Zero-warning builds
python3 tools/anma.py module add billing         # Scaffold a new module
python3 tools/anma.py graph                      # Regenerate dependency graph
python3 tools/anma.py dashboard                  # Project health overview
python3 tools/anma.py impact user-auth           # What breaks if auth changes?
```

Run `python3 tools/anma.py` for the full list. All tools also work standalone (e.g. `python3 tools/lint_contracts.py`).

## FAQ

**How is this different from OpenAPI / Swagger?**
OpenAPI describes HTTP endpoints. ANMA describes module boundaries — interfaces, invariants, errors, dependencies, state, and institutional memory. You can use both: OpenAPI for your public API, ANMA for internal architecture.

**Do I have to use Claude?**
The full workflow is built for Claude. The contract format is plain YAML, so other LLMs can read it, but only Claude has been tested end-to-end.

**Isn't this just writing documentation?**
Documentation describes what code does. Contracts prescribe what code must do — with machine-parseable inputs, outputs, errors, and invariants that a linter enforces. Documentation drifts. Contracts break the build.

**What size projects is this for?**
5-80 modules, 1-4 developers. Most real software lives in this range.

## License

[BSL 1.1](LICENSE) — free to use for any project. You can't use it to build a competing scaffold product. Converts to Apache 2.0 on May 23, 2029.

## Requirements

- Python 3.8+
- PyYAML (`pip install pyyaml`)

No other dependencies. ANMA is a convention and a set of scripts, not a framework you install.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md) — The 7 design principles
- [Contract Guide](docs/CONTRACT-GUIDE.md) — Writing effective contracts
- [Quickstart Guide](docs/QUICKSTART.md) — Detailed setup walkthrough
