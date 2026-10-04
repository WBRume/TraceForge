"""Enforce the dependency directions introduced by the domain refactor."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
BOUNDARIES = (
    "domains/task/services/task_records",
    "domains/task/services/provisioning",
    "domains/task/services/task_workspace",
    "domains/task/services/conversation",
    "domains/skill/services/catalog",
    "domains/skill/services/packages",
    "domains/skill/services/reviews",
    "domains/skill/services/runtime",
    "domains/asset/services/review",
)
REMOVED = (
    "app.domains.task.services.task_service",
    "app.domains.skill.services.skill_service",
    "app.domains.asset.routers.asset",
)


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def test_callers_cannot_import_removed_aggregate_services():
    violations = []
    for path in APP.rglob("*.py"):
        for dependency in imports(path):
            if any(dependency == name or dependency.startswith(name + ".") for name in REMOVED):
                violations.append((str(path.relative_to(APP)), dependency))
    assert not violations, violations


def test_domain_services_have_no_transport_dependency_or_internal_cycles():
    modules = {}
    for boundary in BOUNDARIES:
        for path in (APP / boundary).glob("*.py"):
            name = "app." + ".".join(path.relative_to(APP).with_suffix("").parts)
            modules[name] = path
    edges = {name: set(imports(path)) & modules.keys() for name, path in modules.items()}
    for name, path in modules.items():
        for dependency in imports(path):
            assert not dependency.startswith(("fastapi", "app.dependencies")), (name, dependency)
            assert ".routers" not in dependency, (name, dependency)
    visited = set()

    def visit(name, stack):
        assert name not in stack, " -> ".join([*stack, name])
        if name in visited:
            return
        for dependency in edges[name]:
            visit(dependency, [*stack, name])
        visited.add(name)

    for name in modules:
        visit(name, [])


def test_skill_selection_queries_do_not_own_materialization():
    dependencies = set(imports(APP / "domains/skill/services/runtime/bindings.py"))
    assert "app.domains.skill.services.runtime.materialization" not in dependencies
    assert "app.domains.skill.services.runtime.configuration" not in dependencies
