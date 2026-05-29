#!/usr/bin/env python3
"""ANMA BUS Lifecycle Manager.

Archives resolved/rejected requests and old deltas to BUS/archive/.
Keeps the active BUS directories clean and token-efficient.

Usage:
    python3 bus_archive.py                    # Archive resolved requests + deltas >30 days
    python3 bus_archive.py --max-age 7        # Archive deltas older than 7 days
    python3 bus_archive.py --dry-run           # Preview without moving files

Zero external dependencies.
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file


def parse_iso_date(date_str):
    """Parse ISO 8601 date string to datetime. Returns None on failure."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        # Handle common ISO formats
        clean = date_str.strip().replace('Z', '+00:00')
        # Python 3.7+ fromisoformat
        return datetime.fromisoformat(clean)
    except (ValueError, AttributeError):
        return None


def archive_requests(root, dry_run=False):
    """Archive resolved/rejected requests."""
    requests_dir = root / 'BUS' / 'requests'
    archive_dir = root / 'BUS' / 'archive' / 'requests'
    archived = []

    if not requests_dir.exists():
        return archived

    dir_created = False
    for req_file in sorted(requests_dir.glob('*.yaml')):
        data = parse_yaml_file(str(req_file))
        if not data or not isinstance(data, dict):
            continue

        status = str(data.get('status', ''))
        if status in ('resolved', 'rejected'):
            if not dry_run:
                if not dir_created:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    dir_created = True
                shutil.move(str(req_file), str(archive_dir / req_file.name))
            archived.append((req_file.name, status))

    return archived


def archive_deltas(root, max_age_days, dry_run=False):
    """Archive deltas older than max_age_days."""
    deltas_dir = root / 'BUS' / 'deltas'
    archive_dir = root / 'BUS' / 'archive' / 'deltas'
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    archived = []

    if not deltas_dir.exists():
        return archived

    dir_created = False
    for delta_file in sorted(deltas_dir.glob('*.yaml')):
        data = parse_yaml_file(str(delta_file))
        if not data or not isinstance(data, dict):
            continue

        timestamp = data.get('timestamp')
        dt = parse_iso_date(str(timestamp)) if timestamp else None

        if dt and dt < cutoff:
            if not dry_run:
                if not dir_created:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    dir_created = True
                shutil.move(str(delta_file), str(archive_dir / delta_file.name))
            archived.append((delta_file.name, str(timestamp)))

    return archived


def main():
    parser = argparse.ArgumentParser(
        description='ANMA BUS Lifecycle Manager')
    parser.add_argument('--max-age', type=int, default=30,
                        help='Archive deltas older than N days (default: 30)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview without moving files')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = Path(args.path).resolve()
    prefix = "[DRY RUN] " if args.dry_run else ""

    print(f"\nANMA BUS Lifecycle Manager")
    print(f"  Max delta age: {args.max_age} days")
    if args.dry_run:
        print(f"  Mode: dry run (no files moved)")
    print()

    req_archived = archive_requests(root, args.dry_run)
    if req_archived:
        print(f"{prefix}Archived {len(req_archived)} resolved/rejected request(s):")
        for name, status in req_archived:
            print(f"  {name} ({status})")
    else:
        print("No resolved/rejected requests to archive.")

    print()

    delta_archived = archive_deltas(root, args.max_age, args.dry_run)
    if delta_archived:
        print(f"{prefix}Archived {len(delta_archived)} delta(s) older than {args.max_age} days:")
        for name, ts in delta_archived:
            print(f"  {name} ({ts})")
    else:
        print(f"No deltas older than {args.max_age} days to archive.")

    total = len(req_archived) + len(delta_archived)
    print(f"\n{prefix}Total: {total} file(s) archived.")


if __name__ == '__main__':
    main()
