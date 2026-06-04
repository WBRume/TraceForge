import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.models.skill import SddSkill, SkillDimension  # noqa: E402
from app.domains.skill.services import skill_service  # noqa: E402
from app.domains.skill.services.skill import git_service, github_import_service, storage_service  # noqa: E402


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


def _write_bytes(path: str, payload: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as file:
        file.write(payload)


class _FakeDbSession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.rollback_called = False

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def refresh(self, _obj):
        return None

    def rollback(self):
        self.rollback_called = True


class GithubImportFlowTest(unittest.TestCase):
    def test_import_skill_from_github_copies_full_package_and_creates_version_one(self):
        with tempfile.TemporaryDirectory() as temp_root:
            storage_root = os.path.join(temp_root, "skills-storage")
            repo_root = os.path.join(temp_root, "repo")
            source_skill_dir = os.path.join(repo_root, "skills", "demo-skill")

            _write_text(
                os.path.join(source_skill_dir, "SKILL.md"),
                "---\ndescription: imported from frontmatter\n---\n# Demo Skill\n",
            )
            _write_text(os.path.join(source_skill_dir, "scripts", "run.sh"), "echo hello\n")
            binary_payload = b"\x00\x01\x02\x03binary"
            _write_bytes(os.path.join(source_skill_dir, "assets", "icon.bin"), binary_payload)
            _write_text(os.path.join(repo_root, ".git", "HEAD"), "ref: refs/heads/main\n")

            @contextmanager
            def _fake_cloned_public_repo(_repo_url: str, **_kwargs):
                yield repo_root

            db = _FakeDbSession()
            user = SimpleNamespace(id="user-1")
            commit_meta = git_service.CommitMeta(
                commit_sha="abc123",
                parent_commit_sha=None,
                tree_sha="tree123",
                changed_files_count=3,
            )

            with (
                mock.patch.object(storage_service.settings, "SKILLS_STORAGE_ROOT", storage_root),
                mock.patch.object(
                    skill_service,
                    "_resolve_creation_target_scope",
                    return_value=(SkillDimension.WORKSPACE, "ws-1"),
                ),
                mock.patch.object(
                    github_import_service,
                    "cloned_public_repo",
                    _fake_cloned_public_repo,
                ),
                mock.patch.object(git_service, "ensure_repo_initialized"),
                mock.patch.object(git_service, "commit_all", return_value=commit_meta),
                mock.patch.object(
                    skill_service,
                    "_create_version_row",
                    return_value=SimpleNamespace(version_no=1),
                ) as mock_create_version,
            ):
                imported = skill_service.import_skill_from_github(
                    db=db,
                    user=user,
                    context_workspace_id="ws-1",
                    repo_url="https://github.com/openai/demo-repo",
                    skill_name="demo-skill",
                    description=None,
                    dimension_value="WORKSPACE",
                    workspace_id="ws-1",
                )
                package_root = storage_service.package_abs_path(imported)
                self.assertTrue(os.path.isfile(os.path.join(package_root, "SKILL.md")))
                self.assertTrue(os.path.isfile(os.path.join(package_root, "scripts", "run.sh")))
                self.assertTrue(os.path.isfile(os.path.join(package_root, "assets", "icon.bin")))
                with open(os.path.join(package_root, "assets", "icon.bin"), "rb") as file:
                    self.assertEqual(file.read(), binary_payload)
                self.assertFalse(os.path.exists(os.path.join(package_root, ".git")))

                self.assertEqual(imported.name, "demo-skill")
                self.assertEqual(imported.description, "imported from frontmatter")
                self.assertEqual(imported.head_commit_sha, "abc123")
                self.assertEqual(imported.latest_version_no, 1)
                self.assertTrue(db.committed)
                self.assertFalse(db.rollback_called)

                _, kwargs = mock_create_version.call_args
                self.assertIn("Import from GitHub", str(kwargs.get("change_note") or ""))
                self.assertIn("#skills/demo-skill", str(kwargs.get("change_note") or ""))

    def test_import_package_from_directory_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temp_root:
            storage_root = os.path.join(temp_root, "skills-storage")
            source_root = os.path.join(temp_root, "source-skill")
            os.makedirs(source_root, exist_ok=True)
            _write_text(os.path.join(source_root, "SKILL.md"), "# Skill\n")
            _write_text(os.path.join(source_root, "target.txt"), "payload\n")

            symlink_path = os.path.join(source_root, "link.txt")
            try:
                os.symlink(os.path.join(source_root, "target.txt"), symlink_path)
            except (AttributeError, NotImplementedError, OSError):
                self.skipTest("symlink is not supported in current test environment")

            skill = SddSkill(
                id="skill-1",
                name="skill",
                description=None,
                dimension=SkillDimension.WORKSPACE,
                workspace_id="ws-1",
                creator_id="user-1",
                last_modifier_id="user-1",
                package_path="workspace/ws-1/skill-1__skill",
                entry_file_path="SKILL.md",
                manifest_path=None,
            )

            with mock.patch.object(storage_service.settings, "SKILLS_STORAGE_ROOT", storage_root):
                with self.assertRaises(storage_service.SkillStorageError):
                    storage_service.import_package_from_directory(
                        skill=skill,
                        source_dir=source_root,
                    )


if __name__ == "__main__":
    unittest.main()
