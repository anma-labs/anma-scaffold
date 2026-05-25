# ANMA Quickstart

Get a working ANMA project in 5 minutes.

## Prerequisites

- Python 3.8+
- `pip install pyyaml`

## Step 1: Clone

```bash
git clone https://github.com/nxy/anma-scaffold my-project
cd my-project
```

## Step 2: Verify the scaffold

```bash
python3 tools/lint_contracts.py
```

Three example modules checked, 0 errors. Browse `modules/user-auth/CONTRACT.yaml` to see a full contract.

## Step 3: Design your contracts

Upload `CLAUDE.md` and `CONVENTIONS.yaml` to any AI chat (Claude, ChatGPT, Gemini) and describe what you're building:

> "I uploaded my ANMA scaffold files. I want to build a project management tool.
> Teams can create projects, add tasks with deadlines, assign them to people,
> and get notified when things change."

The AI drafts contracts, asks clarifying questions, and iterates with you. When ready:

> "Give me all CONTRACT.yaml files so I can save them and run the linter."

Save each file as `<module-name>-CONTRACT.yaml` (e.g. `task-mgmt-CONTRACT.yaml`).

## Step 4: Import and validate

```bash
python3 tools/init_project.py                                 # clear example modules
python3 tools/import_contracts.py ~/Downloads/*-CONTRACT.yaml  # import, sync, lint
```

`import_contracts.py` creates module directories, copies contracts, generates supporting files (STATE, MEMORY, TESTS, GRAPH, MANIFEST), and runs the linter. One command.

## Step 5: Implement with Claude Code

```bash
claude
> Read the task-mgmt module CONTRACT.yaml and implement all interfaces.
```

Claude Code reads the contract (~350 tokens), sees every interface, input, output, error, and invariant, and implements the module.

Repeat for each module. The contracts are the spec.

## What's Next

- [Architecture Overview](ARCHITECTURE.md) — how ANMA works and the 7 design principles
- [Contract Guide](CONTRACT-GUIDE.md) — best practices for writing contracts
- [CONTRIBUTING.md](../CONTRIBUTING.md) — how to contribute
