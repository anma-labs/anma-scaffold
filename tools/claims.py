#!/usr/bin/env python3
"""ANMA Module Claims — lightweight coordination for multi-agent work."""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file


CLAIMS_DIR = '.anma'
CLAIMS_FILE = '.anma/claims.yaml'


def _get_git_branch():
    try:
        import subprocess
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'


def _load_claims(root):
    path = Path(root) / CLAIMS_FILE
    if not path.exists():
        return {}
    data = parse_yaml_file(str(path))
    if not data or not isinstance(data, dict):
        return {}
    return data.get('claims', {}) or {}


def _save_claims(root, claims):
    root = Path(root)
    path = root / CLAIMS_FILE
    (root / CLAIMS_DIR).mkdir(exist_ok=True)
    import yaml
    header = '# Who is working on what. Updated via: anma claim / anma release\n'
    body = yaml.safe_dump({'claims': claims or {}}, default_flow_style=False, sort_keys=True)
    path.write_text(header + body)


def add_claim(root, module, by=None, branch=None):
    """Add a claim. Returns (success, message)."""
    claims = _load_claims(root)
    if by is None:
        by = os.environ.get('USER', 'unknown')
    if branch is None:
        branch = _get_git_branch()
    existing = claims.get(module)
    if existing and existing.get('by') != by:
        return False, (f"'{module}' already claimed by {existing['by']} "
                       f"(branch: {existing.get('branch', '?')})")
    claims[module] = {
        'by': by,
        'branch': branch,
        'since': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    _save_claims(root, claims)
    return True, f"Claimed '{module}' for {by}"


def get_claim(root, module):
    """Get claim info for a module. Returns dict or None."""
    claims = _load_claims(root)
    return claims.get(module)


def release_claim(root, module):
    """Release a claim. Returns (success, message)."""
    claims = _load_claims(root)
    if module not in claims:
        return True, f"'{module}' was not claimed"
    del claims[module]
    _save_claims(root, claims)
    return True, f"Released '{module}'"


def print_status(root):
    """Print claims table."""
    claims = _load_claims(root)
    if not claims:
        print("No active claims.")
        return
    print(f"\n{'Module':<25} {'By':<15} {'Branch':<25} {'Since'}")
    print("─" * 80)
    for mod, info in sorted(claims.items()):
        print(f"  {mod:<23} {info.get('by','?'):<15} "
              f"{info.get('branch','?'):<25} {info.get('since','?')}")
    print()


def main():
    parser = argparse.ArgumentParser(description='ANMA Module Claims')
    parser.add_argument('--path', default='.', help='Project root')
    sub = parser.add_subparsers(dest='command')

    # claim
    p_claim = sub.add_parser('claim', help='Claim modules')
    p_claim.add_argument('modules', nargs='+', help='Module names to claim')
    p_claim.add_argument('--by', default=None, help='Who is claiming')
    p_claim.add_argument('--branch', default=None, help='Git branch')

    # release
    p_release = sub.add_parser('release', help='Release modules')
    p_release.add_argument('modules', nargs='+', help='Module names to release')

    # status
    sub.add_parser('status', help='Show claims')

    # clear
    sub.add_parser('clear', help='Clear all claims')

    args = parser.parse_args()
    root = Path(args.path).resolve()

    if args.command == 'claim':
        any_failed = False
        claims = _load_claims(root)
        by = args.by if args.by is not None else os.environ.get('USER', 'unknown')
        branch = args.branch if args.branch is not None else _get_git_branch()
        dirty = False
        for mod in args.modules:
            existing = claims.get(mod)
            if existing and existing.get('by') != by:
                msg = (f"'{mod}' already claimed by {existing['by']} "
                       f"(branch: {existing.get('branch', '?')})")
                print(f"  {'✗'} {msg}")
                any_failed = True
            else:
                claims[mod] = {
                    'by': by,
                    'branch': branch,
                    'since': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                }
                dirty = True
                print(f"  {'✓'} Claimed '{mod}' for {by}")
        if dirty:
            _save_claims(root, claims)
        if any_failed:
            sys.exit(1)
    elif args.command == 'release':
        claims = _load_claims(root)
        dirty = False
        for mod in args.modules:
            if mod not in claims:
                print(f"  {'✓'} '{mod}' was not claimed")
            else:
                del claims[mod]
                dirty = True
                print(f"  {'✓'} Released '{mod}'")
        if dirty:
            _save_claims(root, claims)
    elif args.command == 'status':
        print_status(root)
    elif args.command == 'clear':
        _save_claims(root, {})
        print("  ✓ All claims cleared.")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
