"""
Human Delta comparison engine.

Compares AI-generated patches (from SddTaskChangeProposal) against final
human patches (from SddEvidence COMMIT/MR) to produce a diff that represents
the human modification delta.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAsset, SddAssetVersion, AssetType
from app.domains.asset.services import asset_document_service
from app.domains.task.models.task import SddTask
from app.domains.workflow.models.task_change import (
    ChangeProposalStatus,
    SddTaskChangeProposal,
)
from app.domains.workspace_asset.models.workspace_asset import (
    DeltaRegionSource,
    DeltaRegionType,
    EvidenceSourceType,
    EvidenceStatus,
    HumanDeltaStatus,
    SddDecision,
    SddDeltaRegion,
    SddEvidence,
    SddHumanDelta,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    ChangeProposalSummary,
    EvidenceSummary,
    HumanDeltaSuggestionItem,
)


_GIT_TIMEOUT_SECONDS = 120


class HumanDeltaError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(repo_path: str, args: List[str], *, check: bool = True) -> str:
    abs_repo = os.path.abspath(repo_path)
    cmd = ["git", *args]
    log.info("_run_git: cwd=%s cmd=%s", abs_repo, " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            cwd=abs_repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            log.error("_run_git: exit=%d stderr=%s", result.returncode, stderr[:500])
            raise HumanDeltaError(
                f"git {' '.join(args[:3])} failed (exit {result.returncode}): {stderr[:300]}"
            )
        log.info("_run_git: exit=0 stdout=%d chars", len(result.stdout))
        return result.stdout
    except subprocess.TimeoutExpired:
        log.error("_run_git: timed out after %ds", _GIT_TIMEOUT_SECONDS)
        raise HumanDeltaError("git command timed out")
    except FileNotFoundError:
        log.error("_run_git: git not found in PATH")
        raise HumanDeltaError("git is not installed or not in PATH")


def _read_file_text(path: str, limit: int = 500_000) -> str:
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        raise HumanDeltaError(f"File not found: {abs_path}")
    with open(abs_path, "rb") as f:
        raw = f.read(limit + 1)
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Summary builders
# ---------------------------------------------------------------------------

def _proposal_summary(proposal: SddTaskChangeProposal) -> ChangeProposalSummary:
    return ChangeProposalSummary(
        id=proposal.id,
        proposal_no=proposal.proposal_no,
        patch_set_no=proposal.patch_set_no,
        base_branch=proposal.base_branch,
        changed_files_count=proposal.changed_files_count,
        insertions=proposal.insertions,
        deletions=proposal.deletions,
    )


def _evidence_summary(evidence: SddEvidence) -> EvidenceSummary:
    return EvidenceSummary(
        id=evidence.id,
        source_type=evidence.source_type.value if hasattr(evidence.source_type, "value") else str(evidence.source_type),
        source_ref=evidence.source_ref,
        source_uri=evidence.source_uri,
        title=evidence.title,
    )


# ---------------------------------------------------------------------------
# Suggestion logic
# ---------------------------------------------------------------------------

def suggest_deltas(
    db: Session,
    workspace_id: str,
    task_id: str,
) -> List[HumanDeltaSuggestionItem]:
    """Find unpaired (ChangeProposal, Evidence) combinations for comparison."""
    # Find proposals that have a patch (any non-draft/non-rejected status)
    proposals = (
        db.query(SddTaskChangeProposal)
        .filter(
            SddTaskChangeProposal.workspace_id == workspace_id,
            SddTaskChangeProposal.task_id == task_id,
            SddTaskChangeProposal.status.in_([
                ChangeProposalStatus.GENERATED,
                ChangeProposalStatus.DOWNLOADED,
                ChangeProposalStatus.APPLIED,
                ChangeProposalStatus.CONFLICT,
                ChangeProposalStatus.VERIFIED,
            ]),
        )
        .order_by(SddTaskChangeProposal.patch_set_no.desc())
        .all()
    )

    # Find evidence that could represent a final patch
    evidence_list = (
        db.query(SddEvidence)
        .filter(
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
            SddEvidence.source_type.in_([
                EvidenceSourceType.COMMIT,
                EvidenceSourceType.MR,
                EvidenceSourceType.DIFF,
                EvidenceSourceType.FILE_PATH,
            ]),
        )
        .all()
    )

    if not proposals or not evidence_list:
        return []

    # Find existing delta pairs
    existing_pairs = set(
        db.query(SddHumanDelta.proposal_id, SddHumanDelta.final_evidence_id)
        .filter(
            SddHumanDelta.workspace_id == workspace_id,
            SddHumanDelta.task_id == task_id,
        )
        .all()
    )

    # Only use the latest proposal (first after ordering by patch_set_no desc)
    # to avoid showing intermediate-generation proposals as suggestions.
    latest_proposal = proposals[0]

    suggestions = []
    for evidence in evidence_list:
        if (latest_proposal.id, evidence.id) not in existing_pairs:
            suggestions.append(HumanDeltaSuggestionItem(
                proposal=_proposal_summary(latest_proposal),
                evidence=_evidence_summary(evidence),
            ))

    return suggestions


# ---------------------------------------------------------------------------
# Delta CRUD
# ---------------------------------------------------------------------------

def create_delta(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    proposal_id: str,
    final_evidence_id: str,
) -> str:
    """Create a new HumanDelta record linking a proposal and evidence."""
    _get_task_or_error(db, workspace_id, task_id)
    proposal = _get_proposal_or_error(db, workspace_id, task_id, proposal_id)
    evidence = _get_evidence_or_error(db, workspace_id, task_id, final_evidence_id)

    # Verify not duplicate
    existing = (
        db.query(SddHumanDelta)
        .filter(
            SddHumanDelta.workspace_id == workspace_id,
            SddHumanDelta.task_id == task_id,
            SddHumanDelta.proposal_id == proposal_id,
            SddHumanDelta.final_evidence_id == final_evidence_id,
        )
        .first()
    )
    if existing:
        raise HumanDeltaError("Delta already exists for this proposal + evidence pair")

    delta = SddHumanDelta(
        workspace_id=workspace_id,
        task_id=task_id,
        created_by_id=actor_id,
        proposal_id=proposal_id,
        final_evidence_id=final_evidence_id,
        status=HumanDeltaStatus.PENDING,
    )
    db.add(delta)
    db.flush()

    _add_audit(db, workspace_id, task_id, delta.id, actor_id, "CREATED", after=_delta_snapshot(delta))
    db.commit()

    log.info("Delta %s created (proposal=%s, evidence=%s), starting auto-compare", delta.id, proposal_id, final_evidence_id)

    # Auto-compare: best-effort, don't fail creation
    try:
        compare_patches(db, workspace_id, task_id, delta.id, actor_id)
        log.info("Delta %s auto-compare succeeded, status=READY", delta.id)
    except HumanDeltaError as exc:
        log.warning("Delta %s auto-compare failed: %s", delta.id, exc)
        # Delta stays PENDING, user can retry
    except Exception as exc:
        log.exception("Delta %s auto-compare unexpected error", delta.id)

    return delta.id


def compare_patches(
    db: Session,
    workspace_id: str,
    task_id: str,
    delta_id: str,
    actor_id: Optional[str],
) -> None:
    """Generate comparison diff between AI patch and final patch."""
    delta = _get_delta_or_error(db, workspace_id, task_id, delta_id)
    if not delta.proposal_id:
        raise HumanDeltaError("Delta has no AI patch proposal linked")
    if not delta.final_evidence_id:
        raise HumanDeltaError("Delta has no final evidence linked")

    proposal = _get_proposal_or_error(db, workspace_id, task_id, delta.proposal_id)
    evidence = _get_evidence_or_error(db, workspace_id, task_id, delta.final_evidence_id)
    task = _get_task_or_error(db, workspace_id, task_id)

    log.info(
        "compare_patches delta=%s: proposal=%s (patch_asset_version=%s, base_commit=%s), evidence=%s (type=%s, ref=%s), task_path=%s",
        delta.id, proposal.id, proposal.patch_asset_version_id, proposal.base_commit_sha,
        evidence.id, evidence.source_type, evidence.source_ref, task.project_path,
    )

    # Mark as comparing
    delta.status = HumanDeltaStatus.COMPARING
    db.flush()

    # 1. Read AI patch text
    log.info("compare_patches delta=%s: step 1 - reading AI patch", delta.id)
    ai_patch_text = _read_ai_patch(db, proposal)
    log.info("compare_patches delta=%s: AI patch read OK (%d chars)", delta.id, len(ai_patch_text))

    # 2. Get final patch text
    log.info("compare_patches delta=%s: step 2 - getting final patch", delta.id)
    final_patch_text = _get_final_patch(task, proposal, evidence)
    log.info("compare_patches delta=%s: final patch read OK (%d chars)", delta.id, len(final_patch_text))

    # 2.5. Check hash-based cache
    ai_hash = hashlib.sha256(ai_patch_text.encode("utf-8")).hexdigest()[:16]
    human_hash = hashlib.sha256(final_patch_text.encode("utf-8")).hexdigest()[:16]
    if (
        delta.ai_patch_hash == ai_hash
        and delta.human_patch_hash == human_hash
        and delta.status == HumanDeltaStatus.READY
        and delta.diff_asset_id
    ):
        log.info("compare_patches delta=%s: cache hit, skipping recomputation", delta.id)
        return

    # 3. Compute diff
    log.info("compare_patches delta=%s: step 3 - computing diff", delta.id)
    diff_text, file_diffs = _compute_delta_diff(ai_patch_text, final_patch_text)
    log.info("compare_patches delta=%s: diff computed OK (%d chars, %d files)", delta.id, len(diff_text), len(file_diffs))

    # 4. Store diff as asset
    diff_asset = _store_diff_asset(db, task, actor_id, delta, diff_text, file_diffs=file_diffs)

    # 5. Update delta
    stats = _count_diff_stats(file_diffs)
    delta.diff_asset_id = diff_asset.id
    delta.changed_files_count = stats["files"]
    delta.insertions = stats["insertions"]
    delta.deletions = stats["deletions"]
    delta.ai_patch_hash = ai_hash
    delta.human_patch_hash = human_hash
    delta.status = HumanDeltaStatus.READY

    # 6. Compute and store DeltaRegion records
    _delete_old_regions(db, delta.id)
    region_data_list = _compute_delta_regions(file_diffs)
    for region_data in region_data_list:
        region = SddDeltaRegion(
            workspace_id=workspace_id,
            delta_id=delta.id,
            **region_data,
        )
        db.add(region)
    log.info("compare_patches delta=%s: created %d delta regions", delta.id, len(region_data_list))

    log.info("compare_patches delta=%s: DONE, files=%d ins=%d del=%d", delta.id, stats["files"], stats["insertions"], stats["deletions"])

    _add_audit(db, workspace_id, task_id, delta.id, actor_id, "UPDATED", after=_delta_snapshot(delta))
    db.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_task_or_error(db: Session, workspace_id: str, task_id: str) -> SddTask:
    task = (
        db.query(SddTask)
        .filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id)
        .first()
    )
    if not task:
        raise HumanDeltaError("Task not found", status_code=404)
    return task


def _get_proposal_or_error(db: Session, workspace_id: str, task_id: str, proposal_id: str) -> SddTaskChangeProposal:
    proposal = (
        db.query(SddTaskChangeProposal)
        .filter(
            SddTaskChangeProposal.id == proposal_id,
            SddTaskChangeProposal.workspace_id == workspace_id,
            SddTaskChangeProposal.task_id == task_id,
        )
        .first()
    )
    if not proposal:
        raise HumanDeltaError("ChangeProposal not found", status_code=404)
    return proposal


def _get_evidence_or_error(db: Session, workspace_id: str, task_id: str, evidence_id: str) -> SddEvidence:
    evidence = (
        db.query(SddEvidence)
        .filter(
            SddEvidence.id == evidence_id,
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
        )
        .first()
    )
    if not evidence:
        raise HumanDeltaError("Evidence not found", status_code=404)
    return evidence


def _get_delta_or_error(db: Session, workspace_id: str, task_id: str, delta_id: str) -> SddHumanDelta:
    delta = (
        db.query(SddHumanDelta)
        .filter(
            SddHumanDelta.id == delta_id,
            SddHumanDelta.workspace_id == workspace_id,
            SddHumanDelta.task_id == task_id,
        )
        .first()
    )
    if not delta:
        raise HumanDeltaError("HumanDelta not found", status_code=404)
    return delta


def _read_ai_patch(db: Session, proposal: SddTaskChangeProposal) -> str:
    """Read the AI patch text from the proposal's patch asset."""
    version_id = str(proposal.patch_asset_version_id or "").strip()
    if not version_id:
        raise HumanDeltaError("Proposal has no patch_asset_version_id")
    version = db.query(SddAssetVersion).filter(SddAssetVersion.id == version_id).first()
    if not version:
        raise HumanDeltaError(f"Patch asset version not found (version_id={version_id})")

    # 1. Try disk file
    path = str(version.original_path or "").strip()
    if path and os.path.isfile(path):
        log.info("_read_ai_patch: reading from disk: %s", path)
        return _read_file_text(path)
    log.info("_read_ai_patch: disk file not found (original_path=%s), trying DB fallback", path or "(empty)")

    # 2. Fallback to version.normalized_markdown (DB)
    md = str(version.normalized_markdown or "").strip()
    if md:
        log.info("_read_ai_patch: using normalized_markdown (%d chars)", len(md))
        return md

    # 3. Fallback to asset.content_text (denormalized)
    asset = db.query(SddAsset).filter(SddAsset.id == version.asset_id).first()
    if asset:
        ct = str(asset.content_text or "").strip()
        if ct:
            log.info("_read_ai_patch: using asset.content_text (%d chars)", len(ct))
            return ct

    raise HumanDeltaError(
        f"Patch artifact has no readable content (version_id={version_id}, "
        f"original_path={path!r}, normalized_markdown={'yes' if md else 'no'}, asset_found={asset is not None})"
    )


def _ensure_commits_local(repo_path: str, sha_list: List[str]) -> None:
    """Check if SHAs exist locally, fetch from origin if any are missing."""
    missing = []
    for sha in sha_list:
        if not sha:
            continue
        try:
            _run_git(repo_path, ["cat-file", "-e", sha], check=True)
        except HumanDeltaError:
            missing.append(sha)
    if not missing:
        return
    log.info("_ensure_commits_local: %d SHA(s) missing, fetching origin", len(missing))
    _run_git(repo_path, ["fetch", "origin"])
    for sha in missing:
        try:
            _run_git(repo_path, ["cat-file", "-e", sha], check=True)
        except HumanDeltaError:
            raise HumanDeltaError(
                f"Commit {sha[:12]}... not found even after fetching from origin. "
                "Ensure the commit has been pushed to the remote."
            )
    log.info("_ensure_commits_local: fetch succeeded, all SHAs now present")


def _get_final_patch(task: SddTask, proposal: SddTaskChangeProposal, evidence: SddEvidence) -> str:
    """Get the final patch text from git using the evidence commit SHA."""
    repo_path = str(task.project_path or "").strip()
    if not repo_path or not os.path.isdir(repo_path):
        raise HumanDeltaError(f"Task project path is not a valid directory: {repo_path!r}")

    source_type = evidence.source_type.value if hasattr(evidence.source_type, "value") else str(evidence.source_type)

    if source_type == "COMMIT":
        commit_sha = str(evidence.source_ref or "").strip()
        if not commit_sha:
            raise HumanDeltaError("COMMIT evidence has no source_ref (commit SHA)")
        base_sha = str(proposal.base_commit_sha or "").strip()
        if not base_sha:
            raise HumanDeltaError("Proposal has no base_commit_sha")
        _ensure_commits_local(repo_path, [base_sha, commit_sha])
        cmd = ["diff", f"{base_sha}..{commit_sha}", "--binary", "--find-renames"]
        log.info("_get_final_patch COMMIT: repo=%s, git %s", repo_path, " ".join(cmd))
        result = _run_git(repo_path, cmd)
        log.info("_get_final_patch COMMIT: git diff returned %d chars", len(result))
        return result

    if source_type == "MR":
        # For MR evidence, try to get commit SHA from source_ref
        commit_sha = str(evidence.source_ref or "").strip()
        if commit_sha:
            base_sha = str(proposal.base_commit_sha or "").strip()
            if base_sha:
                _ensure_commits_local(repo_path, [base_sha, commit_sha])
                return _run_git(repo_path, ["diff", f"{base_sha}..{commit_sha}", "--binary", "--find-renames"])
        raise HumanDeltaError(
            "MR evidence requires a commit SHA in source_ref to generate diff. "
            "Please update the Evidence with the merge commit SHA."
        )

    if source_type == "DIFF":
        # DIFF evidence stores the diff content directly
        diff_path = str(evidence.source_path or evidence.source_uri or "").strip()
        if diff_path and os.path.isfile(diff_path):
            return _read_file_text(diff_path)
        # Try source_ref as content path
        ref = str(evidence.source_ref or "").strip()
        if ref and os.path.isfile(ref):
            return _read_file_text(ref)
        raise HumanDeltaError(
            "DIFF evidence has no readable diff file. "
            "Please ensure source_path or source_ref points to the diff file."
        )

    if source_type == "FILE_PATH":
        # FILE_PATH evidence: source_ref contains file paths, use git to diff them
        base_sha = str(proposal.base_commit_sha or "").strip()
        if not base_sha:
            raise HumanDeltaError("Proposal has no base_commit_sha for FILE_PATH comparison")
        _ensure_commits_local(repo_path, [base_sha])
        file_paths = [p.strip() for p in str(evidence.source_ref or "").split(",") if p.strip()]
        if not file_paths:
            raise HumanDeltaError("FILE_PATH evidence has no file paths in source_ref")
        return _run_git(repo_path, ["diff", base_sha, "--binary", "--find-renames", "--"] + file_paths)

    raise HumanDeltaError(f"Unsupported evidence source_type: {source_type}")


def _compute_delta_diff(
    ai_patch_text: str, final_patch_text: str
) -> Tuple[str, List[Dict[str, Any]]]:
    """Compare AI patch and human patch at the file level.

    Returns (summary_text, file_diffs). Each file_diff dict contains:
      file_path, change_type, comparison_type,
      ai_insertions, ai_deletions, human_insertions, human_deletions,
      insertions, deletions (total), hunks.
    """
    ai_files = _parse_patch_to_files(ai_patch_text)
    final_files = _parse_patch_to_files(final_patch_text)

    ai_map: Dict[str, Dict[str, Any]] = {f["file_path"]: f for f in ai_files}
    final_map: Dict[str, Dict[str, Any]] = {f["file_path"]: f for f in final_files}

    all_paths = sorted(set(ai_map) | set(final_map))

    result: List[Dict[str, Any]] = []
    summary_ai = 0
    summary_human = 0
    summary_common = 0

    for path in all_paths:
        ai_fd = ai_map.get(path)
        final_fd = final_map.get(path)

        if ai_fd and not final_fd:
            result.append({
                "file_path": path,
                "change_type": ai_fd["change_type"],
                "comparison_type": "ai_only",
                "ai_change_type": ai_fd["change_type"],
                "human_change_type": None,
                "ai_insertions": ai_fd["insertions"],
                "ai_deletions": ai_fd["deletions"],
                "human_insertions": 0,
                "human_deletions": 0,
                "insertions": ai_fd["insertions"],
                "deletions": ai_fd["deletions"],
                "hunks": ai_fd["hunks"],
                "ai_hunks": ai_fd["hunks"],
                "human_hunks": [],
            })
            summary_ai += 1

        elif final_fd and not ai_fd:
            result.append({
                "file_path": path,
                "change_type": final_fd["change_type"],
                "comparison_type": "human_only",
                "ai_change_type": None,
                "human_change_type": final_fd["change_type"],
                "ai_insertions": 0,
                "ai_deletions": 0,
                "human_insertions": final_fd["insertions"],
                "human_deletions": final_fd["deletions"],
                "insertions": final_fd["insertions"],
                "deletions": final_fd["deletions"],
                "hunks": final_fd["hunks"],
                "ai_hunks": [],
                "human_hunks": final_fd["hunks"],
            })
            summary_human += 1

        else:
            merged_hunks, total_ins, total_del = _merge_common_file_hunks(
                ai_fd["hunks"], final_fd["hunks"]
            )
            result.append({
                "file_path": path,
                "change_type": ai_fd["change_type"],
                "comparison_type": "common",
                "ai_change_type": ai_fd["change_type"],
                "human_change_type": final_fd["change_type"],
                "ai_insertions": ai_fd["insertions"],
                "ai_deletions": ai_fd["deletions"],
                "human_insertions": final_fd["insertions"],
                "human_deletions": final_fd["deletions"],
                "insertions": total_ins,
                "deletions": total_del,
                "hunks": merged_hunks,
                "ai_hunks": ai_fd["hunks"],
                "human_hunks": final_fd["hunks"],
            })
            summary_common += 1

    parts = []
    if summary_ai:
        parts.append(f"{summary_ai} file(s) only in AI patch")
    if summary_human:
        parts.append(f"{summary_human} file(s) only in human patch")
    if summary_common:
        parts.append(f"{summary_common} file(s) in both")
    summary = "; ".join(parts) if parts else "No differences"

    return summary, result


def _merge_common_file_hunks(
    ai_hunks: List[Dict[str, Any]],
    final_hunks: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Merge hunks from AI and human patches for the same file.

    Returns (merged_hunks, total_insertions, total_deletions).
    Each line gets a ``source`` field: "both", "ai", "human", or "context".
    """
    ai_changes: set[Tuple[str, str]] = set()
    ai_all_lines: List[Dict[str, Any]] = []
    for hunk in ai_hunks:
        for line in hunk.get("lines", []):
            ai_all_lines.append(line)
            if line["type"] != "context":
                ai_changes.add((line["type"], line["content"]))

    final_only: List[Dict[str, Any]] = []
    final_change_keys: set[Tuple[str, str]] = set()
    for hunk in final_hunks:
        for line in hunk.get("lines", []):
            if line["type"] != "context":
                key = (line["type"], line["content"])
                final_change_keys.add(key)
                if key not in ai_changes:
                    final_only.append({**line, "source": "human"})

    merged: List[Dict[str, Any]] = []
    for line in ai_all_lines:
        if line["type"] == "context":
            merged.append({**line, "source": "context"})
        elif (line["type"], line["content"]) in final_change_keys:
            merged.append({**line, "source": "both"})
        else:
            merged.append({**line, "source": "ai"})

    merged.extend(final_only)

    total_ins = sum(1 for l in merged if l["type"] == "add")
    total_del = sum(1 for l in merged if l["type"] == "del")

    hunk = {
        "old_start": 1,
        "old_count": total_del,
        "new_start": 1,
        "new_count": total_ins,
        "lines": merged,
    }
    return [hunk], total_ins, total_del


# --- Structured diff parser ---

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_FILE_FROM_RE = re.compile(r"^--- (.+)$")
_FILE_TO_RE = re.compile(r"^\+\+\+ (.+)$")


def _parse_patch_to_files(patch_text: str) -> List[Dict[str, Any]]:
    """Parse unified diff text into per-file structured data.

    Handles both git-diff format (with ``diff --git`` headers) and plain
    difflib unified-diff format (only ``---``/``+++`` headers).

    Returns list of dicts with keys:
      file_path, old_path, new_path, change_type,
      insertions, deletions, hunks
    """
    if not patch_text or not patch_text.strip():
        return []

    lines = patch_text.split("\n")

    # ── Step 1: split into file segments ──────────────────────────────
    # A segment starts at a ``diff --git`` line, or at a ``---`` line
    # when there is no ``diff --git`` header.
    segments: List[Tuple[int, int]] = []  # (start_idx, end_idx)
    has_git_headers = any(ln.startswith("diff --git") for ln in lines)

    if has_git_headers:
        starts = [i for i, ln in enumerate(lines) if ln.startswith("diff --git")]
        for j, start in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else len(lines)
            segments.append((start, end))
    else:
        # difflib format: segments begin at ``--- `` lines
        starts = [i for i, ln in enumerate(lines) if ln.startswith("--- ")]
        for j, start in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else len(lines)
            segments.append((start, end))

    result: List[Dict[str, Any]] = []

    for seg_start, seg_end in segments:
        seg_lines = lines[seg_start:seg_end]
        file_info = _parse_single_file_segment(seg_lines, has_git_headers)
        if file_info:
            result.append(file_info)

    return result


def _parse_single_file_segment(
    seg_lines: List[str], has_git_headers: bool
) -> Optional[Dict[str, Any]]:
    """Parse one file segment into a structured dict."""
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    hunks: List[Dict[str, Any]] = []
    current_hunk: Optional[Dict[str, Any]] = None
    insertions = 0
    deletions = 0

    # Track line numbers within current hunk
    old_line_no = 0
    new_line_no = 0

    for line in seg_lines:
        # ── diff --git header ──
        if line.startswith("diff --git"):
            m = _DIFF_GIT_RE.match(line)
            if m:
                old_path = m.group(1)
                new_path = m.group(2)
            continue

        # ── --- / +++ headers ──
        if line.startswith("--- "):
            m = _FILE_FROM_RE.match(line)
            if m:
                val = m.group(1)
                if val == "/dev/null":
                    old_path = "/dev/null"
                elif not has_git_headers:
                    old_path = val
            continue
        if line.startswith("+++ "):
            m = _FILE_TO_RE.match(line)
            if m:
                val = m.group(1)
                if val == "/dev/null":
                    new_path = "/dev/null"
                elif not has_git_headers:
                    new_path = val
            continue

        # ── index / mode lines ──
        if line.startswith("index ") or line.startswith("new file mode ") or line.startswith("deleted file mode "):
            continue

        # ── @@ hunk header ──
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            current_hunk = {
                "old_start": int(hunk_match.group(1)),
                "old_count": int(hunk_match.group(2) or "1"),
                "new_start": int(hunk_match.group(3)),
                "new_count": int(hunk_match.group(4) or "1"),
                "lines": [],
            }
            hunks.append(current_hunk)
            old_line_no = current_hunk["old_start"]
            new_line_no = current_hunk["new_start"]
            continue

        # ── diff content lines ──
        if current_hunk is not None:
            if line.startswith("+"):
                current_hunk["lines"].append({
                    "type": "add",
                    "content": line[1:],
                    "old_line_no": None,
                    "new_line_no": new_line_no,
                })
                new_line_no += 1
                insertions += 1
            elif line.startswith("-"):
                current_hunk["lines"].append({
                    "type": "del",
                    "content": line[1:],
                    "old_line_no": old_line_no,
                    "new_line_no": None,
                })
                old_line_no += 1
                deletions += 1
            else:
                # context line (starts with space or is empty)
                content = line[1:] if line.startswith(" ") else line
                current_hunk["lines"].append({
                    "type": "context",
                    "content": content,
                    "old_line_no": old_line_no,
                    "new_line_no": new_line_no,
                })
                old_line_no += 1
                new_line_no += 1

    if not old_path and not new_path:
        return None

    # Determine file_path (prefer real path over /dev/null)
    if new_path and new_path != "/dev/null":
        file_path = new_path
    elif old_path and old_path != "/dev/null":
        file_path = old_path
    else:
        file_path = new_path or old_path or ""

    # Determine change_type
    if old_path in (None, "/dev/null"):
        change_type = "added"
    elif new_path in (None, "/dev/null"):
        change_type = "deleted"
    elif old_path != new_path:
        change_type = "renamed"
    else:
        change_type = "modified"

    return {
        "file_path": file_path,
        "old_path": old_path,
        "new_path": new_path,
        "change_type": change_type,
        "insertions": insertions,
        "deletions": deletions,
        "hunks": hunks,
    }


def _count_diff_stats(structured_diffs: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count files, insertions, deletions from comparison diff data."""
    return {
        "files": len(structured_diffs),
        "insertions": sum(f.get("insertions", 0) for f in structured_diffs),
        "deletions": sum(f.get("deletions", 0) for f in structured_diffs),
    }


def _delete_old_regions(db: Session, delta_id: str) -> None:
    """Delete existing DeltaRegion records for a delta (before re-creating)."""
    db.query(SddDeltaRegion).filter(SddDeltaRegion.delta_id == delta_id).delete(synchronize_session=False)


def _compute_delta_regions(
    file_diffs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract DeltaRegion data from structured file diffs."""
    regions: List[Dict[str, Any]] = []
    for file_diff in file_diffs:
        comparison_type = file_diff.get("comparison_type")
        change_type = file_diff.get("change_type", "modified")

        if comparison_type == "ai_only":
            region_type = _change_type_to_region_type(change_type)
            regions.append({
                "file_path": file_diff["file_path"],
                "old_file_path": file_diff.get("old_path"),
                "region_type": region_type,
                "region_source": DeltaRegionSource.AI_ONLY,
                "ai_insertions": file_diff.get("ai_insertions", file_diff.get("insertions", 0)),
                "ai_deletions": file_diff.get("ai_deletions", file_diff.get("deletions", 0)),
                "human_insertions": 0,
                "human_deletions": 0,
            })

        elif comparison_type == "human_only":
            region_type = _change_type_to_region_type(change_type)
            regions.append({
                "file_path": file_diff["file_path"],
                "old_file_path": file_diff.get("old_path"),
                "region_type": region_type,
                "region_source": DeltaRegionSource.HUMAN_ONLY,
                "ai_insertions": 0,
                "ai_deletions": 0,
                "human_insertions": file_diff.get("human_insertions", file_diff.get("insertions", 0)),
                "human_deletions": file_diff.get("human_deletions", file_diff.get("deletions", 0)),
            })

        elif comparison_type == "common":
            regions.extend(_extract_common_file_regions(file_diff))

    return regions


def _change_type_to_region_type(change_type: str) -> DeltaRegionType:
    """Map file change_type to DeltaRegionType enum."""
    mapping = {
        "added": DeltaRegionType.FILE_ADDED,
        "deleted": DeltaRegionType.FILE_DELETED,
        "renamed": DeltaRegionType.FILE_RENAMED,
        "modified": DeltaRegionType.HUNK_MODIFIED,
    }
    return mapping.get(change_type, DeltaRegionType.HUNK_MODIFIED)


def _extract_common_file_regions(
    file_diff: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract DeltaRegion data from a common file's merged hunks.

    Walks the merged hunk lines and groups consecutive lines by source
    into contiguous regions.
    """
    regions: List[Dict[str, Any]] = []
    hunks = file_diff.get("hunks", [])
    if not hunks:
        return regions

    # Flatten all lines from all hunks
    all_lines = []
    for hunk in hunks:
        all_lines.extend(hunk.get("lines", []))

    if not all_lines:
        return regions

    # Group consecutive lines by source into regions
    current_source = None
    block_start_idx = 0
    ai_ins = 0
    ai_del = 0
    human_ins = 0
    human_del = 0

    def _flush_block():
        if current_source is None or current_source == "context":
            return
        region_source = _source_to_region_source(current_source)
        # Determine line ranges
        ai_lines = [l for l in all_lines[block_start_idx:i] if l.get("source") in ("ai", "both")]
        human_lines = [l for l in all_lines[block_start_idx:i] if l.get("source") in ("human", "both")]
        ai_start = ai_lines[0].get("new_line_no") if ai_lines else None
        ai_end = ai_lines[-1].get("new_line_no") if ai_lines else None
        human_start = human_lines[0].get("new_line_no") if human_lines else None
        human_end = human_lines[-1].get("new_line_no") if human_lines else None

        summary_parts = []
        if ai_ins:
            summary_parts.append(f"AI +{ai_ins}")
        if ai_del:
            summary_parts.append(f"AI -{ai_del}")
        if human_ins:
            summary_parts.append(f"Human +{human_ins}")
        if human_del:
            summary_parts.append(f"Human -{human_del}")

        regions.append({
            "file_path": file_diff["file_path"],
            "old_file_path": file_diff.get("old_path"),
            "region_type": DeltaRegionType.HUNK_MODIFIED,
            "region_source": region_source,
            "ai_line_start": ai_start,
            "ai_line_end": ai_end,
            "human_line_start": human_start,
            "human_line_end": human_end,
            "ai_insertions": ai_ins,
            "ai_deletions": ai_del,
            "human_insertions": human_ins,
            "human_deletions": human_del,
            "summary": ", ".join(summary_parts) if summary_parts else None,
        })

    for i, line in enumerate(all_lines):
        source = line.get("source", "context")
        if source != current_source:
            if current_source is not None:
                _flush_block()
            block_start_idx = i
            current_source = source
            ai_ins = 0
            ai_del = 0
            human_ins = 0
            human_del = 0

        if source == "ai":
            if line.get("type") == "add":
                ai_ins += 1
            elif line.get("type") == "del":
                ai_del += 1
        elif source == "human":
            if line.get("type") == "add":
                human_ins += 1
            elif line.get("type") == "del":
                human_del += 1
        elif source == "both":
            if line.get("type") == "add":
                ai_ins += 1
                human_ins += 1
            elif line.get("type") == "del":
                ai_del += 1
                human_del += 1

    # Flush the last block
    if current_source is not None:
        _flush_block()

    return regions


def _source_to_region_source(source: str) -> DeltaRegionSource:
    """Map line source tag to DeltaRegionSource enum."""
    mapping = {
        "ai": DeltaRegionSource.AI_ONLY,
        "human": DeltaRegionSource.HUMAN_ONLY,
        "both": DeltaRegionSource.BOTH_SAME,
    }
    return mapping.get(source, DeltaRegionSource.DIVERGED)


def _store_diff_asset(
    db: Session,
    task: SddTask,
    actor_id: Optional[str],
    delta: SddHumanDelta,
    diff_text: str,
    file_diffs: Optional[List[Dict[str, Any]]] = None,
) -> SddAsset:
    """Store the comparison diff as an asset."""
    raw = diff_text.encode("utf-8")
    content_json: Dict[str, Any] = {
        "artifact_kind": "human_delta_diff",
        "delta_id": delta.id,
        "proposal_id": delta.proposal_id,
        "final_evidence_id": delta.final_evidence_id,
    }
    if file_diffs:
        content_json["file_diffs"] = file_diffs
    asset, _version = asset_document_service.create_task_asset_version_from_bytes(
        db,
        task,
        creator_id=actor_id,
        asset_type=AssetType.CODE_DIFF,
        asset_name=f"Human Delta #{delta.id[:8]} Diff",
        file_name=f"human-delta-{delta.id[:8]}.diff",
        file_content=raw,
        content_text=diff_text[:50000],
        content_json=content_json,
        change_note="Human Delta comparison diff",
        source_ext=".diff",
        source_mime="text/x-diff",
    )
    return asset


def _delta_snapshot(delta: SddHumanDelta) -> dict:
    return {
        "id": delta.id,
        "status": delta.status.value if hasattr(delta.status, "value") else delta.status,
        "proposal_id": delta.proposal_id,
        "final_evidence_id": delta.final_evidence_id,
        "diff_asset_id": delta.diff_asset_id,
        "changed_files_count": delta.changed_files_count,
        "insertions": delta.insertions,
        "deletions": delta.deletions,
    }


def _add_audit(
    db: Session,
    workspace_id: str,
    task_id: str,
    record_id: str,
    actor_id: Optional[str],
    action: str,
    *,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
) -> None:
    from app.domains.workspace_asset.models.workspace_asset import SddTaskProcessAuditLog
    log = SddTaskProcessAuditLog(
        workspace_id=workspace_id,
        task_id=task_id,
        actor_id=actor_id,
        record_type=TaskProcessRecordType.HUMAN_DELTA,
        record_id=record_id,
        action=TaskProcessAuditAction(action),
        before_json=before,
        after_json=after,
    )
    db.add(log)
