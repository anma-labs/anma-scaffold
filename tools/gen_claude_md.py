#!/usr/bin/env python3
"""ANMA CLAUDE.md Generator.

Generates a CLAUDE.md file for Claude Code from the project's
CONVENTIONS.yaml, MANIFEST.yaml, and GRAPH.yaml.

Usage:
    python3 gen_claude_md.py                  # Generate project-level CLAUDE.md
    python3 gen_claude_md.py --module auth-service  # Generate module-level CLAUDE.md

Zero external dependencies — uses the same YAML parser as lint_contracts.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules


def generate_project_claude_md(root):
    """Generate a project-level CLAUDE.md."""
    conv = parse_yaml_file(str(root / 'CONVENTIONS.yaml')) or {}
    manifest = parse_yaml_file(str(root / 'MANIFEST.yaml')) or {}
    graph = parse_yaml_file(str(root / 'GRAPH.yaml')) or {}

    modules = manifest.get('modules', {})
    if not isinstance(modules, dict):
        modules = {}

    lines = [
        "# CLAUDE.md — ANMA Project Instructions",
        "",
        "This project uses AI-Native Modular Architecture (ANMA).",
        "Every module is defined by structured YAML contracts, not code.",
        "Read contracts first. Never infer interfaces from source.",
        "",
        "## Architecture",
        "",
        f"Modules: {', '.join(sorted(modules.keys())) if modules else 'none yet'}",
        "",
        "## Context Loading Order",
        "",
        "On every task, read these files first (in order):",
        "",
        "1. `CONVENTIONS.yaml` — universal rules all agents follow",
        "2. `MANIFEST.yaml` — project modules and their status",
        "3. `GRAPH.yaml` — dependency graph between modules",
        "4. `modules/<module>/CONTRACT.yaml` — the interface spec",
        "5. `modules/<module>/STATE.yaml` — current work and blockers",
        "6. `modules/<module>/MEMORY.yaml` — accumulated knowledge",
        "",
        "Do NOT skip this loading order. Do NOT read source code before contracts.",
        "",
        "## Rules",
        "",
    ]

    # Naming conventions
    naming = conv.get('naming', {})
    if isinstance(naming, dict):
        lines.append("### Naming")
        lines.append("")
        for key, val in naming.items():
            lines.append(f"- {key}: `{val}`")
        lines.append("")

    # Communication rules
    comm = conv.get('communication', [])
    if isinstance(comm, list) and comm:
        lines.append("### Communication")
        lines.append("")
        for rule in comm:
            lines.append(f"- {rule}")
        lines.append("")

    # Memory rules
    mem = conv.get('memory', {})
    if isinstance(mem, dict):
        lines.append("### Memory Management")
        lines.append("")
        lines.append(f"- Max {mem.get('max_entries', 20)} entries in MEMORY.yaml")
        lines.append(f"- Each entry under {mem.get('max_content_chars', 100)} characters")
        rules = mem.get('rules', [])
        if isinstance(rules, list):
            for rule in rules:
                lines.append(f"- {rule}")
        lines.append("")

    # Error format
    ef = conv.get('error_format', {})
    if isinstance(ef, dict) and ef.get('shape'):
        lines.append("### Error Format")
        lines.append("")
        shape = ef['shape']
        if isinstance(shape, dict):
            lines.append(f"- All errors: `{{ code: STRING_CONSTANT, message: string, details: object | null }}`")
        lines.append("")

    # Contract lifecycle
    lifecycle = conv.get('contract_lifecycle', {})
    if isinstance(lifecycle, dict):
        statuses = lifecycle.get('statuses', [])
        if isinstance(statuses, list):
            lines.append("### Contract Status Values")
            lines.append("")
            lines.append(f"Valid: {', '.join(str(s) for s in statuses)}")
            lines.append("")

    lines.extend([
        "## Inter-Module Communication",
        "",
        "- Never edit another module's files directly",
        "- Use `BUS/requests/` to request changes from other modules",
        "- Publish contract changes to `BUS/deltas/`",
        "- Read BUS files relevant to your module on every task",
        "",
        "## Linting",
        "",
        "Run `python3 lint_contracts.py` before committing any change.",
        "Run `python3 lint_contracts.py --strict` for zero-warning builds.",
        "",
        "## Adding a Module",
        "",
        "Use the scaffolding script:",
        "```",
        "python3 new_module.py <name> --manager <manager> --consumes <deps>",
        "```",
        "",
        "## Key Principle",
        "",
        "Design for replacement, not continuity. Any fresh agent with zero history",
        "can take over any module by reading its 6 files. If knowledge exists only",
        "in your context, write it to MEMORY.yaml or CHANGELOG.yaml.",
    ])

    return '\n'.join(lines) + '\n'


def generate_module_claude_md(root, module_name):
    """Generate a module-level CLAUDE.md for a specific agent."""
    conv = parse_yaml_file(str(root / 'CONVENTIONS.yaml')) or {}
    manifest = parse_yaml_file(str(root / 'MANIFEST.yaml')) or {}
    graph = parse_yaml_file(str(root / 'GRAPH.yaml')) or {}
    try:
        module_paths = discover_modules(root)
    except ValueError:
        module_paths = {}
    mod_dir = module_paths.get(module_name, root / 'modules' / module_name)
    contract = parse_yaml_file(str(mod_dir / 'CONTRACT.yaml')) or {}

    # Get dependencies from graph
    graph_modules = graph.get('modules', {})
    mod_graph = {}
    if isinstance(graph_modules, dict):
        mod_graph = graph_modules.get(module_name, {})
    if not isinstance(mod_graph, dict):
        mod_graph = {}

    consumes = mod_graph.get('consumes', [])
    consumed_by = mod_graph.get('consumed_by', [])
    if not isinstance(consumes, list):
        consumes = []
    if not isinstance(consumed_by, list):
        consumed_by = []

    purpose = contract.get('purpose', 'TBD')
    status = contract.get('status', 'unknown')

    lines = [
        f"# CLAUDE.md — {module_name} Agent Instructions",
        "",
        f"You are the agent responsible for `{module_name}`.",
        f"Purpose: {purpose}",
        f"Status: {status}",
        "",
        "## Your Files",
        "",
        "Read these on every task (in order):",
        "",
        "1. `CONVENTIONS.yaml`",
        "2. `MANIFEST.yaml`",
        f"3. `GRAPH.yaml` (your edges: consumes {consumes}, consumed_by {consumed_by})",
        f"4. `modules/{module_name}/CONTRACT.yaml` — YOUR contract (source of truth)",
        f"5. `modules/{module_name}/STATE.yaml` — update after every task",
        f"6. `modules/{module_name}/MEMORY.yaml` — curate, don't just append",
        "",
        "## Your Interfaces",
        "",
    ]

    provides = contract.get('provides', [])
    if isinstance(provides, list) and provides:
        for iface in provides:
            if isinstance(iface, dict):
                iid = iface.get('id', '??')
                lines.append(f"- `{iid}`")
                invariants = iface.get('invariants', [])
                if isinstance(invariants, list):
                    for inv in invariants:
                        lines.append(f"  - invariant: {inv}")
    else:
        lines.append("- None yet (draft module)")

    lines.extend([
        "",
        "## Dependencies",
        "",
    ])

    if consumes:
        lines.append(f"You depend on: {', '.join(str(c) for c in consumes)}")
        lines.append("Read their CONTRACTs to understand their interfaces.")
    else:
        lines.append("You have no dependencies.")

    if consumed_by:
        lines.append(f"Consumed by: {', '.join(str(c) for c in consumed_by)}")
        lines.append("Your contract changes affect these modules — publish deltas.")
    else:
        lines.append("No other module depends on you yet.")

    lines.extend([
        "",
        "## Rules",
        "",
        "- Never read or modify another module's source code",
        "- Update STATE.yaml after every task",
        "- Write important decisions to MEMORY.yaml",
        "- Publish contract changes to BUS/deltas/",
        "- Request changes from other modules via BUS/requests/",
        "- Run `python3 lint_contracts.py` before declaring work complete",
        "",
        "## After Every Task",
        "",
        "1. Update `STATE.yaml` with current work and any blockers",
        "2. If you learned something important, add it to `MEMORY.yaml`",
        "3. If you changed the contract, publish a delta to `BUS/deltas/`",
        "4. Run the linter to verify consistency",
    ])

    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='ANMA CLAUDE.md Generator')
    parser.add_argument('--module', type=str, default=None,
                        help='Generate module-level CLAUDE.md for a specific module')
    parser.add_argument('--output', type=str, default=None,
                        help='Output path (default: CLAUDE.md or modules/<mod>/CLAUDE.md)')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing CLAUDE.md (required if file exists)')
    args = parser.parse_args()

    root = Path(args.path).resolve()

    if args.module:
        try:
            module_paths = discover_modules(root)
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        mod_dir = module_paths.get(args.module)
        if mod_dir is None:
            print(f"ERROR: Module '{args.module}' not found in modules/ or domains/")
            sys.exit(1)

        content = generate_module_claude_md(root, args.module)
        output = Path(args.output) if args.output else mod_dir / 'CLAUDE.md'
    else:
        content = generate_project_claude_md(root)
        output = Path(args.output) if args.output else root / 'CLAUDE.md'

    if output.exists() and not args.force:
        print(f"ERROR: {output} already exists.")
        print(f"  This file may contain custom content that would be lost.")
        print(f"  Use --force to overwrite, or --output to write elsewhere.")
        sys.exit(1)

    output.write_text(content)
    print(f"Generated {output}")
    print(f"  ({len(content)} chars, ~{len(content) // 4} tokens)")


if __name__ == '__main__':
    main()
