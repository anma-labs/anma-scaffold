#!/usr/bin/env python3
"""ANMA Contract Template Generator.

Generates a starting CONTRACT.yaml from a module name and purpose description.
Recognizes common patterns (CRUD, service, store) and generates appropriate
interfaces, errors, and invariants.

Usage:
    python3 gen_contract.py auth --purpose "User authentication and sessions"
    python3 gen_contract.py user-store --purpose "User data storage" --consumes auth
    python3 gen_contract.py payment-service --purpose "Billing and subscriptions" --type infrastructure

Not a replacement for contract design — just a faster starting point than TBD placeholders.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules


# Common interface patterns based on module name/purpose keywords
PATTERNS = {
    'crud': {
        'keywords': ['store', 'storage', 'data', 'repository', 'crud', 'records'],
        'interfaces': [
            {'id': 'create_{entity}', 'input': '{ data: object }', 'output': '{ id: uuid, created_at: timestamp }',
             'errors': ['{ENTITY}_ALREADY_EXISTS', 'MISSING_REQUIRED_FIELD', 'INVALID_INPUT']},
            {'id': 'get_{entity}', 'input': '{ id: uuid }', 'output': '{ id: uuid, data: object }',
             'errors': ['{ENTITY}_NOT_FOUND']},
            {'id': 'update_{entity}', 'input': '{ id: uuid, fields: object }', 'output': '{ updated_fields: "string[]" }',
             'errors': ['{ENTITY}_NOT_FOUND', 'INVALID_INPUT']},
            {'id': 'delete_{entity}', 'input': '{ id: uuid }', 'output': '{ success: boolean }',
             'errors': ['{ENTITY}_NOT_FOUND']},
            {'id': 'list_{entity}s', 'input': '{ filters: object, limit: integer, cursor: string_optional }',
             'output': '{ items: "object[]", next_cursor: string_optional }',
             'errors': []},
        ],
    },
    'auth': {
        'keywords': ['auth', 'authentication', 'login', 'session', 'identity'],
        'interfaces': [
            {'id': 'authenticate', 'input': '{ credentials: object }', 'output': '{ user_id: uuid, token: string }',
             'errors': ['INVALID_CREDENTIALS', 'ACCOUNT_LOCKED', 'ACCOUNT_SUSPENDED']},
            {'id': 'validate_token', 'input': '{ token: string }', 'output': '{ user_id: uuid, valid: boolean }',
             'errors': ['TOKEN_EXPIRED', 'INVALID_TOKEN']},
            {'id': 'logout', 'input': '{ user_id: uuid }', 'output': '{ success: boolean }',
             'errors': []},
        ],
    },
    'notification': {
        'keywords': ['notification', 'alert', 'push', 'email', 'messaging'],
        'interfaces': [
            {'id': 'send_notification', 'input': '{ user_id: uuid, type: string, template: string, variables: object }',
             'output': '{ notification_id: uuid }',
             'errors': ['USER_NOT_FOUND', 'TEMPLATE_NOT_FOUND', 'NOTIFICATION_DISABLED']},
            {'id': 'get_notifications', 'input': '{ user_id: uuid, limit: integer }',
             'output': '{ notifications: "object[]" }',
             'errors': ['USER_NOT_FOUND']},
            {'id': 'set_preferences', 'input': '{ user_id: uuid, preferences: object }',
             'output': '{ success: boolean }',
             'errors': ['USER_NOT_FOUND']},
        ],
    },
    'payment': {
        'keywords': ['payment', 'billing', 'subscription', 'purchase', 'charge'],
        'interfaces': [
            {'id': 'get_subscription', 'input': '{ user_id: uuid }', 'output': '{ tier: string, active: boolean, expires_at: timestamp }',
             'errors': ['USER_NOT_FOUND']},
            {'id': 'create_subscription', 'input': '{ user_id: uuid, tier: string, receipt: string }',
             'output': '{ subscription_id: uuid }',
             'errors': ['INVALID_RECEIPT', 'ALREADY_SUBSCRIBED']},
            {'id': 'cancel_subscription', 'input': '{ user_id: uuid }', 'output': '{ success: boolean }',
             'errors': ['NOT_SUBSCRIBED']},
        ],
    },
    'moderation': {
        'keywords': ['moderation', 'report', 'review', 'ban', 'content filter'],
        'interfaces': [
            {'id': 'report_content', 'input': '{ reporter_id: uuid, content_id: uuid, reason: string }',
             'output': '{ report_id: uuid }',
             'errors': ['CONTENT_NOT_FOUND', 'DUPLICATE_REPORT']},
            {'id': 'check_content', 'input': '{ content: string, type: string }',
             'output': '{ is_safe: boolean, flags: "string[]" }',
             'errors': ['CHECK_FAILED']},
            {'id': 'resolve_report', 'input': '{ report_id: uuid, action: string }',
             'output': '{ success: boolean }',
             'errors': ['REPORT_NOT_FOUND']},
        ],
    },
    'search': {
        'keywords': ['search', 'query', 'index', 'lookup', 'find', 'discover'],
        'interfaces': [
            {'id': 'search', 'input': '{ query: string, filters: object, limit: integer, offset: integer }',
             'output': '{ results: "object[]", total_count: integer }',
             'errors': ['INVALID_QUERY']},
            {'id': 'get_suggestions', 'input': '{ prefix: string, limit: integer }',
             'output': '{ suggestions: "string[]" }',
             'errors': []},
        ],
    },
    'analytics': {
        'keywords': ['analytics', 'metrics', 'tracking', 'stats', 'telemetry'],
        'interfaces': [
            {'id': 'track_event', 'input': '{ user_id: uuid, event: string, properties: object }',
             'output': '{ success: boolean }',
             'errors': ['INVALID_EVENT']},
            {'id': 'get_metrics', 'input': '{ metric: string, time_range: object }',
             'output': '{ data_points: "object[]", summary: object }',
             'errors': ['METRIC_NOT_FOUND', 'INVALID_TIME_RANGE']},
        ],
    },
    'media': {
        'keywords': ['media', 'upload', 'image', 'photo', 'file', 'asset', 'cdn'],
        'interfaces': [
            {'id': 'upload', 'input': '{ user_id: uuid, file_type: string, size_bytes: integer }',
             'output': '{ upload_url: string, asset_id: uuid }',
             'errors': ['FILE_TOO_LARGE', 'UNSUPPORTED_FORMAT']},
            {'id': 'get_asset', 'input': '{ asset_id: uuid }',
             'output': '{ url: string, metadata: object }',
             'errors': ['ASSET_NOT_FOUND']},
            {'id': 'delete_asset', 'input': '{ asset_id: uuid }',
             'output': '{ success: boolean }',
             'errors': ['ASSET_NOT_FOUND']},
        ],
    },
    'matching': {
        'keywords': ['matching', 'recommendation', 'score', 'compatibility', 'suggest', 'rank'],
        'interfaces': [
            {'id': 'calculate_score', 'input': '{ user_id: uuid, target_id: uuid }',
             'output': '{ score: number, breakdown: object }',
             'errors': ['USER_NOT_FOUND', 'TARGET_NOT_FOUND']},
            {'id': 'get_recommendations', 'input': '{ user_id: uuid, limit: integer, filters: object }',
             'output': '{ recommendations: "object[]" }',
             'errors': ['USER_NOT_FOUND']},
        ],
    },
}

# Default pattern when no keywords match
DEFAULT_PATTERN = {
    'interfaces': [
        {'id': 'get_{entity}', 'input': '{ id: uuid }', 'output': '{ data: object }',
         'errors': ['{ENTITY}_NOT_FOUND']},
        {'id': 'process_{entity}', 'input': '{ data: object }', 'output': '{ result: object }',
         'errors': ['INVALID_INPUT', 'PROCESSING_FAILED']},
    ],
}


def detect_pattern(name, purpose):
    """Detect which pattern(s) best match the module."""
    text = f"{name} {purpose}".lower()
    for pattern_name, pattern in PATTERNS.items():
        for kw in pattern['keywords']:
            if kw in text:
                return pattern_name, pattern
    return 'default', DEFAULT_PATTERN


def derive_entity(name):
    """Derive the entity name from the module name."""
    # user-store → user, auth-service → auth, payment-handler → payment
    parts = name.split('-')
    suffixes = {'service', 'store', 'handler', 'manager', 'engine', 'module', 'worker', 'gateway'}
    entity_parts = [p for p in parts if p not in suffixes]
    return '_'.join(entity_parts) if entity_parts else parts[0]


def generate_contract(name, purpose, consumes, mod_type, root=None, force_pattern=None):
    """Generate CONTRACT.yaml content."""
    entity = derive_entity(name)
    entity_upper = entity.upper().replace('-', '_')

    if force_pattern:
        if force_pattern in PATTERNS:
            pattern_name = force_pattern
            pattern = PATTERNS[force_pattern]
        elif force_pattern == 'default':
            pattern_name = 'default'
            pattern = DEFAULT_PATTERN
        else:
            pattern_name = 'default'
            pattern = DEFAULT_PATTERN
    else:
        pattern_name, pattern = detect_pattern(name, purpose)

    lines = [
        f"module: {name}",
        "version: 1",
        "status: draft",
        f"type: {mod_type}",
        f'purpose: "{purpose}"',
        "",
        "provides:",
    ]

    for iface in pattern['interfaces']:
        iface_id = iface['id'].replace('{entity}', entity)
        errors = [e.replace('{ENTITY}', entity_upper) for e in iface['errors']]
        errors_str = '[' + ', '.join(errors) + ']' if errors else '[]'
        lines.extend([
            f"  - id: {iface_id}",
            f"    input: {iface['input']}",
            f"    output: {iface['output']}",
            f"    errors: {errors_str}",
        ])

    lines.append("")
    if consumes:
        lines.append("consumes:")
        module_paths = {}
        if root:
            try:
                module_paths = discover_modules(root)
            except ValueError:
                module_paths = {}
        for dep in consumes:
            # Try to look up the provider's interfaces
            iface_name = 'TBD'
            if root:
                contract_path = module_paths.get(dep, root / 'modules' / dep) / 'CONTRACT.yaml'
                if contract_path.exists():
                    dep_contract = parse_yaml_file(str(contract_path))
                    if dep_contract and isinstance(dep_contract.get('provides'), list):
                        provides = dep_contract['provides']
                        iface_ids = [p['id'] for p in provides
                                     if isinstance(p, dict) and 'id' in p]
                        if iface_ids:
                            iface_name = iface_ids[0]  # use first interface
                            if len(iface_ids) > 1:
                                lines.append(f"  # {dep} also provides: {', '.join(iface_ids[1:])}")
            lines.extend([
                f"  - module: {dep}",
                f"    interface: {iface_name}",
                "    required: true",
                "    contract_version: 1",
            ])
    else:
        lines.append("consumes: []")

    lines.extend([
        "",
        "contract_rules:",
        "  adding_interface: allowed",
        "  modifying_interface: notify",
        "  removing_interface: breaking",
    ])

    return '\n'.join(lines) + '\n', pattern_name


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Contract Template Generator')
    parser.add_argument('name', nargs='?', help='Module name (kebab-case)')
    parser.add_argument('--purpose', type=str, default=None,
                        help='Module purpose description')
    parser.add_argument('--consumes', type=str, default=None,
                        help='Comma-separated dependencies')
    parser.add_argument('--type', type=str, default='regular',
                        choices=['regular', 'infrastructure'])
    parser.add_argument('--output', type=str, default=None,
                        help='Output file path (default: stdout)')
    parser.add_argument('--pattern', type=str, default=None,
                        help='Force a specific pattern (skip auto-detection)')
    parser.add_argument('--list-patterns', action='store_true',
                        help='Show available patterns and exit')
    args = parser.parse_args()

    if args.list_patterns:
        print("Available patterns:")
        for name, pat in sorted(PATTERNS.items()):
            ifaces = [i['id'] for i in pat['interfaces']]
            kws = ', '.join(pat['keywords'][:3])
            print(f"  {name:14s} {len(ifaces)} interfaces  (keywords: {kws})")
        print(f"  {'default':14s} 2 interfaces  (fallback when no keywords match)")
        sys.exit(0)

    if not args.name:
        parser.error("module name is required (or use --list-patterns)")

    if not args.purpose:
        parser.error("--purpose is required")

    consumes = [c.strip() for c in args.consumes.split(',') if c.strip()] if args.consumes else []
    # Find project root for provider interface lookup
    root = Path('.').resolve()
    if not (root / 'MANIFEST.yaml').exists():
        root = None  # not in a project — skip provider lookup

    content, pattern = generate_contract(
        args.name, args.purpose, consumes, args.type,
        root=root, force_pattern=args.pattern)

    if args.pattern and args.pattern not in PATTERNS and args.pattern != 'default':
        print(f"# Unknown pattern '{args.pattern}', using default. "
              f"Run --list-patterns to see options.", file=sys.stderr)

    print(f"# Pattern detected: {pattern}", file=sys.stderr)
    print(f"# Entity derived: {derive_entity(args.name)}", file=sys.stderr)

    if args.output:
        Path(args.output).write_text(content)
        print(f"# Written to {args.output}", file=sys.stderr)
    else:
        print(content)


if __name__ == '__main__':
    main()
