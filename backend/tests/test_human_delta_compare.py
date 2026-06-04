"""
Diagnostic script for Human Delta comparison.

Usage:
    python test_human_delta_compare.py <workspace_id> <task_id>
    python test_human_delta_compare.py <workspace_id> <task_id> --fix

With --fix: re-runs comparison for all PENDING deltas.
"""
import logging
import os
import sys

# Setup logging to see everything
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("test_human_delta")

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.domains.asset.models.asset import SddAsset, SddAssetVersion
from app.domains.task.models.task import SddTask
from app.domains.workflow.models.task_change import SddTaskChangeProposal
from app.domains.workspace_asset.models.workspace_asset import (
    EvidenceSourceType,
    HumanDeltaStatus,
    SddEvidence,
    SddHumanDelta,
)
from app.domains.workspace_asset.services.human_delta_compare_service import (
    compare_patches,
    _get_final_patch,
    _read_ai_patch,
    _run_git,
)


def check_delta(db, workspace_id: str, task_id: str, delta: SddHumanDelta):
    """Run full diagnostic on a single delta."""
    print(f"\n{'='*60}")
    print(f"Delta: {delta.id}")
    print(f"  status:          {delta.status.value if hasattr(delta.status, 'value') else delta.status}")
    print(f"  proposal_id:     {delta.proposal_id}")
    print(f"  evidence_id:     {delta.final_evidence_id}")
    print(f"  diff_asset_id:   {delta.diff_asset_id}")
    print(f"  created_at:      {delta.created_at}")

    errors = []

    # Check proposal
    proposal = db.query(SddTaskChangeProposal).filter(SddTaskChangeProposal.id == delta.proposal_id).first()
    if not proposal:
        errors.append("Proposal not found")
    else:
        print(f"\n  Proposal: {proposal.id}")
        print(f"    status:              {proposal.status.value if hasattr(proposal.status, 'value') else proposal.status}")
        print(f"    patch_asset_id:      {proposal.patch_asset_id}")
        print(f"    patch_asset_ver_id:  {proposal.patch_asset_version_id}")
        print(f"    base_commit_sha:     {proposal.base_commit_sha}")
        print(f"    base_branch:         {proposal.base_branch}")
        print(f"    changed_files_count: {proposal.changed_files_count}")

        if not proposal.patch_asset_version_id:
            errors.append("Proposal has no patch_asset_version_id")
        else:
            version = db.query(SddAssetVersion).filter(SddAssetVersion.id == proposal.patch_asset_version_id).first()
            if not version:
                errors.append(f"AssetVersion not found (id={proposal.patch_asset_version_id})")
            else:
                print(f"\n    AssetVersion: {version.id}")
                print(f"      original_path:      {version.original_path}")
                path = str(version.original_path or "").strip()
                file_exists = path and os.path.isfile(path)
                print(f"      file_exists:        {file_exists}")
                md = str(version.normalized_markdown or "").strip()
                print(f"      normalized_markdown: {len(md)} chars")
                asset = db.query(SddAsset).filter(SddAsset.id == version.asset_id).first()
                if asset:
                    ct = str(asset.content_text or "").strip()
                    print(f"      asset.content_text:  {len(ct)} chars")
                else:
                    errors.append("Parent SddAsset not found")

                if not file_exists and not md and (not asset or not str(asset.content_text or "").strip()):
                    errors.append("No readable AI patch content anywhere (disk + DB)")

        if not proposal.base_commit_sha:
            errors.append("Proposal has no base_commit_sha")

    # Check evidence
    evidence = db.query(SddEvidence).filter(SddEvidence.id == delta.final_evidence_id).first()
    if not evidence:
        errors.append("Evidence not found")
    else:
        st = evidence.source_type.value if hasattr(evidence.source_type, "value") else str(evidence.source_type)
        print(f"\n  Evidence: {evidence.id}")
        print(f"    source_type:  {st}")
        print(f"    source_ref:   {evidence.source_ref}")
        print(f"    source_uri:   {evidence.source_uri}")
        print(f"    source_path:  {evidence.source_path}")
        print(f"    title:        {evidence.title}")
        print(f"    status:       {evidence.status}")

        if st == "COMMIT":
            if not evidence.source_ref:
                errors.append("COMMIT evidence has no source_ref")
            if proposal and not proposal.base_commit_sha:
                errors.append("Cannot git diff: proposal has no base_commit_sha")

    # Check task
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        errors.append("Task not found")
    else:
        repo_path = str(task.project_path or "").strip()
        print(f"\n  Task: {task.id}")
        print(f"    project_path: {repo_path}")
        is_dir = os.path.isdir(repo_path)
        print(f"    is_dir:       {is_dir}")
        if is_dir:
            is_git = os.path.isdir(os.path.join(repo_path, ".git"))
            print(f"    is_git_repo:  {is_git}")
            if is_git and proposal and evidence:
                base_sha = str(proposal.base_commit_sha or "").strip()
                commit_sha = str(evidence.source_ref or "").strip()
                if base_sha:
                    try:
                        _run_git(repo_path, ["cat-file", "-e", base_sha])
                        print(f"    base_sha exists in repo: YES")
                    except Exception as e:
                        print(f"    base_sha exists in repo: NO ({e})")
                        errors.append(f"base_commit_sha {base_sha[:12]}... not found in git repo")
                if commit_sha:
                    try:
                        _run_git(repo_path, ["cat-file", "-e", commit_sha])
                        print(f"    commit_sha exists in repo: YES")
                    except Exception as e:
                        print(f"    commit_sha exists in repo: NO ({e})")
                        errors.append(f"evidence commit {commit_sha[:12]}... not found in git repo")
        else:
            errors.append(f"project_path is not a directory: {repo_path!r}")

    print(f"\n  Errors: {len(errors)}")
    for err in errors:
        print(f"    - {err}")

    return errors


def try_compare(db, workspace_id: str, task_id: str, delta: SddHumanDelta, actor_id=None):
    """Try to run comparison and report result."""
    print(f"\n  Attempting comparison for delta {delta.id}...")
    try:
        compare_patches(db, workspace_id, task_id, delta.id, actor_id)
        db.refresh(delta)
        print(f"  SUCCESS: status={delta.status.value if hasattr(delta.status, 'value') else delta.status}")
        print(f"    diff_asset_id: {delta.diff_asset_id}")
        print(f"    files: {delta.changed_files_count}, +{delta.insertions}, -{delta.deletions}")
        return True
    except Exception as exc:
        print(f"  FAILED: {exc}")
        return False


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    workspace_id = sys.argv[1]
    task_id = sys.argv[2]
    fix = "--fix" in sys.argv

    db = SessionLocal()
    try:
        # Check task exists
        task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
        if not task:
            print(f"Task not found: workspace={workspace_id}, task={task_id}")
            sys.exit(1)

        print(f"Task: {task.name} (status={task.status.value if hasattr(task.status, 'value') else task.status})")

        # List all deltas
        deltas = (
            db.query(SddHumanDelta)
            .filter(SddHumanDelta.workspace_id == workspace_id, SddHumanDelta.task_id == task_id)
            .all()
        )
        print(f"Found {len(deltas)} delta(s)")

        if not deltas:
            # Check if there are proposals and evidence
            proposals = db.query(SddTaskChangeProposal).filter(
                SddTaskChangeProposal.workspace_id == workspace_id,
                SddTaskChangeProposal.task_id == task_id,
            ).all()
            evidence = db.query(SddEvidence).filter(
                SddEvidence.workspace_id == workspace_id,
                SddEvidence.task_id == task_id,
            ).all()
            print(f"  Proposals: {len(proposals)}")
            for p in proposals:
                print(f"    - {p.id} status={p.status.value if hasattr(p.status, 'value') else p.status}")
            print(f"  Evidence: {len(evidence)}")
            for e in evidence:
                st = e.source_type.value if hasattr(e.source_type, "value") else str(e.source_type)
                print(f"    - {e.id} type={st} ref={e.source_ref}")

        total_errors = 0
        for delta in deltas:
            errors = check_delta(db, workspace_id, task_id, delta)
            total_errors += len(errors)

            if fix and delta.status in (HumanDeltaStatus.PENDING, HumanDeltaStatus.COMPARING):
                try_compare(db, workspace_id, task_id, delta)

        print(f"\n{'='*60}")
        print(f"Total errors: {total_errors}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
