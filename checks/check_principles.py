"""
ANMA Principle Enforcement — 7 checks mapping to 7 design principles.
Drop into checks/check_principles.py. The linter auto-discovers it.
"""
import re

# Implementation patterns (case-insensitive) — things that don't belong in contracts
_IMPL_PATTERNS = [
    (r'\b(mysql|postgres(?:ql)?|sqlite|mongodb|dynamodb|redis|firestore|cloud ?sql)\b', 'database engine'),
    (r'\b(python|java(?:script)?|kotlin|swift|dart|golang|rust|ruby|php|node\.?js|deno|bun)\b', 'language/runtime'),
    (r'\b(express|flask|django|fastapi|spring|rails|laravel|nextjs|nuxt|flutter|react)\b', 'framework'),
    (r'\b(bcrypt|argon2|scrypt|sha256|md5|aes)\b', 'crypto implementation'),
    (r'\bclass\s+\w+|def\s+\w+|function\s+\w+|import\s+\w+|require\(', 'source code'),
    (r'\b\w+\.(py|js|ts|dart|go|rs|java|kt|rb)\b', 'source file reference'),
    (r'\b(docker|kubernetes|k8s|nginx|apache)\b', 'infrastructure'),
    (r'\b(cloud ?run|cloud ?functions?|lambda|ec2|s3 bucket|gcs)\b', 'cloud service'),
    (r'\b(postgis|sequelize|prisma|typeorm|knex|orm)\b', 'data layer'),
]

_IMPL_WHITELIST = {'json', 'http', 'https', 'rest', 'graphql', 'grpc', 'websocket',
    'oauth', 'pkce', 'uuid', 'iso', 'utc', 'url', 'uri', 'api', 'cdn', 'ssl',
    'tls', 'smtp', 'fcm', 'apns', 'jwt'}

# PascalCase check (case-SENSITIVE) — catches actual class names like FirebaseAuth
_PASCAL_RE = re.compile(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b')
_PASCAL_OK = {'MyAnimeList', 'AniList', 'OAuth', 'PostGIS', 'AppCheck', 'SendGrid',
    'CloudSQL', 'FireStore', 'StoRSI'}


def _count_chars(filepath):
    try:
        return len(filepath.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError):
        return 0


def check_p1_contracts_over_code(root, contracts, result):
    """P1: Contracts describe behavior, never implementation."""
    print("── Principle 1: Contracts over code ──")
    for mod_name in contracts:
        contract_path = root / 'modules' / mod_name / 'CONTRACT.yaml'
        if not contract_path.exists():
            continue
        try:
            content = contract_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue

        seen = set()
        # Case-insensitive impl patterns
        for pattern, category in _IMPL_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                term = match.group(0).strip().lower()
                if term in _IMPL_WHITELIST:
                    continue
                line_start = content.rfind('\n', 0, match.start()) + 1
                if content[line_start:match.start()].lstrip().startswith('#'):
                    continue
                key = (term, category)
                if key not in seen:
                    seen.add(key)
                    result.warning(mod_name,
                        f"P1 contract references {category} '{term}' — "
                        f"move to ASSUMPTIONS.yaml")

        # Case-sensitive PascalCase check
        for match in _PASCAL_RE.finditer(content):
            term = match.group(0)
            if term in _PASCAL_OK:
                continue
            key = (term, 'class name')
            if key not in seen:
                seen.add(key)
                result.warning(mod_name,
                    f"P1 contract references class name '{term}' — "
                    f"contracts describe WHAT, not HOW")


def check_p2_tokens_are_bottleneck(root, contracts, result):
    """P2: Single contract max 600 tokens."""
    print("── Principle 2: Tokens are the bottleneck ──")
    for mod_name in contracts:
        contract_path = root / 'modules' / mod_name / 'CONTRACT.yaml'
        if not contract_path.exists():
            continue
        tokens = _count_chars(contract_path) // 4
        if tokens > 600:
            result.warning(mod_name,
                f"P2 contract is {tokens} tokens (max 600). "
                f"Consider splitting or compressing invariants")


def check_p3_state_is_explicit(root, contracts, result):
    """P3: Non-draft STATE.yaml must reflect actual work."""
    print("── Principle 3: State is explicit ──")
    for mod_name, contract in contracts.items():
        status = str(contract.get('status', 'draft')).lower()
        if status == 'draft':
            continue
        state_path = root / 'modules' / mod_name / 'STATE.yaml'
        if not state_path.exists():
            result.warning(mod_name, f"P3 non-draft module (status: {status}) has no STATE.yaml")
            continue
        try:
            content = state_path.read_text(encoding='utf-8').strip()
        except (OSError, UnicodeDecodeError):
            continue
        if len(content) < 30:
            result.warning(mod_name,
                f"P3 STATE.yaml nearly empty ({len(content)} chars) for {status} module")
        for marker in ['TODO', 'TBD', 'placeholder']:
            if marker.lower() in content.lower():
                result.warning(mod_name, f"P3 STATE.yaml contains '{marker}'")
                break


def check_p4_communication_is_async(root, contracts, all_contracts, result):
    """P4: Cross-module deps should have BUS events."""
    print("── Principle 4: Communication is async ──")
    bus_dir = root / 'BUS'
    bus_mentioned = set()
    if bus_dir.exists():
        for subdir in ['deltas', 'requests']:
            d = bus_dir / subdir
            if d.is_dir():
                for f in d.iterdir():
                    if f.suffix in ('.yaml', '.yml'):
                        try:
                            c = f.read_text(encoding='utf-8').lower()
                            for m in all_contracts:
                                if m in c:
                                    bus_mentioned.add(m)
                        except (OSError, UnicodeDecodeError):
                            pass

    for mod_name, contract in contracts.items():
        consumes = contract.get('consumes', [])
        if not consumes:
            continue
        consumed = []
        for dep in consumes:
            if isinstance(dep, dict):
                consumed.append(dep.get('module', ''))
            elif isinstance(dep, str):
                consumed.append(dep)
        if not consumed:
            continue

        has_bus = False
        for iface in (contract.get('provides', []) or []):
            if isinstance(iface, dict):
                for inv in (iface.get('invariants', []) or []):
                    if any(kw in str(inv).lower() for kw in
                           ['bus', 'event', 'publish', 'emit', 'subscribe', 'notify', 'trigger', 'queue']):
                        has_bus = True
                        break

        if not has_bus and mod_name not in bus_mentioned:
            result.warning(mod_name,
                f"P4 consumes [{', '.join(consumed)}] but no BUS events detected")


def check_p5_hierarchy_is_real(root, contracts, manifest, result):
    """P5: Every module has a manager, max 7 per manager."""
    print("── Principle 5: Hierarchy is real ──")
    if not manifest or not isinstance(manifest, dict):
        return
    modules_section = manifest.get('modules', {})
    if not isinstance(modules_section, dict):
        return
    manager_loads = {}
    for mod_name in contracts:
        meta = modules_section.get(mod_name, {})
        if not isinstance(meta, dict):
            meta = {}
        manager = meta.get('manager', '')
        if not manager and str(contracts[mod_name].get('status', 'draft')).lower() != 'draft':
            result.warning(mod_name, "P5 no manager assigned in MANIFEST.yaml")
        elif manager:
            manager_loads.setdefault(manager, []).append(mod_name)
    for manager, modules in manager_loads.items():
        if len(modules) > 7:
            result.warning(manager,
                f"P5 owns {len(modules)} modules (max 7): {', '.join(modules)}")


def check_p6_recovery_is_cheap(root, contracts, result):
    """P6: Module recovery (CONTRACT+STATE+MEMORY) under 1200 tokens."""
    print("── Principle 6: Recovery is cheap ──")
    for mod_name in contracts:
        module_dir = root / 'modules' / mod_name
        tokens = sum(_count_chars(module_dir / f) // 4
                     for f in ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml'])
        if tokens > 1200:
            result.warning(mod_name,
                f"P6 module recovery is {tokens} tokens (max 1200)")


def check_p7_replacement_over_continuity(root, contracts, result):
    """P7: MEMORY.yaml is structured insights, not logs or code."""
    print("── Principle 7: Replacement over continuity ──")
    red_flags = [
        (r'```', 'contains code blocks'),
        (r'\bdef \b|\bfunction \b|\bclass \b', 'contains source code'),
        (r'\b(said|told|asked|replied|discussed)\b', 'reads like a conversation log'),
    ]
    for mod_name in contracts:
        memory_path = root / 'modules' / mod_name / 'MEMORY.yaml'
        if not memory_path.exists():
            continue
        try:
            content = memory_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        for pattern, message in red_flags:
            if re.search(pattern, content, re.IGNORECASE):
                result.warning(mod_name, f"P7 MEMORY.yaml {message}")
                break


def run(root, contracts, all_contracts, conventions, manifest, result):
    """Plugin entry point."""
    check_p1_contracts_over_code(root, contracts, result)
    check_p2_tokens_are_bottleneck(root, contracts, result)
    check_p3_state_is_explicit(root, contracts, result)
    check_p4_communication_is_async(root, contracts, all_contracts, result)
    check_p5_hierarchy_is_real(root, contracts, manifest, result)
    check_p6_recovery_is_cheap(root, contracts, result)
    check_p7_replacement_over_continuity(root, contracts, result)
