"""Catalog changes coordinate database state and package directory ownership."""

from pathlib import Path

import pytest

from app.domains.skill.models.skill import SddSkill, SkillDimension
from app.domains.skill.services.catalog.commands import update_skill_metadata
from app.domains.skill.services.packages import storage as storage_service
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session


def seed_skill(db, storage_root):
    user, _workspace, _task = _seed_workspace(db)
    skill = SddSkill(
        id="catalog-skill",
        name="Before",
        dimension=SkillDimension.GLOBAL,
        creator_id=user.id,
        last_modifier_id=user.id,
        package_path=storage_service.package_relative_path("catalog-skill", SkillDimension.GLOBAL, None, "Before"),
        entry_file_path="SKILL.md",
        manifest_path="",
    )
    db.add(skill)
    db.commit()
    directory = Path(storage_service.package_abs_path(skill))
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    return user, skill, directory


def rename(db, user, skill, **overrides):
    return update_skill_metadata(
        db,
        user,
        skill,
        **{
            "context_workspace_id": "ws-1",
            "name": "After",
            "description": None,
            "dimension_value": None,
            "workspace_id": None,
            "entry_file_path": None,
            "manifest_path": None,
            **overrides,
        },
    )


def test_invalid_entry_is_rejected_before_moving_package(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service.settings, "SKILLS_STORAGE_ROOT", str(tmp_path))
    engine, factory = _build_db()
    try:
        with _session(factory) as db:
            user, skill, directory = seed_skill(db, tmp_path)
            old_path = skill.package_path
            with pytest.raises(storage_service.SkillStorageError):
                rename(db, user, skill, entry_file_path="../escape.md")
            assert skill.package_path == old_path
            assert (directory / "SKILL.md").is_file()
            assert skill.name == "Before"
    finally:
        engine.dispose()


def test_commit_failure_restores_package_and_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service.settings, "SKILLS_STORAGE_ROOT", str(tmp_path))
    engine, factory = _build_db()
    try:
        with _session(factory) as db:
            user, skill, directory = seed_skill(db, tmp_path)
            old_path = skill.package_path
            target = Path(
                storage_service.package_abs_path_from_relative(
                    storage_service.package_relative_path(skill.id, SkillDimension.GLOBAL, None, "After")
                )
            )

            def fail_commit():
                raise RuntimeError("database unavailable")

            monkeypatch.setattr(db, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="database unavailable"):
                rename(db, user, skill)
            assert (directory / "SKILL.md").read_text(encoding="utf-8") == "# Skill\n"
            assert not target.exists()
            assert skill.package_path == old_path
            assert skill.name == "Before"
    finally:
        engine.dispose()


def test_successful_rename_moves_package_and_persists_new_owner_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service.settings, "SKILLS_STORAGE_ROOT", str(tmp_path))
    engine, factory = _build_db()
    try:
        with _session(factory) as db:
            user, skill, directory = seed_skill(db, tmp_path)
            rename(db, user, skill)
            assert not directory.exists()
            assert Path(storage_service.package_abs_path(skill), "SKILL.md").is_file()
            db.expire_all()
            assert db.get(SddSkill, "catalog-skill").name == "After"
    finally:
        engine.dispose()
