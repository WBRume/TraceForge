"""Private document drafts and atomic publication of their source and discussion anchors."""

from pathlib import Path

from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAsset, SddAssetDocumentDraft, SddAssetVersion
from app.domains.asset.schemas.asset import AssetDraftResponse, AssetDraftSave, AssetDraftState
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.asset.services.document import repository, transactions, versioning
from app.domains.asset.services.document.docx import parse_docx_payload
from app.domains.asset.services.document.docx.paragraph_edit import docx_edit_regions, edit_docx_paragraphs
from app.domains.asset.services.document.inheritance import inherit_anchors
from app.domains.asset.services.document.text_source import TEXT_EXTENSIONS, decode_source, read_original
from app.domains.asset.services.review import policy
from app.domains.asset.services.review.errors import ReviewError
from app.domains.local_resource.service import is_local, materialize_file
from app.domains.task.services import task_cli_state_service


def _asset(db: Session, ws_id: str, asset_id: str, user_id: str, *, lock: bool = False) -> SddAsset:
    policy._verify_expert_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(404, "Asset not found")
    if lock:
        if asset.task:
            transactions.lock_task_for_document_write(db, asset.task)
            db.refresh(asset.task, attribute_names=["status"])
        transactions.lock_asset(db, asset)
    return asset


def _base(db: Session, asset: SddAsset, version_id: str) -> SddAssetVersion:
    version = repository.get_asset_version(db, asset.id, version_id)
    if not version:
        raise ReviewError(404, "Draft base version not found")
    return version


def _check_state(draft: SddAssetDocumentDraft | None, state: AssetDraftState) -> None:
    if draft is None and state.revision == 0:
        return
    if draft is None or draft.revision != state.revision or draft.base_version_id != state.base_version_id:
        raise ReviewError(409, "This draft changed. Reopen it to load the latest saved changes")


def _response(base: SddAssetVersion, draft: SddAssetDocumentDraft, source: bytes | None = None) -> AssetDraftResponse:
    blocks = None
    if (base.original_ext or "").lower() == ".docx":
        blocks = base.blocks_json
        if draft.docx_edits:
            if source is None:
                source, _, _ = _prepare_source(base, None, draft.docx_edits)
            blocks = parse_docx_payload(source)["blocks_json"]
    return AssetDraftResponse(
        base_version_id=base.id,
        revision=draft.revision,
        text=draft.text,
        docx_edits=draft.docx_edits,
        blocks=blocks,
    )


def _prepare_source(
    base: SddAssetVersion, text: str | None, edits: dict[str, str]
) -> tuple[bytes, dict[str, str], bool]:
    ext = (base.original_ext or "").lower()
    try:
        if ext in TEXT_EXTENSIONS:
            if text is None or edits or "\0" in text:
                raise ValueError("Expected plain source text")
            original = read_original(base)
            old, encoding, bom = decode_source(original)
            try:
                source = bom + text.encode(encoding)
            except UnicodeEncodeError:
                source = text.encode("utf-8")
            return source, {}, text != old

        if ext != ".docx" or text is not None:
            raise ValueError("Unsupported draft format")
        targets = docx_edit_regions(base.blocks_json or [])
        changes: dict[str, str] = {}
        patches: list[tuple[int, str, str]] = []
        for block_id, value in edits.items():
            target = targets.get(block_id)
            if target is None:
                raise ValueError("The block has no editable source DOCX paragraph")
            ordinal, old, in_table = target.paragraph, target.text, target.in_table
            value = value.replace("\r\n", "\n").replace("\r", "\n")
            if len(value) > 100_000:
                raise ValueError("Edited paragraphs must contain at most 100,000 characters")
            if not in_table and not value.strip():
                raise ValueError("Edited non-table paragraphs must contain text")
            if old != value:
                changes[block_id] = value
                patches.append((ordinal, old, value))
        source = edit_docx_paragraphs(base.original_path or "", patches) if patches else read_original(base)
        return source, changes, bool(changes)
    except (OSError, ValueError) as exc:
        raise ReviewError(422, str(exc)) from exc


def read_draft(db: Session, ws_id: str, asset_id: str, user_id: str) -> AssetDraftResponse | None:
    asset = _asset(db, ws_id, asset_id, user_id)
    draft = db.get(SddAssetDocumentDraft, (asset.id, user_id))
    return _response(_base(db, asset, draft.base_version_id), draft) if draft else None


def read_draft_docx(db: Session, ws_id: str, asset_id: str, user_id: str, revision: int) -> bytes:
    asset = _asset(db, ws_id, asset_id, user_id)
    draft = db.get(SddAssetDocumentDraft, (asset.id, user_id))
    if not draft:
        raise ReviewError(404, "Draft not found")
    if draft.revision != revision:
        raise ReviewError(409, "This draft changed. Reopen it to load the latest saved changes")
    base = _base(db, asset, draft.base_version_id)
    if base.original_ext != ".docx":
        raise ReviewError(404, "DOCX draft not found")
    return _prepare_source(base, None, draft.docx_edits)[0]


def save_draft(db: Session, ws_id: str, asset_id: str, user_id: str, data: AssetDraftSave) -> AssetDraftResponse:
    asset = _asset(db, ws_id, asset_id, user_id, lock=True)
    policy._ensure_spec_editable(asset)
    draft = db.get(SddAssetDocumentDraft, (asset.id, user_id))
    _check_state(draft, data)
    if draft is None and data.base_version_id != asset.active_version_id:
        raise ReviewError(409, "The published version changed. Reopen the document to start a draft")
    base = _base(db, asset, data.base_version_id)
    source, edits, _ = _prepare_source(base, data.text, data.docx_edits)
    if draft is None:
        draft = SddAssetDocumentDraft(asset_id=asset.id, author_id=user_id, base_version_id=base.id)
        db.add(draft)
    draft.revision = data.revision + 1
    draft.text = data.text
    draft.docx_edits = edits
    db.flush()
    return _response(base, draft, source)


def discard_draft(db: Session, ws_id: str, asset_id: str, user_id: str, data: AssetDraftState) -> None:
    asset = _asset(db, ws_id, asset_id, user_id, lock=True)
    draft = db.get(SddAssetDocumentDraft, (asset.id, user_id))
    _check_state(draft, data)
    if draft:
        db.delete(draft)


def publish_draft(
    db: Session, ws_id: str, asset_id: str, user_id: str, data: AssetDraftState
) -> tuple[SddAssetVersion, str]:
    asset = _asset(db, ws_id, asset_id, user_id, lock=True)
    policy._ensure_spec_editable(asset)
    draft = db.get(SddAssetDocumentDraft, (asset.id, user_id))
    _check_state(draft, data)
    if not draft:
        raise ReviewError(404, "Save the draft before publishing")
    if data.base_version_id != asset.active_version_id:
        raise ReviewError(409, "The published version changed. Your draft is saved")
    base = _base(db, asset, draft.base_version_id)
    source, _, changed = _prepare_source(base, draft.text, draft.docx_edits)
    if not changed:
        raise ReviewError(422, "This draft has no changes to publish")
    try:
        version = versioning.create_asset_version_from_source(db, asset, base, source, user_id)
    except transactions.DocumentVersionConflict as exc:
        raise ReviewError(409, str(exc)) from exc
    if version.original_ext == ".docx":
        asset_discussion_service.sync_docx_comments_to_threads(db, asset=asset, version=base)
        version.render_json = {**version.render_json, "docx_comments_inherited": True}
    inherit_anchors(db, base, version, user_id)
    task = asset.task
    task_cli_state_service.upsert_bootstrap_for_upload(
        db, workspace_id=ws_id, task_id=task.id, spec_asset_id=asset.id, spec_version_id=version.id
    )
    task_cli_state_service.invalidate_bootstrap(db, workspace_id=ws_id, task_id=task.id, spec_version_id=version.id)
    db.delete(draft)
    db.flush()
    path = Path(version.original_path).resolve()
    task.spec_doc_path = (
        materialize_file(task, f".sdd/spec/{version.id}/{path.name}", source) if is_local(task) else str(path)
    )
    return version, task.id
