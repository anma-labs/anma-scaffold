#!/usr/bin/env python3
"""ANMA New Module Scaffolding Script.

Creates a complete module directory with all required files,
updates MANIFEST.yaml and GRAPH.yaml, and runs the linter to verify.

Usage:
    python3 new_module.py payment-service
    python3 new_module.py payment-service --manager backend-manager --consumes user-store
    python3 new_module.py cache-layer --type infrastructure --purpose "Shared cache"

Zero external dependencies — uses the same YAML parser as lint_contracts.py.
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import the YAML parser from lint_contracts
sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules


# ---------------------------------------------------------------------------
# YAML writing helpers (minimal, no external deps)
# ---------------------------------------------------------------------------

def timestamp_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def write_contract(path, name, mod_type, purpose, consumes):
    lines = [
        f"module: {name}",
        "version: 1",
        "status: draft",
        f"type: {mod_type}",
        "",
        f'purpose: "{purpose}"',
        "",
        "provides: []",
        "# Example:",
        "#  - id: my_interface",
        "#    input: { key: string }",
        "#    output: { value: string }",
        "#    errors: [NOT_FOUND]",
        '#    invariants: ["returns NOT_FOUND for missing keys"]',
        "",
    ]

    if consumes:
        lines.append("consumes:")
        for dep in consumes:
            lines.append(f"  - module: {dep}")
            lines.append(f"    interface: TBD")
            lines.append(f"    required: true")
    else:
        lines.append("consumes: []")

    lines.extend([
        "",
        "constraints:",
        "  language: TBD",
        "  runtime: TBD",
        "",
        "contract_rules:",
        "  adding_interface: allowed",
        "  modifying_interface: notify",
        "  removing_interface: breaking",
    ])

    path.write_text('\n'.join(lines) + '\n')


def write_state(path, name):
    path.write_text('\n'.join([
        f"module: {name}",
        "status: green",
        f"updated: {timestamp_now()}",
        "",
        "current_work: \"Initial scaffolding\"",
        "blockers: []",
        "health_notes: \"Freshly created\"",
    ]) + '\n')


def write_memory(path, name):
    path.write_text('\n'.join([
        f"module: {name}",
        "entries: []",
    ]) + '\n')


def write_changelog(path, name):
    path.write_text('\n'.join([
        "# Structured diffs against CONTRACT.yaml.",
        f"module: {name}",
        "changes: []",
    ]) + '\n')


def write_tests(path, name):
    path.write_text('\n'.join([
        "# Black-box contract tests.",
        f"module: {name}",
        "tests: []",
        "# REQUIRED FIELDS: interface, case, input, expect",
        "# Tests are a FLAT list (not nested by interface).",
        "#",
        "# Example — happy path:",
        "#  - interface: get_item",
        "#    case: valid_id",
        "#    input: { item_id: \"abc123\" }",
        "#    expect: { has_keys: [item_id, name, status] }",
        "#",
        "# Example — error case:",
        "#  - interface: get_item",
        "#    case: not_found",
        "#    input: { item_id: \"nonexistent\" }",
        "#    expect: { error: ITEM_NOT_FOUND }",
        "#",
        "# Example — with precondition:",
        "#  - interface: login",
        "#    case: account_locked",
        "#    input: { email: \"user@test.com\", password: \"wrong\" }",
        "#    precondition: \"5 failed attempts within 15 min\"",
        "#    expect: { error: ACCOUNT_LOCKED }",
    ]) + '\n')


def write_assumptions(path, name):
    path.write_text('\n'.join([
        "# Implementation assumptions not captured in CONTRACT.",
        f"module: {name}",
        "assumptions: []",
        "# Example:",
        "#  - id: A001",
        "#    category: data",
        '#    content: "database supports transactions"',
    ]) + '\n')


# ---------------------------------------------------------------------------
# MANIFEST and GRAPH updaters
# ---------------------------------------------------------------------------

def update_manifest(root, name, manager, domain=None):
    """Append new module to MANIFEST.yaml using yaml_editor."""
    from yaml_editor import manifest_add_module, scope_add_module

    manifest_path = root / 'MANIFEST.yaml'
    if not manifest_path.exists():
        print(f"  WARNING: {manifest_path} not found, skipping")
        return

    ok, err = manifest_add_module(root, name, manager=manager, domain=domain)
    if not ok:
        print(f"  {err}")
        return
    print(f"  Updated MANIFEST.yaml")

    if manager:
        if scope_add_module(root, manager, name):
            print(f"  Updated managers/{manager}/SCOPE.yaml")


def update_graph(root, name, consumes):
    """Append new module to GRAPH.yaml and update consumed_by using yaml_editor."""
    from yaml_editor import graph_add_module, read_graph

    graph_path = root / 'GRAPH.yaml'
    if not graph_path.exists():
        print(f"  WARNING: {graph_path} not found, skipping")
        return

    data = read_graph(root)
    modules = data.get('modules', {})
    if isinstance(modules, dict) and name in modules:
        print(f"  GRAPH.yaml already contains '{name}', skipping")
        return

    graph_add_module(root, name, consumes)
    print(f"  Updated GRAPH.yaml")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='ANMA New Module Scaffolding Script')
    parser.add_argument('name', help='Module name (kebab-case)')
    parser.add_argument('--manager', type=str, default=None,
                        help='Owning manager (e.g., backend-manager)')
    parser.add_argument('--consumes', type=str, default=None,
                        help='Comma-separated list of modules this depends on')
    parser.add_argument('--type', type=str, default='regular',
                        choices=['regular', 'infrastructure'],
                        help='Module type (default: regular)')
    parser.add_argument('--purpose', type=str,
                        default='TBD — describe this module',
                        help='One-line purpose description')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    parser.add_argument('--domain', type=str, default=None,
                        help='Place module under domains/<domain>/ (default: modules/)')
    parser.add_argument('--lint', action='store_true',
                        help='Run linter after scaffolding')
    args = parser.parse_args()

    root = Path(args.path).resolve()
    name = args.name
    consumes = [c.strip() for c in args.consumes.split(',') if c.strip()] if args.consumes else []

    # Validate name is kebab-case
    if not re.match(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$', name):
        print(f"ERROR: '{name}' is not valid kebab-case")
        sys.exit(1)

    # Discover existing modules across flat and domain layouts
    try:
        existing_paths = discover_modules(root)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Check module doesn't already exist
    if name in existing_paths:
        print(f"ERROR: Module '{name}' already exists at {existing_paths[name]}")
        sys.exit(1)
    if args.domain:
        mod_dir = root / 'domains' / args.domain / name
        rel_label = f"domains/{args.domain}/{name}"
    else:
        mod_dir = root / 'modules' / name
        rel_label = f"modules/{name}"
    if mod_dir.exists():
        print(f"ERROR: Module directory already exists: {mod_dir}")
        sys.exit(1)

    # Validate consumed modules exist
    for dep in consumes:
        if dep not in existing_paths:
            print(f"ERROR: Consumed module '{dep}' does not exist in modules/ or domains/")
            sys.exit(1)

    print(f"\nANMA New Module Scaffolding")
    print(f"  Module:   {name}")
    print(f"  Type:     {args.type}")
    print(f"  Manager:  {args.manager or '(none)'}")
    print(f"  Domain:   {args.domain or '(none)'}")
    print(f"  Consumes: {consumes or '(none)'}")
    print()

    # Create module directory
    mod_dir.mkdir(parents=True)
    (mod_dir / 'src').mkdir()
    (mod_dir / 'tests').mkdir()
    (mod_dir / 'src' / '.gitkeep').write_text('')
    (mod_dir / 'tests' / '.gitkeep').write_text('')

    # Create all 6 YAML files
    write_contract(mod_dir / 'CONTRACT.yaml', name, args.type, args.purpose, consumes)
    write_state(mod_dir / 'STATE.yaml', name)
    write_memory(mod_dir / 'MEMORY.yaml', name)
    write_changelog(mod_dir / 'CHANGELOG.yaml', name)
    write_tests(mod_dir / 'TESTS.yaml', name)
    write_assumptions(mod_dir / 'ASSUMPTIONS.yaml', name)

    print(f"  Created {rel_label}/ with 8 files")

    # Update MANIFEST and GRAPH
    update_manifest(root, name, args.manager, args.domain)
    update_graph(root, name, consumes)

    print(f"\n  Done. Run 'python3 lint_contracts.py' to verify.")

    if args.lint:
        print()
        os.system(f'cd {root} && python3 lint_contracts.py')


if __name__ == '__main__':
    main()
