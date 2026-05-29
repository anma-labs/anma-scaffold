#!/usr/bin/env python3
"""ANMA Project Rename Script.
Usage: python3 rename_project.py my-new-project
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
    parser = argparse.ArgumentParser(description='ANMA Project Rename')
    parser.add_argument('name', help='New project name (kebab-case)')
    args = parser.parse_args()
    new_name = args.name
    if not re.match(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$', new_name):
        print(f"  ERROR: Project name must be kebab-case (got '{new_name}')"); sys.exit(1)
    root = find_project_root()

    manifest = root / 'MANIFEST.yaml'
    content = manifest.read_text()
    match = re.search(r'^project:\s*(\S+)', content, re.MULTILINE)
    old_name = match.group(1) if match else None
    if not old_name:
        print("  ERROR: Could not find project name in MANIFEST.yaml"); sys.exit(1)
    if old_name == new_name:
        print(f"  Project is already named '{new_name}'"); sys.exit(0)

    print(f"\nANMA Project Rename\n  From: {old_name}\n  To:   {new_name}\n")
    files = [root / 'MANIFEST.yaml', root / 'orchestrator' / 'PLAN.yaml', root / 'README.md']
    pattern = re.compile(r'(?<![a-z0-9-])' + re.escape(old_name) + r'(?![a-z0-9-])')
    updated = 0
    for fp in files:
        if fp.exists():
            c = fp.read_text()
            nc = pattern.sub(new_name, c)
            if nc != c: fp.write_text(nc); print(f"  Updated {fp.relative_to(root)}"); updated += 1
    print(f"\n  Renamed in {updated} file(s). Run 'python3 gen_claude_md.py' to regenerate CLAUDE.md.\n")

if __name__ == '__main__': main()
