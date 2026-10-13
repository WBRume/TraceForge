"""Autogeneration must see all domain tables in a fresh Python interpreter."""

import subprocess
import sys
from pathlib import Path


def test_alembic_registers_every_declared_domain_table():
    script = """
import ast
import runpy
from contextlib import nullcontext
from pathlib import Path
from alembic import context
from alembic.config import Config

context.config = Config('alembic.ini')
context.is_offline_mode = lambda: True
context.configure = lambda **kwargs: None
context.begin_transaction = nullcontext
context.run_migrations = lambda: None
namespace = runpy.run_path('alembic/env.py')
registered = set(namespace['target_metadata'].tables)
declared = set()
for path in Path('app/domains').rglob('*.py'):
    if path.stem != 'models' and 'models' not in path.parts:
        continue
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == '__tablename__' for target in node.targets
        ):
            declared.add(ast.literal_eval(node.value))
assert declared <= registered, sorted(declared - registered)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
