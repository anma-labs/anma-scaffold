#!/usr/bin/env python3
"""ANMA New Manager Scaffolding Script.
Usage: python3 new_manager.py core-manager --owns auth,user-profiles
"""
import argparse, re, sys
from pathlib import Path

def find_project_root(start='.'):
    p = Path(start).resolve()
    if (p / 'MANIFEST.yaml').exists(): return p
    for parent in p.parents:
        if (parent / 'MANIFEST.yaml').exists(): return parent
    return p

def main():
    parser = argparse.ArgumentParser(description='ANMA New Manager Scaffolding')
    parser.add_argument('name', help='Manager name (kebab-case)')
    parser.add_argument('--owns', type=str, default=None,
                        help='Comma-separated list of modules this manager owns')
    args = parser.parse_args()
    name = args.name
    if not re.match(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$', name):
        print(f"  ERROR: Manager name must be kebab-case (got '{name}')"); sys.exit(1)
    owns = [m.strip() for m in args.owns.split(',') if m.strip()] if args.owns else []
    root = find_project_root()
    mgr_dir = root / 'managers' / name
    if mgr_dir.exists():
        print(f"  ERROR: Manager directory already exists: {mgr_dir}"); sys.exit(1)

    print(f"\nANMA New Manager Scaffolding")
    print(f"  Manager: {name}")
    print(f"  Owns:    {owns if owns else '(none)'}\n")

    # Create directory structure
    mgr_dir.mkdir(parents=True)
    owns_str = ', '.join(owns) if owns else ''
    (mgr_dir / 'SCOPE.yaml').write_text(
        f"manager: {name}\nowns: [{owns_str}]\n\n"
        "responsibilities:\n  - Resolve cross-module requests within owned group\n"
        "  - Approve breaking contract changes\n"
        "  - Escalate to orchestrator if change affects modules outside scope\n\n"
        f"reads:\n  - GRAPH.yaml\n  - BUS/deltas/*\n  - BUS/requests/*\n\n"
        f"writes:\n  - managers/{name}/STRATEGY.yaml\n  - managers/{name}/INBOX.yaml\n"
        "  - BUS/requests/* (resolve/reject)\n\n"
        "escalation_triggers:\n  - Any module status RED for > 2 hours\n"
        "  - Breaking contract change proposed\n  - Circular dependency detected\n")
    (mgr_dir / 'STRATEGY.yaml').write_text(f"manager: {name}\ncurrent_phase: scaffolding\npriorities: []\nrisks: []\n")
    (mgr_dir / 'INBOX.yaml').write_text(f"manager: {name}\nitems: []\n")
    print(f"  Created managers/{name}/ with SCOPE, STRATEGY, INBOX")

    # Update MANIFEST using yaml_editor
    from yaml_editor import manifest_add_manager
    ok, err = manifest_add_manager(root, name, owns)
    if ok:
        print(f"  Updated MANIFEST.yaml")
    else:
        import shutil
        shutil.rmtree(mgr_dir)
        print(f"  ERROR: {err}")
        sys.exit(1)

    # Log activity
    try:
        from session_log import log_activity
        log_activity(root, f"created manager {name}", "new_manager.py")
    except Exception:
        pass

    print(f"\n  Done. Run 'python3 lint_contracts.py' to verify.\n")

if __name__ == '__main__': main()
