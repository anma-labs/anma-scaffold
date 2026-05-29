#!/usr/bin/env python3
"""ANMA Remove Module Script. Refuses removal if other modules consume this one.
Usage: python3 remove_module.py auth-service --confirm [--force]
"""
import argparse, os, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import load_all_contracts, parse_yaml_file
from discover import discover_modules

def find_project_root(start='.'):
    p = Path(start).resolve()
    if (p / 'MANIFEST.yaml').exists(): return p
    for parent in p.parents:
        if (parent / 'MANIFEST.yaml').exists(): return parent
    return p

def check_consumers(root, name, module_paths=None):
    contracts = load_all_contracts(root, module_paths=module_paths)
    consumers = []
    for mod_name, contract in contracts.items():
        if mod_name == name: continue
        consumes = contract.get('consumes', [])
        if isinstance(consumes, list):
            for dep in consumes:
                if isinstance(dep, dict) and dep.get('module') == name:
                    consumers.append(mod_name); break
    return consumers

def clean_bus(root, name):
    bus_dir = root / 'BUS'; removed = 0
    if bus_dir.is_dir():
        for sub in ['deltas', 'requests']:
            d = bus_dir / sub
            if d.is_dir():
                for f in d.iterdir():
                    if f.suffix not in ('.yaml', '.yml') or f.name == '.gitkeep':
                        continue
                    data = parse_yaml_file(str(f))
                    if not data or not isinstance(data, dict):
                        continue
                    refs = set()
                    for key in ['source', 'from', 'to']:
                        val = data.get(key)
                        if val and isinstance(val, str):
                            refs.add(val)
                    affected = data.get('impact', {})
                    if isinstance(affected, dict):
                        for consumer in affected.get('consumers_affected', []):
                            refs.add(str(consumer))
                    if name in refs:
                        f.unlink(); removed += 1
    return removed

def main():
    parser = argparse.ArgumentParser(description='ANMA Remove Module')
    parser.add_argument('name', help='Module name to remove')
    parser.add_argument('--confirm', action='store_true', help='Required to confirm removal')
    parser.add_argument('--force', action='store_true', help='Remove even if consumed by others')
    args = parser.parse_args()
    name = args.name
    root = find_project_root()
    try:
        module_paths = discover_modules(root)
    except ValueError as e:
        print(f"  ERROR: {e}"); sys.exit(1)
    mod_dir = module_paths.get(name)
    if mod_dir is None or not mod_dir.exists():
        print(f"  ERROR: Module '{name}' not found in modules/ or domains/"); sys.exit(1)
    if not args.confirm:
        print(f"  ERROR: Pass --confirm to actually remove '{name}'"); sys.exit(1)

    # Warn if module is claimed by someone else (don't block — --force overrides)
    try:
        from claims import get_claim
        claim = get_claim(root, name)
        if claim and claim.get('by') != os.environ.get('USER', 'unknown'):
            print(f"  ⚠ WARNING: '{name}' is claimed by {claim['by']} "
                  f"(branch: {claim.get('branch', '?')})")
            if not args.force:
                print("  Use --force to override.")
                sys.exit(1)
    except ImportError:
        pass

    consumers = check_consumers(root, name, module_paths=module_paths)
    if consumers and not args.force:
        print(f"\n  ERROR: Cannot remove '{name}' — consumed by: {', '.join(consumers)}")
        print(f"  Update these modules' contracts first, or use --force.\n"); sys.exit(1)
    if consumers and args.force:
        print(f"\n  WARNING: '{name}' is consumed by: {', '.join(consumers)}")
        print(f"  These modules will have broken consumes references.\n")

    print(f"\nANMA Remove Module\n  Removing: {name}\n")

    # All destructive operations first, summary printed after
    messages = []

    # Backup module before deletion
    backup_dir = root / '.anma-backup' / name
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.copytree(str(mod_dir), str(backup_dir))
    messages.append(f"  Backed up to .anma-backup/{name}/")

    # Clean up using yaml_editor
    from yaml_editor import manifest_remove_module, graph_remove_module, scope_remove_module
    
    manifest_remove_module(root, name)
    messages.append(f"  Removed '{name}' from MANIFEST")

    graph_remove_module(root, name)
    messages.append(f"  Removed '{name}' from GRAPH")

    # Clean SCOPE files for all managers
    managers_dir = root / 'managers'
    if managers_dir.is_dir():
        for mgr in managers_dir.iterdir():
            if mgr.is_dir() and (mgr / 'SCOPE.yaml').exists():
                if scope_remove_module(root, mgr.name, name):
                    messages.append(f"  Updated managers/{mgr.name}/SCOPE.yaml")

    bus_removed = clean_bus(root, name)
    if bus_removed:
        messages.append(f"  Removed {bus_removed} BUS file(s)")

    shutil.rmtree(mod_dir)
    try:
        rel = mod_dir.relative_to(root)
        messages.append(f"  Deleted {rel}/")
    except ValueError:
        messages.append(f"  Deleted {mod_dir}/")

    # Log activity
    try:
        from session_log import log_activity
        log_activity(root, f"removed module {name}", "remove_module.py")
    except Exception:
        pass

    # Print summary (SIGPIPE here can't prevent operations above)
    for msg in messages:
        print(msg)
    print(f"\n  Done. Run 'python3 gen_graph.py && python3 lint_contracts.py' to verify.\n")

if __name__ == '__main__': main()
