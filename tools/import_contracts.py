#!/usr/bin/env python3
"""ANMA Contract Importer.

Takes downloaded CONTRACT.yaml files and sets up the project:
- Creates module directories
- Copies contracts into place
- Runs sync_all.py to generate all supporting files
- Runs lint_contracts.py to verify

Usage:
    python3 tools/import_contracts.py user-auth-CONTRACT.yaml task-mgmt-CONTRACT.yaml
    python3 tools/import_contracts.py ~/Downloads/*-CONTRACT.yaml
    python3 tools/import_contracts.py contracts/*.yaml --force
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules

TOOLS_DIR = Path(__file__).parent


def extract_module_name(filepath):
    """Extract module name from filename or YAML content.

    Naming convention: <module-name>-CONTRACT.yaml
    Fallback: reads 'module:' field from YAML content.
    """
    name = filepath.stem  # e.g. "user-auth-CONTRACT"

    # Try naming convention first
    if name.upper().endswith("-CONTRACT"):
        return name[:-len("-CONTRACT")].lower()

    # Fallback: parse YAML
    data = parse_yaml_file(str(filepath))
    if data and isinstance(data, dict) and data.get("module"):
        return str(data["module"])

    return None


def import_contract(filepath, root, force=False, existing_paths=None, domain=None):
    """Import a single contract file into the project."""
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  ✗ {filepath} not found")
        return False

    module_name = extract_module_name(filepath)
    if not module_name:
        print(f"  ✗ {filepath.name}: can't determine module name")
        print(f"    Name files as <module-name>-CONTRACT.yaml")
        return False

    if existing_paths is None:
        try:
            existing_paths = discover_modules(root)
        except ValueError:
            existing_paths = {}

    if module_name in existing_paths:
        module_dir = existing_paths[module_name]
    elif domain:
        module_dir = root / "domains" / domain / module_name
    else:
        module_dir = root / "modules" / module_name
    target = module_dir / "CONTRACT.yaml"

    if target.exists() and not force:
        print(f"  ✗ {module_name}: already exists (use --force to overwrite)")
        return False

    module_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(filepath, target)
    print(f"  ✓ {module_name}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Import CONTRACT.yaml files into ANMA project")
    parser.add_argument("contracts", nargs="+",
                        help="Contract files (e.g. user-auth-CONTRACT.yaml)")
    parser.add_argument("--path", default=".",
                        help="Project root (default: current directory)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing module contracts")
    parser.add_argument("--skip-lint", action="store_true",
                        help="Skip linter after import")
    parser.add_argument("--domain", default=None,
                        help="Place new modules under domains/<domain>/ (default: modules/)")
    args = parser.parse_args()

    root = Path(args.path).resolve()

    # Verify this is an ANMA project
    if not (root / "CONVENTIONS.yaml").exists():
        print(f"Error: {root} is not an ANMA project (no CONVENTIONS.yaml)")
        print(f"  Run 'git clone <anma-scaffold> my-project' first")
        sys.exit(1)

    # Check if examples are still present
    example_modules = {"user-auth", "todo-api", "notifications"}
    try:
        existing_paths = discover_modules(root)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    if set(existing_paths) & example_modules:
        print("Warning: example modules still present.")
        print("  Run 'python3 tools/init_project.py' first to clear them.")
        print()

    # Import contracts
    print("Importing contracts:\n")
    imported = 0
    failed = 0
    for contract_path in args.contracts:
        path = Path(contract_path)
        if import_contract(path, root, args.force, existing_paths, args.domain):
            imported += 1
        else:
            failed += 1

    if imported == 0:
        print("\nNo contracts imported.")
        sys.exit(1)

    print(f"\n  {imported} imported, {failed} skipped")

    # Run sync_all.py
    print("\nSyncing project files...")
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "sync_all.py"), "--path", str(root)],
        capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  sync_all.py failed:\n{result.stdout[-500:]}")
        sys.exit(1)
    print("  ✓ sync complete")

    # Run linter
    if not args.skip_lint:
        print("\nRunning linter...")
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "lint_contracts.py"), str(root)],
            capture_output=True, text=True)

        # Show just the results section
        in_results = False
        for line in result.stdout.split("\n"):
            if "Results" in line:
                in_results = True
            if in_results:
                print(f"  {line}")

        if result.returncode != 0:
            print("\n  Fix the errors above, then re-run:")
            print(f"  python3 tools/lint_contracts.py")
        else:
            print("\n  ✓ Ready for implementation.")
            print(f"\n  Next: cd {root.name} && claude")
            print('  Then: "Read the <module> contract and implement all interfaces."')
    else:
        print("\n  Skipped linting. Run manually:")
        print(f"  python3 tools/lint_contracts.py")


if __name__ == "__main__":
    main()
