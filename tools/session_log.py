"""ANMA Session History Logger.

Lightweight helper to append activity entries to SESSION-HISTORY.yaml.
Used by ANMA scripts to track project activity across sessions.
All functions are fail-safe — logging failures never break the calling script.

Suppress logging by setting ANMA_NO_LOG=1 in the environment.

Usage from other scripts:
    from session_log import log_activity
    log_activity(root, "linted 2 modules: 0 errors", "lint_contracts.py")
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path


def log_activity(root, action, script_name):
    """Append an activity entry to SESSION-HISTORY.yaml. Fails silently."""
    try:
        if os.environ.get('ANMA_NO_LOG'):
            return

        root = Path(root)
        history_path = root / 'SESSION-HISTORY.yaml'
        if not history_path.exists():
            return

        content = history_path.read_text()
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Update last_activity
        content = re.sub(
            r'^last_activity:.*$',
            f'last_activity: {now}',
            content, flags=re.MULTILINE)

        # Append to activity_log
        entry = (
            f"  - timestamp: {now}\n"
            f"    action: \"{action}\"\n"
            f"    script: {script_name}"
        )

        # Find the activity_log: [] line and replace, or find activity_log: and append
        lines = content.split('\n')
        if 'activity_log: []' in content:
            content = content.replace(
                'activity_log: []',
                f'activity_log:\n{entry}')
            lines = content.split('\n')
        elif 'activity_log:' in content:
            # Find the last entry (or the header) and append after it
            insert_idx = None
            in_log = False
            for i, line in enumerate(lines):
                if line.startswith('activity_log:'):
                    in_log = True
                    insert_idx = i
                    continue
                if in_log:
                    if line.startswith('  - ') or line.startswith('    '):
                        insert_idx = i
                    elif line.strip() and not line.startswith('#'):
                        break
            if insert_idx is not None:
                lines.insert(insert_idx + 1, entry)

        # Keep only last 50 entries to prevent unbounded growth
        entry_count = sum(1 for l in lines if l.strip().startswith('- timestamp:'))
        if entry_count > 50:
            # Find and remove oldest entries
            remove_count = entry_count - 50
            removed = 0
            new_lines = []
            skip_entry = False
            for line in lines:
                if removed < remove_count and line.strip().startswith('- timestamp:'):
                    skip_entry = True
                    removed += 1
                    continue
                if skip_entry and (line.startswith('    ') and not line.strip().startswith('- ')):
                    continue
                skip_entry = False
                new_lines.append(line)
            lines = new_lines

        history_path.write_text('\n'.join(lines))
    except Exception:
        pass  # Never break the calling script
