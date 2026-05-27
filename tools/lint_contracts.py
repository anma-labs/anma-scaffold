#!/usr/bin/env python3
"""
ANMA Contract Linter v0.1
Validates the structural integrity of an AI-Native Modular Architecture project.

Run from project root:
    python lint_contracts.py [--strict] [--module MODULE_NAME]

Exit codes:
    0 = all checks passed
    1 = errors found
    2 = warnings found (only with --strict)
"""

import sys
import re
import argparse
import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path

from discover import discover_modules, discover_domains, get_module_domain

# ---------------------------------------------------------------------------
# YAML parsing — uses PyYAML when available, falls back to built-in parser.
# The built-in handles the flat/nested YAML used in ANMA contracts.
# Install PyYAML for full YAML support: pip install pyyaml
# ---------------------------------------------------------------------------

# Try to import PyYAML
_HAS_PYYAML = False
_PYYAML_NOTICE_SHOWN = False
try:
    import yaml as _yaml
    _HAS_PYYAML = True
except ImportError:
    _yaml = None


def parse_yaml_file(filepath, strict=False):
    """Parse a YAML file into a Python dict.

    Uses PyYAML (yaml.safe_load) when available for full YAML support.
    Falls back to built-in parser for the ANMA YAML subset.

    Args:
        filepath: Path to the YAML file.
        strict: If True (built-in parser only), error on unparsable lines
                instead of skipping them.
    """
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        return _parse_yaml_auto(content, source=str(filepath), strict=strict)
    except FileNotFoundError:
        return None
    except Exception as e:
        return {'_parse_error': str(e)}


def _parse_yaml_auto(text, source=None, strict=False):
    """Parse YAML text, choosing the best available parser."""
    global _PYYAML_NOTICE_SHOWN

    if _HAS_PYYAML:
        try:
            result = _yaml.safe_load(text)
            if result is None:
                return {}
            _normalize_types(result)
            return result
        except _yaml.YAMLError as e:
            return {'_parse_error': f"PyYAML: {e}"}

    # Built-in parser fallback
    if not _PYYAML_NOTICE_SHOWN:
        import sys
        print("  note: PyYAML not found, using built-in parser"
              " (install with: pip install pyyaml)", file=sys.stderr)
        _PYYAML_NOTICE_SHOWN = True

    return parse_yaml(text, strict=strict)


def _normalize_types(obj):
    """Recursively convert PyYAML-specific types (datetime, date) to strings
    for consistency with the built-in parser."""
    from datetime import datetime, date
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, datetime):
                obj[k] = v.isoformat().replace('+00:00', 'Z')
            elif isinstance(v, date):
                obj[k] = v.isoformat()
            elif isinstance(v, (dict, list)):
                _normalize_types(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, datetime):
                obj[i] = v.isoformat().replace('+00:00', 'Z')
            elif isinstance(v, date):
                obj[i] = v.isoformat()
            elif isinstance(v, (dict, list)):
                _normalize_types(v)


def parse_yaml(text, strict=False):
    """Built-in minimal YAML parser for ANMA contract files.

    Args:
        strict: If True, include parse warnings for any skipped lines.
    """
    lines = text.split('\n')
    warnings = []
    result, _ = _parse_block(lines, 0, 0, warnings)
    if warnings:
        if not isinstance(result, dict):
            result = {}
        result['_parse_warnings'] = warnings
        if strict:
            result['_parse_error'] = (
                f"Built-in parser skipped {len(warnings)} line(s): "
                + "; ".join(warnings[:3])
            )
    return result


def _current_indent(line):
    return len(line) - len(line.lstrip())


def _strip_comment(line):
    """Remove inline comments, respecting quoted strings."""
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == '#' and not in_single and not in_double:
            return line[:i].rstrip()
    return line.rstrip()


def _parse_flow_value(val):
    """Parse inline YAML values: flow mappings, flow lists, scalars."""
    val = val.strip()
    if not val or val == 'null' or val == 'Null' or val == 'NULL' or val == '~':
        return None
    if val.lower() in ('true', 'yes', 'on'):
        return True
    if val.lower() in ('false', 'no', 'off'):
        return False
    # Flow list: [a, b, c]
    if val.startswith('[') and val.endswith(']'):
        inner = val[1:-1].strip()
        if not inner:
            return []
        items = _split_flow(inner)
        return [_parse_flow_value(i) for i in items]
    # Flow mapping: {key: val, key: val}
    if val.startswith('{') and val.endswith('}'):
        inner = val[1:-1].strip()
        if not inner:
            return {}
        result = {}
        pairs = _split_flow(inner)
        for pair in pairs:
            if ':' in pair:
                k, v = pair.split(':', 1)
                result[k.strip().strip('"').strip("'")] = _parse_flow_value(v)
        return result
    # Quoted string
    if (val.startswith('"') and val.endswith('"')) or \
       (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    # Number
    try:
        if '.' in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    return val


def _split_flow(text):
    """Split flow sequence/mapping items respecting nested braces/brackets."""
    items = []
    depth = 0
    current = []
    for ch in text:
        if ch in ('{', '['):
            depth += 1
            current.append(ch)
        elif ch in ('}', ']'):
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            items.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        items.append(''.join(current).strip())
    return items


def _parse_block(lines, idx, base_indent, warnings=None):
    """Parse a YAML block into a dict, returning (result, next_index)."""
    result = {}
    while idx < len(lines):
        raw = lines[idx]
        # Skip blank lines and comments
        if not raw.strip() or raw.strip().startswith('#'):
            idx += 1
            continue
        indent = _current_indent(raw)
        if indent < base_indent:
            break
        if indent > base_indent and base_indent >= 0:
            break

        line = _strip_comment(raw)
        if not line.strip():
            idx += 1
            continue

        # List item at current indent
        stripped = line.strip()
        if stripped.startswith('- '):
            # We've hit a list; the caller handles this
            break

        # Key-value pair
        if ':' in stripped:
            colon_pos = stripped.index(':')
            key = stripped[:colon_pos].strip().strip('"').strip("'")
            val_part = stripped[colon_pos + 1:].strip()

            if val_part:
                # Inline value
                result[key] = _parse_flow_value(val_part)
                idx += 1
            else:
                # Check what's below
                idx += 1
                if idx < len(lines):
                    next_raw = lines[idx]
                    while idx < len(lines) and (not next_raw.strip() or next_raw.strip().startswith('#')):
                        idx += 1
                        if idx < len(lines):
                            next_raw = lines[idx]
                        else:
                            break

                    if idx < len(lines):
                        next_indent = _current_indent(next_raw)
                        next_stripped = next_raw.strip()
                        if next_indent > indent:
                            if next_stripped.startswith('- '):
                                # List
                                lst, idx = _parse_list(lines, idx, next_indent, warnings)
                                result[key] = lst
                            else:
                                # Nested mapping
                                nested, idx = _parse_block(lines, idx, next_indent, warnings)
                                result[key] = nested
                        else:
                            result[key] = None
                    else:
                        result[key] = None
                else:
                    result[key] = None
        else:
            if warnings is not None:
                warnings.append(f"line {idx + 1}: skipped (no key:value pair): {stripped[:60]}")
            idx += 1
    return result, idx


def _parse_list(lines, idx, base_indent, warnings=None):
    """Parse a YAML list, returning (list, next_index)."""
    result = []
    while idx < len(lines):
        raw = lines[idx]
        if not raw.strip() or raw.strip().startswith('#'):
            idx += 1
            continue
        indent = _current_indent(raw)
        if indent < base_indent:
            break

        stripped = raw.strip()
        if not stripped.startswith('- '):
            break

        item_val = stripped[2:].strip()

        # Quoted string or flow value: treat as scalar even if it contains ':'
        if item_val and (
            (item_val.startswith('"') and item_val.endswith('"')) or
            (item_val.startswith("'") and item_val.endswith("'")) or
            (item_val.startswith('{') and item_val.endswith('}')) or
            (item_val.startswith('[') and item_val.endswith(']'))
        ):
            result.append(_parse_flow_value(item_val))
            idx += 1
        # Simple list item: - value (no colon)
        elif item_val and ':' not in item_val:
            result.append(_parse_flow_value(item_val))
            idx += 1
        elif item_val and ':' in item_val:
            # Inline mapping start: - key: value
            # Could be a single-line or start of a mapping block
            colon_pos = item_val.index(':')
            key = item_val[:colon_pos].strip().strip('"').strip("'")
            val_part = item_val[colon_pos + 1:].strip()

            item_dict = {}
            if val_part:
                item_dict[key] = _parse_flow_value(val_part)
            else:
                item_dict[key] = None

            idx += 1
            # Check for continuation lines belonging to this list item
            if idx < len(lines):
                next_raw = lines[idx]
                while idx < len(lines) and (not next_raw.strip() or next_raw.strip().startswith('#')):
                    idx += 1
                    if idx < len(lines):
                        next_raw = lines[idx]
                    else:
                        break
                if idx < len(lines):
                    next_indent = _current_indent(next_raw)
                    # Continuation keys are indented further than the dash
                    if next_indent > indent:
                        more, idx = _parse_block(lines, idx, next_indent, warnings)
                        item_dict.update(more)
            result.append(item_dict)
        else:
            # Bare dash: block value follows on next lines
            idx += 1
            if idx < len(lines):
                next_indent = _current_indent(lines[idx])
                if next_indent > indent:
                    nested, idx = _parse_block(lines, idx, next_indent, warnings)
                    result.append(nested)
                else:
                    result.append(None)
            else:
                result.append(None)

    return result, idx


# ---------------------------------------------------------------------------
# Linter checks
# ---------------------------------------------------------------------------

class LintResult:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, module, message):
        self.errors.append(f"ERROR [{module}]: {message}")

    def warning(self, module, message):
        self.warnings.append(f"WARN  [{module}]: {message}")

    def ok(self):
        return len(self.errors) == 0

    def print_report(self):
        for e in self.errors:
            print(f"  ✗ {e}")
            suggestion = _suggest_fix(e)
            if suggestion:
                print(f"    → {suggestion}")
        for w in self.warnings:
            print(f"  ⚠ {w}")
            suggestion = _suggest_fix(w)
            if suggestion:
                print(f"    → {suggestion}")
        print()
        total_e = len(self.errors)
        total_w = len(self.warnings)
        if total_e == 0 and total_w == 0:
            print("  ✓ All checks passed.")
        else:
            print(f"  {total_e} error(s), {total_w} warning(s)")


# Suggestion patterns: (substring_to_match, suggestion_text)
_SUGGESTIONS = [
    # TBD placeholders
    (".TBD'", "Design the contract: replace 'interface: TBD' in CONTRACT.yaml with a real interface name"),
    ("has no provides section", "Run: python3 gen_contract.py <module> --purpose '<desc>' --output modules/<module>/CONTRACT.yaml"),
    # Missing files
    ("Missing STATE.yaml", "Run: python3 new_module.py to scaffold, or create STATE.yaml manually"),
    ("Missing MEMORY.yaml", "Create modules/<module>/MEMORY.yaml with: module: <name>\\nentries: []"),
    ("Missing TESTS.yaml", "Create modules/<module>/TESTS.yaml with test cases for each interface"),
    ("Missing ASSUMPTIONS.yaml", "Create modules/<module>/ASSUMPTIONS.yaml with: module: <name>\\nassumptions: []"),
    # Structure
    ("missing required field 'provides'", "Add a 'provides:' section listing the module's interfaces"),
    ("missing required field 'purpose'", "Add: purpose: \"One-line description of what this module does\""),
    ("missing required field 'version'", "Add: version: 1"),
    ("missing required field 'status'", "Add: status: draft"),
    # Naming
    ("is not kebab-case", "Use lowercase with hyphens: my-module-name"),
    ("is not snake_case", "Use lowercase with underscores: my_interface_name"),
    ("is not SCREAMING_SNAKE_CASE", "Use uppercase with underscores: MY_ERROR_CODE"),
    # GRAPH
    ("has CONTRACT but missing from GRAPH", "Run: python3 gen_graph.py"),
    ("CONTRACT consumes", "Run: python3 gen_graph.py to regenerate"),
    ("has CONTRACT but missing from MANIFEST", "Add module to MANIFEST.yaml modules section, or run new_module.py"),
    # Version pins
    ("without contract_version pin", "Add 'contract_version: 1' to the consumes entry in CONTRACT.yaml"),
    ("pinned to v", "Update contract_version in the consumes entry to match the provider's current version"),
    # Budget
    ("context budget", "Split large files: move implementation details from CONTRACT to ASSUMPTIONS"),
    # Granularity
    ("interfaces (over", "Consider splitting into two modules with clearer responsibilities"),
    # Memory
    ("entries (max", "Curate MEMORY.yaml: delete stale entries before adding new ones"),
    ("total content is", "Shorten entries in MEMORY.yaml: max 100 chars each, one line per entry"),
    # Assumptions
    ("has assumptions from", "Review these modules' ASSUMPTIONS.yaml for conflicting implementation choices"),
    # Frozen
    ("is frozen but allows", "Set modifying_interface and removing_interface to 'forbidden' in contract_rules"),
    # Circular
    ("Circular hard dependency", "Break the cycle: change one dependency to 'required: false' or use BUS instead"),
    # Stale
    ("open/acknowledged", "Resolve or reject this request, or escalate to the manager"),
    # Replacement
    ("non-draft modules must have", "Create the missing file to ensure any fresh agent can take over this module"),
    # SCOPE
    ("which is not a known module", "Remove the stale module name from the manager's SCOPE.yaml owns list"),
    # STRATEGY/PLAN
    ("references module", "Update the file to remove references to deleted modules"),
    ("references manager", "Update orchestrator/PLAN.yaml to reference current managers"),
    # Schema
    ("has unknown key", "Check for typos — remove or rename the unrecognized key"),
    ("should be list", "Use YAML list syntax: key: [item1, item2] or key:\\n  - item1"),
    ("should be str", "Wrap the value in quotes: key: \"value\""),
    ("should be int", "Use a plain number without quotes: key: 1"),
    ("should be dict", "Use YAML mapping syntax: key:\\n  subkey: value"),
]


def _suggest_fix(message):
    """Return a fix suggestion for a lint message, or None."""
    for pattern, suggestion in _SUGGESTIONS:
        if pattern in message:
            return suggestion
    return None


def find_project_root(start_path='.'):
    """Find project root by looking for MANIFEST.yaml."""
    p = Path(start_path).resolve()
    if (p / 'MANIFEST.yaml').exists():
        return p
    for parent in p.parents:
        if (parent / 'MANIFEST.yaml').exists():
            return parent
    return Path(start_path).resolve()


def load_all_contracts(root):
    """Load all module CONTRACT.yaml files. Returns {module_name: contract_dict}.
    Includes empty/malformed contracts so structure checks can report them."""
    contracts = {}
    try:
        module_paths = discover_modules(root)
    except ValueError:
        # Duplicate module names — main() will re-call discover_modules and
        # surface the error there. Return empty so the "no contracts" check
        # in main() doesn't mask it.
        return contracts
    for mod_name, mod_dir in module_paths.items():
        contract_file = mod_dir / 'CONTRACT.yaml'
        data = parse_yaml_file(str(contract_file))
        if data is None:
            # File vanished between discovery and open(), treat as empty
            data = {}
        if '_parse_error' in data:
            # Parser returned an error — still include with empty dict
            # so structure checks will report missing fields
            print(f"  ⚠ WARNING: {contract_file} could not be parsed: "
                  f"{data['_parse_error']}")
            data = {}
        contracts[mod_name] = data
    return contracts


def load_graph(root):
    """Load GRAPH.yaml."""
    return parse_yaml_file(str(root / 'GRAPH.yaml'))


def load_conventions(root):
    """Load CONVENTIONS.yaml."""
    return parse_yaml_file(str(root / 'CONVENTIONS.yaml'))


def load_manifest(root):
    """Load MANIFEST.yaml."""
    return parse_yaml_file(str(root / 'MANIFEST.yaml'))


# ---------------------------------------------------------------------------
# Check 1: Contract cross-references
# Every consumes entry must point to a real provides entry in target module.
# ---------------------------------------------------------------------------

def check_cross_references(contracts, all_contracts, result):
    """Verify every consumes entry resolves to a real provides entry."""
    print("── Check 1: Contract cross-references ──")

    for mod_name, contract in contracts.items():
        consumes = contract.get('consumes')
        if not consumes or not isinstance(consumes, list):
            continue

        for dep in consumes:
            if not isinstance(dep, dict):
                continue
            target_module = dep.get('module')
            target_interface = dep.get('interface')

            if not target_module:
                result.error(mod_name, f"consumes entry missing 'module' field")
                continue

            if target_module not in all_contracts:
                result.error(mod_name,
                    f"consumes module '{target_module}' but no CONTRACT.yaml found for it")
                continue

            if not target_interface:
                result.error(mod_name,
                    f"consumes from '{target_module}' but missing 'interface' field")
                continue

            # Check the target module actually provides this interface
            target_contract = all_contracts[target_module]
            provides = target_contract.get('provides')
            if not provides or not isinstance(provides, list):
                result.error(mod_name,
                    f"consumes '{target_module}.{target_interface}' but "
                    f"'{target_module}' has no provides section")
                continue

            provided_ids = []
            for p in provides:
                if isinstance(p, dict):
                    provided_ids.append(p.get('id'))

            if target_interface not in provided_ids:
                result.error(mod_name,
                    f"consumes '{target_module}.{target_interface}' but "
                    f"'{target_module}' only provides: {provided_ids}")


# ---------------------------------------------------------------------------
# Check 2: GRAPH.yaml matches actual contracts
# ---------------------------------------------------------------------------

def check_graph_consistency(contracts, all_contracts, graph, result):
    """Verify GRAPH.yaml matches the consumes/consumed_by in actual contracts."""
    print("── Check 2: GRAPH.yaml consistency ──")

    if not graph:
        result.error('GRAPH', "GRAPH.yaml missing or unparseable")
        return

    graph_modules = graph.get('modules', {})
    if not isinstance(graph_modules, dict):
        result.error('GRAPH', "GRAPH.yaml 'modules' is not a mapping")
        return

    # Build actual dependency map from contracts being linted
    actual_consumes = {}
    for mod_name, contract in contracts.items():
        deps = []
        consumes = contract.get('consumes')
        if consumes and isinstance(consumes, list):
            for dep in consumes:
                if isinstance(dep, dict) and dep.get('module'):
                    deps.append(dep['module'])
        actual_consumes[mod_name] = sorted(set(deps))  # deduplicate to match gen_graph.py

    # Compare linted modules with GRAPH
    for mod_name, actual_deps in actual_consumes.items():
        if mod_name not in graph_modules:
            result.error('GRAPH',
                f"Module '{mod_name}' has a CONTRACT but is missing from GRAPH.yaml")
            continue

        graph_entry = graph_modules[mod_name]
        graph_deps = graph_entry.get('consumes', [])
        if not isinstance(graph_deps, list):
            graph_deps = []
        graph_deps = sorted(graph_deps)

        if actual_deps != graph_deps:
            result.error('GRAPH',
                f"Module '{mod_name}': CONTRACT consumes {actual_deps} "
                f"but GRAPH says {graph_deps}")

    # Check for modules in GRAPH but not in any contract (use all_contracts)
    for mod_name in graph_modules:
        if mod_name not in all_contracts:
            result.warning('GRAPH',
                f"Module '{mod_name}' in GRAPH.yaml but no CONTRACT.yaml found")

    # Verify consumed_by is the inverse of consumes
    for mod_name, entry in graph_modules.items():
        consumed_by = entry.get('consumed_by', [])
        if not isinstance(consumed_by, list):
            consumed_by = []
        for consumer in consumed_by:
            consumer_entry = graph_modules.get(consumer, {})
            consumer_deps = consumer_entry.get('consumes', [])
            if not isinstance(consumer_deps, list):
                consumer_deps = []
            if mod_name not in consumer_deps:
                result.error('GRAPH',
                    f"'{mod_name}' lists '{consumer}' in consumed_by, "
                    f"but '{consumer}' doesn't list '{mod_name}' in consumes")

    # Check for duplicate entries in consumes and consumed_by lists
    for mod_name, entry in graph_modules.items():
        consumes_list = entry.get('consumes', [])
        if isinstance(consumes_list, list) and len(consumes_list) != len(set(consumes_list)):
            dupes = [x for x in consumes_list if consumes_list.count(x) > 1]
            result.warning('GRAPH',
                f"'{mod_name}' has duplicate entries in consumes: {sorted(set(dupes))}")
        consumed_by_list = entry.get('consumed_by', [])
        if isinstance(consumed_by_list, list) and len(consumed_by_list) != len(set(consumed_by_list)):
            dupes = [x for x in consumed_by_list if consumed_by_list.count(x) > 1]
            result.warning('GRAPH',
                f"'{mod_name}' has duplicate entries in consumed_by: {sorted(set(dupes))}")


# ---------------------------------------------------------------------------
# Check 3: Naming conventions
# ---------------------------------------------------------------------------

def check_naming_conventions(contracts, conventions, result):
    """Verify all names follow CONVENTIONS.yaml rules."""
    print("── Check 3: Naming conventions ──")

    naming = {}
    if conventions:
        naming = conventions.get('naming', {})

    # Module names: kebab-case
    module_pattern = re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$')
    for mod_name in contracts:
        if not module_pattern.match(mod_name):
            result.error(mod_name,
                f"Module name '{mod_name}' is not kebab-case")

    # Interface names: snake_case
    interface_pattern = re.compile(r'^[a-z][a-z0-9]*(_[a-z0-9]+)*$')
    for mod_name, contract in contracts.items():
        provides = contract.get('provides')
        if not provides or not isinstance(provides, list):
            continue
        for p in provides:
            if not isinstance(p, dict):
                continue
            iface_id = p.get('id', '')
            if iface_id and not interface_pattern.match(str(iface_id)):
                result.error(mod_name,
                    f"Interface '{iface_id}' is not snake_case")

    # Error codes: SCREAMING_SNAKE_CASE
    error_pattern = re.compile(r'^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$')
    for mod_name, contract in contracts.items():
        provides = contract.get('provides')
        if not provides or not isinstance(provides, list):
            continue
        for p in provides:
            if not isinstance(p, dict):
                continue
            errors = p.get('errors', [])
            if not isinstance(errors, list):
                continue
            for err in errors:
                if isinstance(err, str) and not error_pattern.match(err):
                    result.error(mod_name,
                        f"Error code '{err}' in interface '{p.get('id')}' "
                        f"is not SCREAMING_SNAKE_CASE")


# ---------------------------------------------------------------------------
# Check 4: Circular hard dependencies
# ---------------------------------------------------------------------------

def check_circular_dependencies(contracts, result):
    """Detect circular chains of required (hard) dependencies."""
    print("── Check 4: Circular dependency detection ──")

    # Build adjacency list of hard dependencies only
    hard_deps = {}
    for mod_name, contract in contracts.items():
        deps = []
        consumes = contract.get('consumes')
        if consumes and isinstance(consumes, list):
            for dep in consumes:
                if isinstance(dep, dict):
                    required = dep.get('required', True)
                    if required is True or (isinstance(required, str) and required.lower() in ('true', 'yes', 'on')):
                        target = dep.get('module')
                        if target:
                            deps.append(target)
        hard_deps[mod_name] = deps

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {m: WHITE for m in hard_deps}
    path = []
    cycles = []

    def dfs(node):
        if node not in color:
            return
        color[node] = GRAY
        path.append(node)
        for neighbor in hard_deps.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
            elif color[neighbor] == WHITE:
                dfs(neighbor)
        path.pop()
        color[node] = BLACK

    for mod in hard_deps:
        if color[mod] == WHITE:
            dfs(mod)

    for cycle in cycles:
        cycle_str = ' → '.join(cycle)
        result.error('CIRCULAR',
            f"Circular hard dependency detected: {cycle_str}")

    if not cycles:
        # Also check for soft-dep cycles as warnings
        all_deps = {}
        for mod_name, contract in contracts.items():
            deps = []
            consumes = contract.get('consumes')
            if consumes and isinstance(consumes, list):
                for dep in consumes:
                    if isinstance(dep, dict) and dep.get('module'):
                        deps.append(dep['module'])
            all_deps[mod_name] = deps

        color2 = {m: WHITE for m in all_deps}
        path2 = []

        def dfs2(node):
            if node not in color2:
                return
            color2[node] = GRAY
            path2.append(node)
            for neighbor in all_deps.get(node, []):
                if neighbor not in color2:
                    continue
                if color2[neighbor] == GRAY:
                    cycle_start = path2.index(neighbor)
                    cycle = path2[cycle_start:] + [neighbor]
                    cycle_str = ' → '.join(cycle)
                    result.warning('CIRCULAR',
                        f"Circular soft dependency: {cycle_str}")
                elif color2[neighbor] == WHITE:
                    dfs2(neighbor)
            path2.pop()
            color2[node] = BLACK

        for mod in all_deps:
            if color2[mod] == WHITE:
                dfs2(mod)


# ---------------------------------------------------------------------------
# Check 5: Contract structure completeness
# ---------------------------------------------------------------------------

def check_contract_structure(contracts, result):
    """Verify each contract has all required fields."""
    print("── Check 5: Contract structure completeness ──")

    required_top = ['module', 'version', 'status', 'purpose', 'provides']
    required_interface = ['id', 'input', 'output']
    valid_statuses = ['stable', 'draft', 'breaking-change', 'deprecated', 'frozen']

    for mod_name, contract in contracts.items():
        # Top-level fields
        for field in required_top:
            if field not in contract:
                result.error(mod_name, f"CONTRACT missing required field '{field}'")

        # Status validation
        status = contract.get('status')
        if status and str(status) not in valid_statuses:
            result.warning(mod_name,
                f"CONTRACT status '{status}' not in {valid_statuses}")

        # Module name matches directory
        declared = contract.get('module')
        if declared and str(declared) != mod_name:
            result.error(mod_name,
                f"CONTRACT declares module='{declared}' but directory is '{mod_name}'")

        # Interface completeness
        provides = contract.get('provides')
        if provides and isinstance(provides, list):
            seen_ids = set()
            for p in provides:
                if not isinstance(p, dict):
                    result.error(mod_name, f"provides entry is not a mapping")
                    continue
                for field in required_interface:
                    if field not in p:
                        result.error(mod_name,
                            f"Interface '{p.get('id', '??')}' missing '{field}'")
                iface_id = p.get('id')
                if iface_id:
                    if iface_id in seen_ids:
                        result.error(mod_name,
                            f"Duplicate interface id '{iface_id}'")
                    seen_ids.add(iface_id)

                # Check invariants exist
                invariants = p.get('invariants')
                if not invariants:
                    result.warning(mod_name,
                        f"Interface '{iface_id}' has no invariants defined")

        # Frozen contract validation
        if str(status) == 'frozen':
            rules = contract.get('contract_rules')
            if rules is None:
                result.error(mod_name,
                    "frozen CONTRACT missing 'contract_rules' "
                    "(must set modifying_interface and removing_interface to 'forbidden')")
            elif not isinstance(rules, dict):
                result.error(mod_name,
                    "frozen CONTRACT 'contract_rules' is not a mapping "
                    "(must set modifying_interface and removing_interface to 'forbidden')")
            else:
                modify_rule = rules.get('modifying_interface')
                if not modify_rule or str(modify_rule) != 'forbidden':
                    result.error(mod_name,
                        f"frozen CONTRACT modifying_interface='{modify_rule}' "
                        f"(must be 'forbidden')")
                remove_rule = rules.get('removing_interface')
                if not remove_rule or str(remove_rule) != 'forbidden':
                    result.error(mod_name,
                        f"frozen CONTRACT removing_interface='{remove_rule}' "
                        f"(must be 'forbidden')")


# ---------------------------------------------------------------------------
# Check 6: MANIFEST.yaml consistency
# ---------------------------------------------------------------------------

def check_manifest_consistency(contracts, manifest, result):
    """Verify MANIFEST.yaml lists all modules and states match."""
    print("── Check 6: MANIFEST.yaml consistency ──")

    if not manifest:
        result.error('MANIFEST', "MANIFEST.yaml missing or unparseable")
        return

    manifest_modules = manifest.get('modules', {})
    if not isinstance(manifest_modules, dict):
        result.error('MANIFEST', "'modules' is not a mapping")
        return

    for mod_name in contracts:
        if mod_name not in manifest_modules:
            result.error('MANIFEST',
                f"Module '{mod_name}' has CONTRACT but missing from MANIFEST.yaml")

    for mod_name in manifest_modules:
        if mod_name not in contracts:
            result.warning('MANIFEST',
                f"Module '{mod_name}' in MANIFEST but no CONTRACT.yaml found")


# ---------------------------------------------------------------------------
# Check 7: STATE.yaml existence and health
# ---------------------------------------------------------------------------

def check_state_files(root, contracts, result, module_paths=None):
    """Verify each module has a STATE.yaml with required fields."""
    print("── Check 7: STATE.yaml existence ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    required_state_fields = ['module', 'status']
    valid_statuses = ['green', 'yellow', 'red', 'blocked']

    for mod_name in contracts:
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        state_file = mod_dir / 'STATE.yaml'
        if not state_file.exists():
            result.warning(mod_name, "Missing STATE.yaml")
            continue

        state = parse_yaml_file(str(state_file))
        if not state:
            result.error(mod_name, "STATE.yaml exists but is empty or unparseable")
            continue

        for field in required_state_fields:
            if field not in state:
                result.error(mod_name, f"STATE.yaml missing field '{field}'")

        status = state.get('status')
        if status and str(status) not in valid_statuses:
            result.warning(mod_name,
                f"STATE.yaml status '{status}' not in {valid_statuses}")


# ---------------------------------------------------------------------------
# Check 8: MEMORY.yaml caps and health
# ---------------------------------------------------------------------------

def check_memory_files(root, contracts, conventions, result, module_paths=None):
    """Verify each module's MEMORY.yaml stays within budget."""
    print("── Check 8: MEMORY.yaml caps ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    # Load limits from conventions, with defaults
    mem_conventions = {}
    if conventions and isinstance(conventions, dict):
        mem_conventions = conventions.get('memory', {})
        if not isinstance(mem_conventions, dict):
            mem_conventions = {}

    max_entries = mem_conventions.get('max_entries', 20)
    max_content_chars = mem_conventions.get('max_content_chars', 100)
    valid_types = mem_conventions.get('valid_types',
        ['decision', 'discovery', 'warning', 'pattern'])

    for mod_name in contracts:
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        mem_file = mod_dir / 'MEMORY.yaml'
        if not mem_file.exists():
            result.warning(mod_name, "Missing MEMORY.yaml")
            continue

        mem = parse_yaml_file(str(mem_file))
        if not mem:
            result.error(mod_name, "MEMORY.yaml exists but is empty or unparseable")
            continue

        # Check module field
        declared = mem.get('module')
        if not declared:
            result.error(mod_name, "MEMORY.yaml missing 'module' field")
        elif str(declared) != mod_name:
            result.error(mod_name,
                f"MEMORY.yaml declares module='{declared}' but directory is '{mod_name}'")

        # Check entries field exists and is a list
        entries = mem.get('entries')
        if entries is None:
            result.error(mod_name, "MEMORY.yaml missing 'entries' field")
            continue
        if not isinstance(entries, list):
            result.error(mod_name, "MEMORY.yaml 'entries' is not a list")
            continue

        # Check entry count
        if len(entries) > max_entries:
            result.error(mod_name,
                f"MEMORY.yaml has {len(entries)} entries (max {max_entries})")

        # Check total token budget (derived from max_entries * max_content_chars)
        max_total_chars = max_entries * max_content_chars
        total_chars = 0
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                result.error(mod_name, f"MEMORY.yaml entry {i} is not a mapping")
                continue

            # Validate entry type
            entry_type = entry.get('type')
            if entry_type and str(entry_type) not in valid_types:
                result.warning(mod_name,
                    f"MEMORY.yaml entry {i} type '{entry_type}' "
                    f"not in {valid_types}")

            # Validate content exists and length
            content = entry.get('content')
            if not content:
                result.warning(mod_name,
                    f"MEMORY.yaml entry {i} has no 'content' field")
                continue

            content_str = str(content)
            total_chars += len(content_str)

            if len(content_str) > max_content_chars:
                result.warning(mod_name,
                    f"MEMORY.yaml entry {i} content is {len(content_str)} chars "
                    f"(max {max_content_chars})")

            # Check single-line
            if '\n' in content_str:
                result.warning(mod_name,
                    f"MEMORY.yaml entry {i} content is multi-line (must be single-line)")

        # Total budget check (derived from conventions)
        if total_chars > max_total_chars:
            max_total_tokens = max_total_chars // 4
            result.error(mod_name,
                f"MEMORY.yaml total content is {total_chars} chars "
                f"(~{total_chars // 4} tokens, max ~{max_total_tokens} tokens)")


# ---------------------------------------------------------------------------
# Check 9: Module granularity (3-7 interfaces)
# ---------------------------------------------------------------------------

def check_granularity(contracts, conventions, result):
    """Verify each module has an appropriate number of interfaces."""
    print("── Check 9: Module granularity ──")

    # Load limits from conventions, with defaults
    gran = {}
    if conventions and isinstance(conventions, dict):
        gran = conventions.get('granularity', {})
        if not isinstance(gran, dict):
            gran = {}

    min_ifaces = gran.get('min_interfaces', 3)
    max_ifaces = gran.get('max_interfaces', 7)
    split_threshold = gran.get('split_threshold', 12)

    for mod_name, contract in contracts.items():
        provides = contract.get('provides')
        if not provides or not isinstance(provides, list):
            # Already caught by check_contract_structure
            continue

        count = len(provides)
        status = contract.get('status', '')

        # Too many interfaces — likely needs splitting
        if count > split_threshold:
            result.error(mod_name,
                f"has {count} interfaces (split threshold is {split_threshold}) "
                f"— likely two or more modules combined")
        elif count > max_ifaces:
            result.warning(mod_name,
                f"has {count} interfaces (recommended max {max_ifaces}) "
                f"— consider splitting")

        # Too few interfaces — skip for draft modules (still being built)
        if count < min_ifaces and str(status) != 'draft':
            result.warning(mod_name,
                f"has {count} interfaces (recommended min {min_ifaces}) "
                f"— may be split too aggressively")


# ---------------------------------------------------------------------------
# Check 10: TESTS.yaml coverage and validity
# ---------------------------------------------------------------------------

def check_test_files(root, contracts, result, module_paths=None):
    """Verify each module has TESTS.yaml with coverage for all interfaces."""
    print("── Check 10: TESTS.yaml coverage ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    for mod_name, contract in contracts.items():
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        test_file = mod_dir / 'TESTS.yaml'
        if not test_file.exists():
            result.warning(mod_name, "Missing TESTS.yaml")
            continue

        tests = parse_yaml_file(str(test_file))
        if not tests:
            result.error(mod_name, "TESTS.yaml exists but is empty or unparseable")
            continue

        # Check module field
        declared = tests.get('module')
        if not declared:
            result.error(mod_name, "TESTS.yaml missing 'module' field")
        elif str(declared) != mod_name:
            result.error(mod_name,
                f"TESTS.yaml declares module='{declared}' but directory is '{mod_name}'")

        # Check tests field
        test_list = tests.get('tests')
        if test_list is None:
            result.error(mod_name, "TESTS.yaml missing 'tests' field")
            continue
        if not isinstance(test_list, list):
            result.error(mod_name, "TESTS.yaml 'tests' is not a list")
            continue

        # Get valid interface IDs from contract
        provides = contract.get('provides')
        valid_ifaces = set()
        if provides and isinstance(provides, list):
            for p in provides:
                if isinstance(p, dict) and p.get('id'):
                    valid_ifaces.add(str(p['id']))

        # Track which interfaces have test coverage
        tested_ifaces = set()
        seen_cases = {}  # {interface: set(case_names)}

        required_test_fields = ['interface', 'case', 'expect']

        for i, t in enumerate(test_list):
            if not isinstance(t, dict):
                result.error(mod_name, f"TESTS.yaml test {i} is not a mapping")
                continue

            # Check required fields
            for field in required_test_fields:
                if field not in t:
                    result.error(mod_name,
                        f"TESTS.yaml test {i} missing required field '{field}'")

            # Check interface references valid contract interface
            iface = t.get('interface')
            if iface:
                iface_str = str(iface)
                if valid_ifaces and iface_str not in valid_ifaces:
                    result.error(mod_name,
                        f"TESTS.yaml test {i} references interface '{iface_str}' "
                        f"not found in CONTRACT provides")
                tested_ifaces.add(iface_str)

                # Check for duplicate case names per interface
                case_name = t.get('case')
                if case_name:
                    case_str = str(case_name)
                    if iface_str not in seen_cases:
                        seen_cases[iface_str] = set()
                    if case_str in seen_cases[iface_str]:
                        result.error(mod_name,
                            f"TESTS.yaml duplicate case '{case_str}' "
                            f"for interface '{iface_str}'")
                    seen_cases[iface_str].add(case_str)

        # Check coverage: every interface should have at least one test
        if valid_ifaces:
            untested = valid_ifaces - tested_ifaces
            for iface in sorted(untested):
                result.warning(mod_name,
                    f"interface '{iface}' has no test cases in TESTS.yaml")


# ---------------------------------------------------------------------------
# Check 11: Context budget per module
# ---------------------------------------------------------------------------

def _content_size(filepath):
    """Return byte count of a YAML file excluding comments and blank lines.
    More accurate than raw file size for token estimation."""
    content = Path(filepath).read_text()
    lines = [l for l in content.split('\n')
             if l.strip() and not l.strip().startswith('#')]
    return sum(len(l) + 1 for l in lines)  # +1 for newline


def check_context_budget(root, contracts, conventions, result, module_paths=None):
    """Verify each module's cold-start context stays within token budget."""
    print("── Check 11: Context budget ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    # Load limits from conventions
    budget = {}
    if conventions and isinstance(conventions, dict):
        budget = conventions.get('context_budget', {})
        if not isinstance(budget, dict):
            budget = {}

    warn_tokens = budget.get('warn_tokens', 2000)
    error_tokens = budget.get('error_tokens', 3000)

    # Scale thresholds for large projects: shared context (MANIFEST, GRAPH)
    # grows ~50 tokens per module, so fixed thresholds penalize large projects.
    total_module_count = len(module_paths)
    per_module_bonus = 50
    if total_module_count > 4:  # only scale above baseline (original scaffold has 2)
        extra = (total_module_count - 4) * per_module_bonus
        warn_tokens += extra
        error_tokens += extra

    # Calculate shared context size (loaded by every agent)
    shared_chars = 0
    for shared_file in ['CONVENTIONS.yaml', 'MANIFEST.yaml', 'GRAPH.yaml']:
        filepath = root / shared_file
        if filepath.exists():
            try:
                shared_chars += _content_size(filepath)
            except OSError:
                pass

    shared_tokens = shared_chars // 4

    for mod_name in contracts:
        module_chars = 0
        file_breakdown = {}
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)

        for mod_file in ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml']:
            filepath = mod_dir / mod_file
            if filepath.exists():
                try:
                    size = _content_size(filepath)
                    module_chars += size
                    file_breakdown[mod_file] = size // 4
                except OSError:
                    pass

        module_tokens = module_chars // 4
        total_tokens = shared_tokens + module_tokens

        if total_tokens > error_tokens:
            # Find the largest file for actionable advice
            largest = max(file_breakdown, key=file_breakdown.get) if file_breakdown else 'unknown'
            result.error(mod_name,
                f"context budget {total_tokens} tokens "
                f"(shared ~{shared_tokens} + module ~{module_tokens}, "
                f"max {error_tokens}) — largest: {largest}")
        elif total_tokens > warn_tokens:
            largest = max(file_breakdown, key=file_breakdown.get) if file_breakdown else 'unknown'
            result.warning(mod_name,
                f"context budget {total_tokens} tokens "
                f"(shared ~{shared_tokens} + module ~{module_tokens}, "
                f"recommended max {warn_tokens}) — largest: {largest}")


# ---------------------------------------------------------------------------
# Check 12: Conventions versioning
# ---------------------------------------------------------------------------

def check_conventions_version(conventions, result):
    """Verify CONVENTIONS.yaml has a version and follows append-only policy."""
    print("── Check 12: Conventions versioning ──")

    if not conventions or not isinstance(conventions, dict):
        result.error('CONVENTIONS', "CONVENTIONS.yaml missing or unparseable")
        return

    version = conventions.get('conventions_version')
    if version is None:
        result.error('CONVENTIONS',
            "CONVENTIONS.yaml missing 'conventions_version' field")
    elif not isinstance(version, int) or version < 1:
        result.error('CONVENTIONS',
            f"conventions_version must be a positive integer, got '{version}'")

    # Check deprecated rules
    deprecated = conventions.get('deprecated_rules', [])
    if isinstance(deprecated, list):
        for entry in deprecated:
            if not isinstance(entry, dict):
                continue
            dep_ver = entry.get('deprecated_in')
            rule = entry.get('rule', '?')
            if isinstance(version, int) and isinstance(dep_ver, int):
                age = version - dep_ver
                if age >= 2:
                    result.warning('CONVENTIONS',
                        f"deprecated rule '{rule[:50]}' (deprecated in v{dep_ver}, "
                        f"current v{version}) — safe to remove")


# ---------------------------------------------------------------------------
# Check 13: Module types (regular vs infrastructure)
# ---------------------------------------------------------------------------

def check_module_types(contracts, conventions, result):
    """Verify module types are valid and infrastructure modules are frozen."""
    print("── Check 13: Module types ──")

    # Load valid types from conventions
    mt = {}
    if conventions and isinstance(conventions, dict):
        mt = conventions.get('module_types', {})
        if not isinstance(mt, dict):
            mt = {}

    valid_types = mt.get('valid', ['regular', 'infrastructure'])

    for mod_name, contract in contracts.items():
        mod_type = contract.get('type')

        # Validate type field if present
        if mod_type and str(mod_type) not in valid_types:
            result.warning(mod_name,
                f"CONTRACT type '{mod_type}' not in {valid_types}")

        # Infrastructure modules must be frozen
        if str(mod_type) == 'infrastructure':
            status = contract.get('status', '')
            if str(status) != 'frozen':
                result.error(mod_name,
                    f"infrastructure module has status='{status}' "
                    f"(must be 'frozen')")


# ---------------------------------------------------------------------------
# Check 14: ASSUMPTIONS.yaml structure
# ---------------------------------------------------------------------------

def check_assumptions(root, contracts, result, module_paths=None):
    """Verify each module's ASSUMPTIONS.yaml is well-structured."""
    print("── Check 14: Assumptions ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    for mod_name in contracts:
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        assumptions_file = mod_dir / 'ASSUMPTIONS.yaml'
        if not assumptions_file.exists():
            result.warning(mod_name, "Missing ASSUMPTIONS.yaml")
            continue

        data = parse_yaml_file(str(assumptions_file))
        if not data:
            result.error(mod_name,
                "ASSUMPTIONS.yaml exists but is empty or unparseable")
            continue

        # Check module field
        declared = data.get('module')
        if not declared:
            result.error(mod_name, "ASSUMPTIONS.yaml missing 'module' field")
        elif str(declared) != mod_name:
            result.error(mod_name,
                f"ASSUMPTIONS.yaml declares module='{declared}' "
                f"but directory is '{mod_name}'")

        # Check assumptions field
        assumptions = data.get('assumptions')
        if assumptions is None:
            result.error(mod_name,
                "ASSUMPTIONS.yaml missing 'assumptions' field")
            continue
        if not isinstance(assumptions, list):
            result.error(mod_name,
                "ASSUMPTIONS.yaml 'assumptions' is not a list")
            continue

        seen_ids = set()
        for i, entry in enumerate(assumptions):
            if not isinstance(entry, dict):
                result.error(mod_name,
                    f"ASSUMPTIONS.yaml entry {i} is not a mapping")
                continue

            # Required fields
            for field in ['id', 'category', 'content']:
                if field not in entry:
                    result.error(mod_name,
                        f"ASSUMPTIONS.yaml entry {i} missing '{field}'")

            # Duplicate ID check
            entry_id = entry.get('id')
            if entry_id:
                entry_id_str = str(entry_id)
                if entry_id_str in seen_ids:
                    result.error(mod_name,
                        f"ASSUMPTIONS.yaml duplicate id '{entry_id_str}'")
                seen_ids.add(entry_id_str)

            # Content length check
            content = entry.get('content')
            if content and len(str(content)) > 200:
                result.warning(mod_name,
                    f"ASSUMPTIONS.yaml entry {i} content is "
                    f"{len(str(content))} chars (keep under 200)")


# ---------------------------------------------------------------------------
# Check 15: CHANGELOG.yaml structure
# ---------------------------------------------------------------------------

def check_changelog(root, contracts, result, module_paths=None):
    """Verify each module has a well-structured CHANGELOG.yaml."""
    print("── Check 15: Changelog ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    for mod_name in contracts:
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        cl_file = mod_dir / 'CHANGELOG.yaml'
        if not cl_file.exists():
            result.warning(mod_name, "Missing CHANGELOG.yaml")
            continue

        data = parse_yaml_file(str(cl_file))
        if not data:
            result.error(mod_name,
                "CHANGELOG.yaml exists but is empty or unparseable")
            continue

        # Check module field
        declared = data.get('module')
        if not declared:
            result.error(mod_name, "CHANGELOG.yaml missing 'module' field")
        elif str(declared) != mod_name:
            result.error(mod_name,
                f"CHANGELOG.yaml declares module='{declared}' "
                f"but directory is '{mod_name}'")

        # Check changes field
        changes = data.get('changes')
        if changes is None:
            result.error(mod_name, "CHANGELOG.yaml missing 'changes' field")
        elif not isinstance(changes, list):
            result.error(mod_name, "CHANGELOG.yaml 'changes' is not a list")


# ---------------------------------------------------------------------------
# Check 16: Replacement readiness (all module files present)
# ---------------------------------------------------------------------------

def check_replacement_ready(root, contracts, result, module_paths=None):
    """Verify each module has all files needed for a fresh agent to take over."""
    print("── Check 16: Replacement readiness ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    required_files = [
        'CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml',
        'CHANGELOG.yaml', 'TESTS.yaml', 'ASSUMPTIONS.yaml'
    ]

    for mod_name, contract in contracts.items():
        status = contract.get('status', '')
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        missing = []
        for filename in required_files:
            filepath = mod_dir / filename
            if not filepath.exists():
                missing.append(filename)

        if missing and str(status) != 'draft':
            result.warning(mod_name,
                f"not replacement-ready: missing {missing} "
                f"(a fresh agent cannot fully take over)")


# ---------------------------------------------------------------------------
# Check 17: BUS validation (deltas and requests)
# ---------------------------------------------------------------------------

def check_bus(root, all_contracts, result):
    """Verify BUS/deltas and BUS/requests files are well-structured."""
    print("── Check 17: BUS validation ──")

    valid_delta_types = ['interface_added', 'interface_modified', 'interface_removed']
    valid_action_required = ['none', 'acknowledge', 'migrate', 'urgent']
    valid_request_statuses = ['open', 'acknowledged', 'resolved', 'rejected']
    valid_priorities = ['low', 'medium', 'high', 'critical']

    module_names = set(all_contracts.keys())

    # --- Validate deltas ---
    deltas_dir = root / 'BUS' / 'deltas'
    if deltas_dir.exists():
        for delta_file in sorted(deltas_dir.iterdir()):
            if delta_file.name.startswith('.') or delta_file.is_dir():
                continue
            if not delta_file.name.endswith('.yaml'):
                continue

            fname = delta_file.name
            data = parse_yaml_file(str(delta_file))
            if not data:
                result.error('BUS/deltas',
                    f"{fname} is empty or unparseable")
                continue

            # Required fields
            for field in ['source', 'timestamp', 'type']:
                if field not in data:
                    result.error('BUS/deltas',
                        f"{fname} missing required field '{field}'")

            # Source references real module
            source = data.get('source')
            if source and module_names and str(source) not in module_names:
                result.error('BUS/deltas',
                    f"{fname} source '{source}' is not a known module")

            # Valid type
            delta_type = data.get('type')
            if delta_type and str(delta_type) not in valid_delta_types:
                result.error('BUS/deltas',
                    f"{fname} type '{delta_type}' not in {valid_delta_types}")

            # Impact validation
            impact = data.get('impact')
            if impact and isinstance(impact, dict):
                action = impact.get('action_required')
                if action and str(action) not in valid_action_required:
                    result.warning('BUS/deltas',
                        f"{fname} action_required '{action}' "
                        f"not in {valid_action_required}")

                affected = impact.get('consumers_affected')
                if affected and isinstance(affected, list) and module_names:
                    for consumer in affected:
                        if str(consumer) not in module_names:
                            result.warning('BUS/deltas',
                                f"{fname} consumers_affected references "
                                f"unknown module '{consumer}'")

    # --- Validate requests ---
    requests_dir = root / 'BUS' / 'requests'
    seen_request_ids = set()

    if requests_dir.exists():
        for req_file in sorted(requests_dir.iterdir()):
            if req_file.name.startswith('.') or req_file.is_dir():
                continue
            if not req_file.name.endswith('.yaml'):
                continue

            fname = req_file.name
            data = parse_yaml_file(str(req_file))
            if not data:
                result.error('BUS/requests',
                    f"{fname} is empty or unparseable")
                continue

            # Required fields
            for field in ['id', 'from', 'to', 'status', 'request']:
                if field not in data:
                    result.error('BUS/requests',
                        f"{fname} missing required field '{field}'")

            # Duplicate ID
            req_id = data.get('id')
            if req_id:
                req_id_str = str(req_id)
                if req_id_str in seen_request_ids:
                    result.error('BUS/requests',
                        f"{fname} duplicate request id '{req_id_str}'")
                seen_request_ids.add(req_id_str)

            # From/to reference real modules
            from_mod = data.get('from')
            if from_mod and module_names and str(from_mod) not in module_names:
                result.warning('BUS/requests',
                    f"{fname} 'from' module '{from_mod}' is not known")
            to_mod = data.get('to')
            if to_mod and module_names and str(to_mod) not in module_names:
                result.warning('BUS/requests',
                    f"{fname} 'to' module '{to_mod}' is not known")

            # Valid status
            req_status = data.get('status')
            if req_status and str(req_status) not in valid_request_statuses:
                result.error('BUS/requests',
                    f"{fname} status '{req_status}' "
                    f"not in {valid_request_statuses}")

            # Valid priority
            priority = data.get('priority')
            if priority and str(priority) not in valid_priorities:
                result.warning('BUS/requests',
                    f"{fname} priority '{priority}' "
                    f"not in {valid_priorities}")


# ---------------------------------------------------------------------------
# Check 18: Cross-module assumption compatibility
# ---------------------------------------------------------------------------

def check_assumption_compatibility(root, all_contracts, result, module_paths=None):
    """Flag assumptions in the same category across different modules for review."""
    print("── Check 18: Assumption compatibility ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    # Collect all assumptions by category: {category: [(module, id, content), ...]}
    by_category = {}
    for mod_name in all_contracts:
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        assumptions_file = mod_dir / 'ASSUMPTIONS.yaml'
        if not assumptions_file.exists():
            continue

        data = parse_yaml_file(str(assumptions_file))
        if not data or not isinstance(data.get('assumptions'), list):
            continue

        for entry in data['assumptions']:
            if not isinstance(entry, dict):
                continue
            category = str(entry.get('category', ''))
            content = str(entry.get('content', ''))
            entry_id = str(entry.get('id', ''))
            if category and content:
                if category not in by_category:
                    by_category[category] = []
                by_category[category].append((mod_name, entry_id, content))

    # Flag categories where multiple modules have assumptions
    for category, entries in sorted(by_category.items()):
        modules_in_category = set(mod for mod, _, _ in entries)
        if len(modules_in_category) < 2:
            continue

        # Build summary of which modules assume what
        summaries = []
        for mod, eid, content in entries:
            short = content[:80] + ('...' if len(content) > 80 else '')
            summaries.append(f"{mod}:{eid}")

        result.warning('ASSUMPTIONS',
            f"category '{category}' has assumptions from "
            f"{sorted(modules_in_category)}: {summaries} "
            f"— review for compatibility")


# ---------------------------------------------------------------------------
# Check 19: Manager and orchestrator validation
# ---------------------------------------------------------------------------

def check_managers_orchestrator(root, all_contracts, manifest, result):
    """Verify manager and orchestrator files are consistent with MANIFEST."""
    print("── Check 19: Manager/orchestrator validation ──")

    module_names = set(all_contracts.keys())

    # Get managers from MANIFEST
    manifest_managers = {}
    if manifest and isinstance(manifest, dict):
        mgrs = manifest.get('managers')
        if mgrs and isinstance(mgrs, dict):
            manifest_managers = mgrs

    managers_dir = root / 'managers'

    if managers_dir.exists():
      for mgr_dir in sorted(managers_dir.iterdir()):
        if not mgr_dir.is_dir() or mgr_dir.name.startswith('.'):
            continue

        mgr_name = mgr_dir.name

        # --- SCOPE.yaml ---
        scope_file = mgr_dir / 'SCOPE.yaml'
        if scope_file.exists():
            scope = parse_yaml_file(str(scope_file))
            if scope and isinstance(scope, dict):
                # Manager name matches directory
                declared = scope.get('manager')
                if declared and str(declared) != mgr_name:
                    result.error(mgr_name,
                        f"SCOPE.yaml declares manager='{declared}' "
                        f"but directory is '{mgr_name}'")

                # owns references real modules
                owns = scope.get('owns')
                if owns and isinstance(owns, list):
                    for mod in owns:
                        if module_names and str(mod) not in module_names:
                            result.error(mgr_name,
                                f"SCOPE.yaml owns '{mod}' which is "
                                f"not a known module")

                    # owns matches MANIFEST
                    if mgr_name in manifest_managers:
                        manifest_owns = manifest_managers[mgr_name].get('owns', [])
                        if isinstance(manifest_owns, list):
                            scope_set = set(str(m) for m in owns)
                            manifest_set = set(str(m) for m in manifest_owns)
                            if scope_set != manifest_set:
                                result.error(mgr_name,
                                    f"SCOPE.yaml owns {sorted(scope_set)} "
                                    f"but MANIFEST says {sorted(manifest_set)}")
        else:
            result.warning(mgr_name, "Missing SCOPE.yaml")

        # --- STRATEGY.yaml ---
        strategy_file = mgr_dir / 'STRATEGY.yaml'
        if strategy_file.exists():
            strategy = parse_yaml_file(str(strategy_file))
            if strategy and isinstance(strategy, dict):
                # Manager name
                declared = strategy.get('manager')
                if declared and str(declared) != mgr_name:
                    result.error(mgr_name,
                        f"STRATEGY.yaml declares manager='{declared}' "
                        f"but directory is '{mgr_name}'")

                # Plan modules reference real modules
                plan = strategy.get('plan')
                if plan and isinstance(plan, list):
                    scope_data = parse_yaml_file(str(scope_file)) if scope_file.exists() else {}
                    scope_owns = set()
                    if scope_data and isinstance(scope_data, dict):
                        so = scope_data.get('owns', [])
                        if isinstance(so, list):
                            scope_owns = set(str(m) for m in so)

                    for phase in plan:
                        if not isinstance(phase, dict):
                            continue
                        phase_mods = phase.get('modules')
                        if phase_mods and isinstance(phase_mods, list):
                            for mod in phase_mods:
                                mod_str = str(mod)
                                if module_names and mod_str not in module_names:
                                    result.error(mgr_name,
                                        f"STRATEGY.yaml references module "
                                        f"'{mod_str}' which does not exist")
                                elif scope_owns and mod_str not in scope_owns:
                                    result.warning(mgr_name,
                                        f"STRATEGY.yaml references module "
                                        f"'{mod_str}' outside its scope")

        # --- INBOX.yaml ---
        inbox_file = mgr_dir / 'INBOX.yaml'
        if inbox_file.exists():
            inbox = parse_yaml_file(str(inbox_file))
            if inbox and isinstance(inbox, dict):
                declared = inbox.get('manager')
                if declared and str(declared) != mgr_name:
                    result.error(mgr_name,
                        f"INBOX.yaml declares manager='{declared}' "
                        f"but directory is '{mgr_name}'")

    # --- Orchestrator PLAN.yaml ---
    plan_file = root / 'orchestrator' / 'PLAN.yaml'
    if plan_file.exists():
        plan = parse_yaml_file(str(plan_file))
        if plan and isinstance(plan, dict):
            phases = plan.get('phases')
            if phases and isinstance(phases, list):
                for phase in phases:
                    if not isinstance(phase, dict):
                        continue

                    # Modules reference real modules
                    phase_mods = phase.get('modules')
                    if phase_mods and isinstance(phase_mods, list):
                        for mod in phase_mods:
                            if module_names and str(mod) not in module_names:
                                result.error('orchestrator',
                                    f"PLAN.yaml references module "
                                    f"'{mod}' which does not exist")

                    # Manager references real manager directory
                    mgr = phase.get('manager')
                    if mgr:
                        mgr_path = root / 'managers' / str(mgr)
                        if not mgr_path.is_dir():
                            result.error('orchestrator',
                                f"PLAN.yaml references manager "
                                f"'{mgr}' which does not exist")


# ---------------------------------------------------------------------------
# Check 20: Delta-contract accuracy
# ---------------------------------------------------------------------------

def check_delta_accuracy(root, all_contracts, result):
    """Verify BUS deltas accurately describe what's in the current CONTRACTs."""
    print("── Check 20: Delta-contract accuracy ──")

    deltas_dir = root / 'BUS' / 'deltas'
    if not deltas_dir.exists():
        return

    for delta_file in sorted(deltas_dir.iterdir()):
        if delta_file.name.startswith('.') or delta_file.is_dir():
            continue
        if not delta_file.name.endswith('.yaml'):
            continue

        fname = delta_file.name
        delta = parse_yaml_file(str(delta_file))
        if not delta or not isinstance(delta, dict):
            continue

        source = delta.get('source')
        if not source or str(source) not in all_contracts:
            continue  # Already flagged by check_bus

        source_str = str(source)
        contract = all_contracts[source_str]
        delta_type = str(delta.get('type', ''))

        # Get current interface IDs from contract
        provides = contract.get('provides', [])
        current_ifaces = set()
        if isinstance(provides, list):
            for p in provides:
                if isinstance(p, dict) and p.get('id'):
                    current_ifaces.add(str(p['id']))

        # Get the change section
        change = delta.get('change', {})
        if not isinstance(change, dict):
            continue

        if delta_type == 'interface_added':
            added = change.get('added', {})
            if isinstance(added, dict):
                added_id = added.get('id')
                if added_id and str(added_id) not in current_ifaces:
                    result.warning('BUS/deltas',
                        f"{fname} claims interface_added '{added_id}' "
                        f"but it's not in {source_str}'s current CONTRACT")

        elif delta_type == 'interface_removed':
            removed = change.get('removed', {})
            if isinstance(removed, dict):
                removed_id = removed.get('id')
                if removed_id and str(removed_id) in current_ifaces:
                    result.warning('BUS/deltas',
                        f"{fname} claims interface_removed '{removed_id}' "
                        f"but it still exists in {source_str}'s current CONTRACT")

        elif delta_type == 'interface_modified':
            modified = change.get('modified', {})
            if isinstance(modified, dict):
                modified_id = modified.get('id')
                if modified_id and str(modified_id) not in current_ifaces:
                    result.warning('BUS/deltas',
                        f"{fname} claims interface_modified '{modified_id}' "
                        f"but it's not in {source_str}'s current CONTRACT")


# ---------------------------------------------------------------------------
# Check 21: Contract version pinning
# ---------------------------------------------------------------------------

def check_version_pinning(contracts, all_contracts, result):
    """Verify consumes entries pin contract_version and it matches provider."""
    print("── Check 21: Version pinning ──")

    for mod_name, contract in contracts.items():
        raw_consumes = contract.get('consumes', [])
        if not isinstance(raw_consumes, list):
            continue

        for i, entry in enumerate(raw_consumes):
            if not isinstance(entry, dict):
                continue

            dep_module = entry.get('module')
            if not dep_module:
                continue
            dep_str = str(dep_module)

            pinned = entry.get('contract_version')
            if pinned is None:
                result.warning(mod_name,
                    f"consumes '{dep_str}' without contract_version pin "
                    f"— add contract_version to track provider changes")
                continue

            # Check pinned version against provider's current version
            if dep_str in all_contracts:
                provider = all_contracts[dep_str]
                current_version = provider.get('version')
                if current_version is not None:
                    try:
                        pinned_int = int(pinned)
                        current_int = int(current_version)
                        if pinned_int != current_int:
                            result.warning(mod_name,
                                f"consumes '{dep_str}' pinned to v{pinned_int} "
                                f"but provider is at v{current_int} "
                                f"— review for breaking changes")
                    except (ValueError, TypeError):
                        pass


# ---------------------------------------------------------------------------
# Check 22: Stale BUS requests
# ---------------------------------------------------------------------------

def check_stale_requests(root, result, stale_days=7):
    """Warn on open BUS requests older than stale_days."""
    print("── Check 22: Stale requests ──")

    requests_dir = root / 'BUS' / 'requests'
    if not requests_dir.exists():
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=stale_days)

    for req_file in sorted(requests_dir.iterdir()):
        if req_file.name.startswith('.') or req_file.is_dir():
            continue
        if not req_file.name.endswith('.yaml'):
            continue

        data = parse_yaml_file(str(req_file))
        if not data or not isinstance(data, dict):
            continue

        status = str(data.get('status', ''))
        if status not in ('open', 'acknowledged'):
            continue

        created = data.get('created')
        if not created:
            continue

        try:
            clean = str(created).strip().replace('Z', '+00:00')
            created_dt = datetime.fromisoformat(clean)
            if created_dt < cutoff:
                age_days = (now - created_dt).days
                req_id = data.get('id', req_file.name)
                result.warning('BUS/requests',
                    f"{req_id} has been {status} for {age_days} days "
                    f"(created {created}) — resolve or escalate")
        except (ValueError, AttributeError):
            pass


# ---------------------------------------------------------------------------
# Check 23: Schema validation
# ---------------------------------------------------------------------------

# Allowed keys per file type. Keys not in this list trigger a warning.
# Types: 'str', 'int', 'float', 'list', 'dict', 'bool', 'any'
_SCHEMAS = {
    'CONTRACT': {
        'module':               {'required': True,  'type': 'str'},
        'version':              {'required': True,  'type': 'int'},
        'status':               {'required': True,  'type': 'str'},
        'type':                 {'required': False, 'type': 'str'},
        'purpose':              {'required': True,  'type': 'str'},
        'provides':             {'required': True,  'type': 'list'},
        'consumes':             {'required': False, 'type': 'list'},
        'constraints':          {'required': False, 'type': 'any'},
        'contract_rules':       {'required': False, 'type': 'dict'},
        'conventions_version':  {'required': False, 'type': 'int'},
    },
    'STATE': {
        'module':               {'required': True,  'type': 'str'},
        'updated':              {'required': False, 'type': 'str'},
        'status':               {'required': True,  'type': 'str'},
        'progress':             {'required': False, 'type': 'any'},
        'current_work':         {'required': False, 'type': 'any'},
        'blockers':             {'required': False, 'type': 'list'},
        'warnings':             {'required': False, 'type': 'list'},
        'health_notes':         {'required': False, 'type': 'any'},
        'last_contract_change': {'required': False, 'type': 'any'},
        'tests_passing':        {'required': False, 'type': 'any'},
    },
    'MEMORY': {
        'module':      {'required': True,  'type': 'str'},
        'entries':     {'required': True,  'type': 'list'},
        'max_entries': {'required': False, 'type': 'int'},
    },
    'TESTS': {
        'module': {'required': True, 'type': 'str'},
        'tests':  {'required': True, 'type': 'list'},
    },
    'ASSUMPTIONS': {
        'module':      {'required': True, 'type': 'str'},
        'assumptions': {'required': True, 'type': 'list'},
    },
    'CHANGELOG': {
        'module':  {'required': True, 'type': 'str'},
        'changes': {'required': True, 'type': 'list'},
    },
}

_TYPE_MAP = {
    'str': str, 'int': int, 'float': (int, float),
    'list': list, 'dict': dict, 'bool': bool,
}


def check_schemas(root, contracts, result, module_paths=None):
    """Validate module files against known schemas — catch misspelled keys and wrong types."""
    print("── Check 23: Schema validation ──")

    if module_paths is None:
        module_paths = discover_modules(root)

    for mod_name in sorted(contracts):
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        for filename, schema in _SCHEMAS.items():
            filepath = mod_dir / f'{filename}.yaml'
            if not filepath.exists():
                continue
            data = parse_yaml_file(str(filepath))
            if not data or not isinstance(data, dict):
                continue

            # Check for unknown keys
            known = set(schema.keys())
            actual = set(k for k in data.keys() if not k.startswith('_'))
            unknown = actual - known
            for key in sorted(unknown):
                result.warning(mod_name,
                    f"{filename}.yaml has unknown key '{key}'"
                    f" — expected one of: {', '.join(sorted(known))}")

            # Check types of known keys
            for key, spec in schema.items():
                if key not in data:
                    continue
                val = data[key]
                if val is None:
                    continue
                expected_type = spec['type']
                if expected_type == 'any':
                    continue
                py_type = _TYPE_MAP.get(expected_type)
                if py_type and not isinstance(val, py_type):
                    result.warning(mod_name,
                        f"{filename}.yaml key '{key}' should be"
                        f" {expected_type}, got {type(val).__name__}")


def check_gateway(root, contracts, all_contracts, module_paths, result):
    """Check 24: Gateway validation for domain scaling."""
    print("── Check 24: Gateway validation ──")

    domains = discover_domains(root)
    if not domains:
        return  # No domains, nothing to check

    # Build domain lookup: {module_name: domain_name}
    domain_lookup = {}
    for dname, info in domains.items():
        for mod in info['modules']:
            domain_lookup[mod] = dname

    # Build exports lookup: {domain: {module: set(interfaces)}}
    exports = {}
    for dname, info in domains.items():
        if info['gateway'] is None:
            continue
        gw = parse_yaml_file(str(info['gateway']))
        if not gw or not isinstance(gw, dict):
            result.error(f"domain/{dname}", "GATEWAY.yaml is empty or malformed")
            continue
        exports[dname] = {}
        for entry in gw.get('exports', []) or []:
            if isinstance(entry, dict):
                mod = entry.get('module', '')
                ifaces = entry.get('interfaces', [])
                exports[dname][mod] = set(ifaces) if isinstance(ifaces, list) else set()

    # Validate cross-domain consumes (only for FILTERED contracts)
    for mod_name, contract in contracts.items():
        mod_domain = domain_lookup.get(mod_name)  # None if flat
        for dep in contract.get('consumes', []) or []:
            if not isinstance(dep, dict):
                continue
            dep_module = dep.get('module', '')
            dep_interface = dep.get('interface', '')
            dep_domain = domain_lookup.get(dep_module)

            # Skip if provider is flat (no gateway to enforce)
            if dep_domain is None:
                continue
            # Skip if same domain (intra-domain, no gateway needed)
            if mod_domain == dep_domain:
                continue

            # Cross-domain OR flat→domain: check gateway
            if dep_domain not in exports:
                result.error(mod_name,
                    f"consumes {dep_module}.{dep_interface} from domain "
                    f"'{dep_domain}' but '{dep_domain}' has no GATEWAY.yaml")
            elif dep_module not in exports[dep_domain]:
                result.error(mod_name,
                    f"consumes {dep_module}.{dep_interface} but "
                    f"'{dep_module}' is not exported in {dep_domain}/GATEWAY.yaml")
            elif dep_interface not in exports[dep_domain].get(dep_module, set()):
                result.error(mod_name,
                    f"consumes {dep_module}.{dep_interface} but "
                    f"'{dep_interface}' is not exported in {dep_domain}/GATEWAY.yaml")

    # Validate gateway references
    for dname, dexports in exports.items():
        for mod, ifaces in dexports.items():
            if mod not in all_contracts:
                result.error(f"domain/{dname}",
                    f"GATEWAY.yaml exports '{mod}' but module doesn't exist")
            else:
                provides = {p['id'] for p in all_contracts[mod].get('provides', [])
                           if isinstance(p, dict) and 'id' in p}
                for iface in ifaces:
                    if iface not in provides:
                        result.error(f"domain/{dname}",
                            f"GATEWAY.yaml exports {mod}.{iface} "
                            f"but interface doesn't exist in contract")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='ANMA Contract Linter')
    parser.add_argument('--strict', action='store_true',
                        help='Treat warnings as errors')
    parser.add_argument('--module', action='append', default=None,
                        help='Lint only specific module(s); repeatable')
    parser.add_argument('path', nargs='?', default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = find_project_root(args.path)
    print(f"\nANMA Contract Linter v0.1")
    print(f"Project root: {root}\n")

    result = LintResult()

    # Load everything
    contracts = load_all_contracts(root)
    graph = load_graph(root)
    conventions = load_conventions(root)
    manifest = load_manifest(root)

    if not contracts:
        print("  ✗ No contracts found in modules/ or domains/ directory.\n")
        sys.exit(1)

    try:
        module_paths = discover_modules(root)
    except ValueError as e:
        print(f"  ✗ {e}")
        sys.exit(1)

    # all_contracts is the full set (needed for cross-reference lookups).
    # contracts is the set being linted (may be filtered by --module).
    all_contracts = contracts

    if args.module:
        filtered = {}
        for mod_name in args.module:
            if mod_name in contracts:
                filtered[mod_name] = contracts[mod_name]
            else:
                print(f"  ✗ Module '{mod_name}' not found.")
        if not filtered:
            print()
            sys.exit(1)
        contracts = filtered

    print(f"Linting {len(contracts)} module(s): {', '.join(contracts.keys())}")
    if len(all_contracts) != len(contracts):
        print(f"({len(all_contracts)} total modules available for cross-reference)")
    print()

    # Run all checks — cross-reference check gets all_contracts for lookups
    check_cross_references(contracts, all_contracts, result)
    check_graph_consistency(contracts, all_contracts, graph, result)
    check_naming_conventions(contracts, conventions, result)
    check_circular_dependencies(all_contracts, result)
    check_contract_structure(contracts, result)
    check_manifest_consistency(all_contracts, manifest, result)
    check_state_files(root, contracts, result, module_paths=module_paths)
    check_memory_files(root, contracts, conventions, result, module_paths=module_paths)
    check_granularity(contracts, conventions, result)
    check_test_files(root, contracts, result, module_paths=module_paths)
    check_context_budget(root, contracts, conventions, result, module_paths=module_paths)
    check_conventions_version(conventions, result)
    check_module_types(contracts, conventions, result)
    check_assumptions(root, contracts, result, module_paths=module_paths)
    check_changelog(root, contracts, result, module_paths=module_paths)
    check_replacement_ready(root, contracts, result, module_paths=module_paths)
    check_bus(root, all_contracts, result)
    check_assumption_compatibility(root, all_contracts, result, module_paths=module_paths)
    check_managers_orchestrator(root, all_contracts, manifest, result)
    check_delta_accuracy(root, all_contracts, result)
    check_version_pinning(contracts, all_contracts, result)
    check_stale_requests(root, result)
    check_schemas(root, contracts, result, module_paths=module_paths)
    check_gateway(root, contracts, all_contracts, module_paths, result)

    # --- Plugin checks from checks/ directory ---
    checks_dir = root / 'checks'
    if checks_dir.is_dir():
        plugin_files = sorted(checks_dir.glob('check_*.py'))
        for plugin_file in plugin_files:
            plugin_name = plugin_file.stem
            try:
                spec = importlib.util.spec_from_file_location(plugin_name, str(plugin_file))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, 'run'):
                    print(f"── Plugin: {plugin_name} ──")
                    mod.run(root=root, contracts=contracts,
                            all_contracts=all_contracts,
                            conventions=conventions, manifest=manifest,
                            result=result, module_paths=module_paths)
                else:
                    result.warning('plugin',
                        f"{plugin_name}.py missing 'run' function")
            except Exception as e:
                result.error('plugin',
                    f"{plugin_name}.py failed: {e}")

    print("\n── Results ──")
    result.print_report()

    # Log activity
    try:
        from session_log import log_activity
        e, w = len(result.errors), len(result.warnings)
        mods = ', '.join(contracts.keys())
        log_activity(root, f"linted {len(contracts)} module(s): {e} errors, {w} warnings", "lint_contracts.py")
    except Exception:
        pass

    if not result.ok():
        sys.exit(1)
    elif args.strict and result.warnings:
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
