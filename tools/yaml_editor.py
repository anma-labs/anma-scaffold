"""ANMA YAML Editor.

Centralized read-modify-write for ANMA's structured YAML files.
Replaces fragile regex-based editing with parse → modify → serialize.

Handles the specific formatting conventions:
- MANIFEST: flow mappings for modules/managers, aligned columns
- GRAPH: block style with flow lists for consumes/consumed_by
- SCOPE: block style with flow list for owns

Zero external dependencies — uses lint_contracts.parse_yaml_file for reading.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file


# ---------------------------------------------------------------------------
# MANIFEST.yaml
# ---------------------------------------------------------------------------

def read_manifest(root):
    """Read and parse MANIFEST.yaml."""
    path = Path(root) / 'MANIFEST.yaml'
    return parse_yaml_file(str(path)) or {}


def write_manifest(root, data):
    """Write MANIFEST.yaml in ANMA format."""
    path = Path(root) / 'MANIFEST.yaml'

    lines = [
        f"project: {data.get('project', 'my-platform')}",
        f"version: {data.get('version', '0.1.0')}",
        f"updated: {data.get('updated', _now())}",
        "",
        "modules:",
    ]

    modules = data.get('modules', {})
    if isinstance(modules, dict) and modules:
        # Calculate alignment width
        max_name = max(len(n) for n in modules) if modules else 0
        width = max(max_name + 2, 19)  # minimum 19 for readability
        for name, entry in modules.items():
            if isinstance(entry, dict):
                parts = []
                for k, v in entry.items():
                    parts.append(f"{k}: {v}")
                flow = '{ ' + ', '.join(parts) + ' }'
                padding = ' ' * max(1, width - len(name))
                lines.append(f"  {name}:{padding}{flow}")
            else:
                lines.append(f"  {name}: {entry}")
    else:
        lines[-1] = "modules: {}"

    lines.append("")
    lines.append("managers:")

    managers = data.get('managers', {})
    if isinstance(managers, dict) and managers:
        for name, entry in managers.items():
            if isinstance(entry, dict):
                owns = entry.get('owns', [])
                if isinstance(owns, list):
                    owns_str = ', '.join(str(o) for o in owns)
                else:
                    owns_str = str(owns)
                lines.append(f"  {name}: {{ owns: [{owns_str}] }}")
            else:
                lines.append(f"  {name}: {entry}")
    else:
        lines[-1] = "managers: {}"

    lines.append("")
    lines.append(f"orchestrator: {data.get('orchestrator', 'active')}")
    lines.append("")

    path.write_text('\n'.join(lines))


def manifest_add_module(root, name, status='draft', owner=None, manager=None, domain=None):
    """Add a module to MANIFEST.yaml."""
    data = read_manifest(root)
    modules = data.get('modules', {})
    if not isinstance(modules, dict):
        modules = {}

    if name in modules:
        return False, f"Module '{name}' already in MANIFEST"

    owner = owner or f"agent-{name.replace('-', '')}"
    entry = {'status': status, 'owner': owner}
    if manager:
        entry['manager'] = manager
    if domain:
        entry['domain'] = domain
    modules[name] = entry
    data['modules'] = modules

    # Update manager owns if specified
    if manager:
        managers = data.get('managers', {})
        if isinstance(managers, dict) and manager in managers:
            mgr_entry = managers[manager]
            if isinstance(mgr_entry, dict):
                owns = mgr_entry.get('owns', [])
                if isinstance(owns, list) and name not in owns:
                    owns.append(name)
                    mgr_entry['owns'] = owns

    data['updated'] = _now()
    write_manifest(root, data)
    return True, None


def manifest_remove_module(root, name):
    """Remove a module from MANIFEST.yaml and any manager owns lists."""
    data = read_manifest(root)
    modules = data.get('modules', {})
    if isinstance(modules, dict) and name in modules:
        del modules[name]
        data['modules'] = modules

    # Remove from all manager owns lists
    managers = data.get('managers', {})
    if isinstance(managers, dict):
        for mgr_entry in managers.values():
            if isinstance(mgr_entry, dict):
                owns = mgr_entry.get('owns', [])
                if isinstance(owns, list) and name in owns:
                    owns.remove(name)

    data['updated'] = _now()
    write_manifest(root, data)


def manifest_add_manager(root, name, owns=None):
    """Add a manager to MANIFEST.yaml."""
    data = read_manifest(root)
    managers = data.get('managers', {})
    if not isinstance(managers, dict):
        managers = {}

    if name in managers:
        return False, f"Manager '{name}' already in MANIFEST"

    managers[name] = {'owns': owns or []}
    data['managers'] = managers

    # Update owned modules' manager field
    if owns:
        modules = data.get('modules', {})
        if isinstance(modules, dict):
            for mod_name in owns:
                if mod_name in modules and isinstance(modules[mod_name], dict):
                    modules[mod_name]['manager'] = name

    data['updated'] = _now()
    write_manifest(root, data)
    return True, None


def manifest_rename_project(root, new_name):
    """Rename the project in MANIFEST.yaml."""
    data = read_manifest(root)
    old_name = data.get('project', '')
    data['project'] = new_name
    data['updated'] = _now()
    write_manifest(root, data)
    return old_name


# ---------------------------------------------------------------------------
# GRAPH.yaml
# ---------------------------------------------------------------------------

def read_graph(root):
    """Read and parse GRAPH.yaml."""
    path = Path(root) / 'GRAPH.yaml'
    return parse_yaml_file(str(path)) or {}


def write_graph(root, data):
    """Write GRAPH.yaml in ANMA format."""
    path = Path(root) / 'GRAPH.yaml'

    lines = [
        "# Auto-generated from CONTRACT consumes fields.",
        "# Regenerate with: python3 gen_graph.py",
        f"version: {data.get('version', 1)}",
        f"updated: {data.get('updated', _now())}",
        "",
        "modules:",
    ]

    modules = data.get('modules', {})
    if isinstance(modules, dict):
        for name in sorted(modules.keys()):
            entry = modules[name]
            if not isinstance(entry, dict):
                entry = {}
            consumes = entry.get('consumes', [])
            consumed_by = entry.get('consumed_by', [])
            if not isinstance(consumes, list):
                consumes = []
            if not isinstance(consumed_by, list):
                consumed_by = []
            c_str = '[' + ', '.join(str(c) for c in consumes) + ']' if consumes else '[]'
            cb_str = '[' + ', '.join(str(c) for c in consumed_by) + ']' if consumed_by else '[]'
            lines.append(f"  {name}:")
            lines.append(f"    consumes: {c_str}")
            lines.append(f"    consumed_by: {cb_str}")

    lines.append("")
    path.write_text('\n'.join(lines))


def graph_add_module(root, name, consumes=None):
    """Add a module to GRAPH.yaml and update consumed_by for dependencies."""
    data = read_graph(root)
    modules = data.get('modules', {})
    if not isinstance(modules, dict):
        modules = {}

    consumes = consumes or []
    modules[name] = {'consumes': list(consumes), 'consumed_by': []}

    # Update consumed_by for each dependency
    for dep in consumes:
        if dep in modules:
            cb = modules[dep].get('consumed_by', [])
            if isinstance(cb, list) and name not in cb:
                cb.append(name)
                modules[dep]['consumed_by'] = sorted(cb)

    data['modules'] = modules
    data['updated'] = _now()
    write_graph(root, data)


def graph_remove_module(root, name):
    """Remove a module from GRAPH.yaml and all consumed_by references."""
    data = read_graph(root)
    modules = data.get('modules', {})
    if not isinstance(modules, dict):
        return

    # Remove the module entry
    modules.pop(name, None)

    # Remove from all consumed_by and consumes lists
    for mod_data in modules.values():
        if isinstance(mod_data, dict):
            cb = mod_data.get('consumed_by', [])
            if isinstance(cb, list) and name in cb:
                cb.remove(name)
            cs = mod_data.get('consumes', [])
            if isinstance(cs, list) and name in cs:
                cs.remove(name)

    data['modules'] = modules
    data['updated'] = _now()
    write_graph(root, data)


# ---------------------------------------------------------------------------
# SCOPE.yaml (per-manager)
# ---------------------------------------------------------------------------

def read_scope(root, manager):
    """Read a manager's SCOPE.yaml."""
    path = Path(root) / 'managers' / manager / 'SCOPE.yaml'
    if not path.exists():
        return None
    return parse_yaml_file(str(path)) or {}


def scope_add_module(root, manager, module_name):
    """Add a module to a manager's SCOPE.yaml owns list."""
    path = Path(root) / 'managers' / manager / 'SCOPE.yaml'
    if not path.exists():
        return False

    content = path.read_text()
    data = parse_yaml_file(str(path)) or {}
    owns = data.get('owns', [])
    if not isinstance(owns, list):
        owns = []
    if module_name in owns:
        return True  # already there

    owns.append(module_name)

    # Rewrite owns line in-place (preserving rest of file)
    new_owns_str = ', '.join(str(o) for o in owns)
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('owns:'):
            lines[i] = f"owns: [{new_owns_str}]"
            break
    path.write_text('\n'.join(lines))
    return True


def scope_remove_module(root, manager, module_name):
    """Remove a module from a manager's SCOPE.yaml owns list."""
    path = Path(root) / 'managers' / manager / 'SCOPE.yaml'
    if not path.exists():
        return False

    content = path.read_text()
    if module_name not in content:
        return True

    data = parse_yaml_file(str(path)) or {}
    owns = data.get('owns', [])
    if isinstance(owns, list) and module_name in owns:
        owns.remove(module_name)

    new_owns_str = ', '.join(str(o) for o in owns)
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('owns:'):
            lines[i] = f"owns: [{new_owns_str}]"
            break
    path.write_text('\n'.join(lines))
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
