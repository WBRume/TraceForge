"""Server-owned bundle registry. API callers cannot register executables/collectors.

A bundle supplies an independently implemented collector and environment probe.
The probe must verify mount/guard/fixture identities; user input is not a receipt.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from app.domains.diagnosis_playbook.contracts import PlaybookError


@dataclass(frozen=True)
class RunnerBundle:
    uri: str
    digest: str
    executable: str
    root: str
    # Complete command templates, not just a prefix allow-list.
    commands: tuple[tuple[str, ...], ...]
    probe: Callable
    collect: Callable
    # Server-owned per-execution secret binding; never serialized in receipts.
    child_environment: Callable | None = None
    stage_contracts: tuple[tuple[str, str], ...] = ()
    cleanup: Callable | None = None


def validate_stage(bundle, stage):
    from app.domains.diagnosis_playbook.contracts import digest
    if tuple(stage["verification"]["command"]["argv"]) not in bundle.commands:
        raise PlaybookError("COMMAND_NOT_IN_BUNDLE")
    if bundle.stage_contracts:
        contract = digest({"verification": stage["verification"], "oracle": stage.get("oracle")})
        if (stage["phase"], contract) not in bundle.stage_contracts:
            raise PlaybookError("BUNDLE_VERIFICATION_CONTRACT_CHANGED")


class BundleRegistry:
    def __init__(self):
        self._bundles = {}

    def register(self, bundle: RunnerBundle):
        executable, root = Path(bundle.executable), Path(bundle.root)
        if not executable.is_absolute() or not executable.is_file() or not root.is_absolute() or not root.is_dir():
            raise PlaybookError("BUNDLE_PATH_INVALID")
        existing = self._bundles.get(bundle.uri)
        if existing is not None and existing != bundle:
            raise PlaybookError("BUNDLE_IMMUTABLE")
        self._bundles[bundle.uri] = bundle

    def resolve(self, uri):
        bundle = self._bundles.get(uri)
        if bundle is None:
            raise PlaybookError("BUNDLE_NOT_INSTALLED", status=409, missing_facts=[uri])
        return bundle


registry = BundleRegistry()


def load_configured_bundles(factories):
    """Load reviewed server extensions during startup, before accepting runs.

    The factory receives no task/user data. All factory paths originate in the
    deployment settings; a YAML document can reference only registered URIs.
    """
    import importlib
    import re
    for reference in factories:
        if not isinstance(reference, str) or not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*:[a-zA-Z_]\w*", reference):
            raise PlaybookError("INVALID_BUNDLE_FACTORY")
        module_name, factory_name = reference.split(":")
        bundles = getattr(importlib.import_module(module_name), factory_name)()
        if isinstance(bundles, RunnerBundle):
            bundles = [bundles]
        for bundle in bundles:
            if not isinstance(bundle, RunnerBundle):
                raise PlaybookError("INVALID_BUNDLE_FACTORY_RESULT")
            registry.register(bundle)
