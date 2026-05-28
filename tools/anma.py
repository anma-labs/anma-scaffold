#!/usr/bin/env python3
"""ANMA CLI — unified entry point for all ANMA scaffold tools.

Usage:
    anma init                                  # Clear examples, start fresh
    anma import <files...> [--force]           # Import contract files
    anma lint [--module X] [--strict]
    anma module add <name> [--manager M] [--consumes X,Y] [--purpose P]
    anma module remove <name> --confirm [--force]
    anma manager add <name> [--owns X,Y]
    anma graph [--check] [--dry-run]
    anma graph viz
    anma dashboard [--json]
    anma rename <new-name>
    anma contract <name> --purpose P [--consumes X] [--output F]
    anma spec [--module X] [--output F]
    anma claude [--module X]
    anma verify <module> [--plan] [--endpoint URL]
    anma compat [--json]
    anma migrate <module> <version>
    anma bus archive [--dry-run] [--max-age N]
    anma test                    # Run unit tests
    anma smoke                   # Run smoke tests

All subcommands pass remaining arguments directly to the underlying script.
Individual scripts (e.g., python3 lint_contracts.py) still work standalone.
"""

import sys
from pathlib import Path

# Ensure the scaffold directory is on the import path
sys.path.insert(0, str(Path(__file__).parent))

COMMANDS = {
    'lint':      ('lint_contracts', 'Lint contracts (22 checks)'),
    'dashboard': ('dashboard',      'Project health dashboard'),
    'compat':    ('compat_matrix',  'Compatibility matrix'),
    'rename':    ('rename_project', 'Rename the project'),
    'claude':    ('gen_claude_md',  'Generate CLAUDE.md'),
    'spec':      ('gen_product_spec', 'Generate product spec'),
    'gentests':  ('gen_tests',        'Generate test stubs from contract'),
    'impact':    ('impact',           'Dependency impact analysis'),
    'diff':      ('contract_diff',   'Contract diff + BUS delta generator'),
    'test':      ('test_linter',    'Run unit tests'),
    'smoke':     ('smoke_test',     'Run smoke tests'),
    'init':      ('init_project',   'Clear examples for a fresh project'),
    'import':    ('import_contracts', 'Import contract files into project'),
    'sync':      ('sync_all',         'Sync project files (GRAPH, MANIFEST, TESTS)'),
}

# Subcommands with sub-subcommands
GROUP_COMMANDS = {
    'module': {
        'add':    ('new_module',    'Scaffold a new module'),
        'remove': ('remove_module', 'Remove a module'),
    },
    'manager': {
        'add':    ('new_manager',   'Scaffold a new manager'),
    },
    'graph': {
        '_default': ('gen_graph',   'Generate/check dependency graph'),
        'viz':      ('graph_viz',   'Visualize dependency graph'),
    },
    'contract': {
        '_default': ('gen_contract', 'Generate contract template'),
    },
    'verify': {
        '_default': ('verify_contract', 'Verify contract implementation'),
    },
    'migrate': {
        '_default': ('plan_migration', 'Plan a contract migration'),
    },
    'bus': {
        'archive': ('bus_archive',  'Archive old BUS entries'),
    },
}


def print_help():
    print("ANMA CLI — unified entry point for all scaffold tools.\n")
    print("Usage: anma <command> [args...]\n")
    print("Commands:")
    for cmd, (_, desc) in sorted(COMMANDS.items()):
        print(f"  {cmd:14s} {desc}")
    print()
    for group, subs in sorted(GROUP_COMMANDS.items()):
        for sub, (_, desc) in sorted(subs.items()):
            if sub == '_default':
                print(f"  {group:14s} {desc}")
            else:
                label = f"{group} {sub}"
                print(f"  {label:14s} {desc}")
    print("  claim          Claim modules for exclusive work")
    print("  release        Release claimed modules")
    print("  claims         Show current module claims")
    print()
    print("Run 'anma <command> --help' for command-specific options.")
    print("All commands also work standalone: python3 lint_contracts.py\n")


def run_module(module_name, args):
    """Import and run a module's main() function with patched sys.argv."""
    sys.argv = [module_name + '.py'] + args

    # Special handling for unittest runner (no main() function)
    if module_name == 'test_linter':
        import unittest
        unittest.main(module='test_linter', argv=[module_name + '.py'] + args, exit=True)
        return

    mod = __import__(module_name)
    try:
        mod.main()
    except SystemExit as e:
        sys.exit(e.code)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print_help()
        sys.exit(0)

    command = sys.argv[1]
    rest = sys.argv[2:]

    # Claims — needs special handling to pass the action verb
    if command in ('claim', 'release', 'claims'):
        action_map = {'claim': 'claim', 'release': 'release', 'claims': 'status'}
        run_module('claims', [action_map[command]] + rest)
        return

    # Simple commands
    if command in COMMANDS:
        module_name = COMMANDS[command][0]
        run_module(module_name, rest)
        return

    # Group commands (module add, graph viz, etc.)
    if command in GROUP_COMMANDS:
        group = GROUP_COMMANDS[command]

        if not rest or rest[0].startswith('-'):
            # No subcommand — use _default if available
            if '_default' in group:
                module_name = group['_default'][0]
                run_module(module_name, rest)
                return
            else:
                print(f"anma {command}: requires a subcommand: {', '.join(k for k in group if k != '_default')}")
                sys.exit(1)

        subcmd = rest[0]
        if subcmd in group:
            module_name = group[subcmd][0]
            run_module(module_name, rest[1:])
            return
        elif subcmd in ('-h', '--help'):
            print(f"anma {command} subcommands:")
            for sub, (_, desc) in sorted(group.items()):
                if sub != '_default':
                    print(f"  {sub:12s} {desc}")
            if '_default' in group:
                print(f"\n  (no subcommand) → {group['_default'][1]}")
            sys.exit(0)
        elif '_default' in group:
            # Unknown subcommand but has default — pass everything to default
            module_name = group['_default'][0]
            run_module(module_name, rest)
            return
        else:
            print(f"anma {command}: unknown subcommand '{subcmd}'")
            print(f"  Available: {', '.join(k for k in group if k != '_default')}")
            sys.exit(1)

    print(f"anma: unknown command '{command}'")
    print("Run 'anma help' for available commands.")
    sys.exit(1)


if __name__ == '__main__':
    main()
