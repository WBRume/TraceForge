"""
Workspace Assets domain models.

These tables describe the minimum durable boundary for development-time
assets. Traceability remains a derived read-only view and is intentionally
not modeled as a persisted source asset.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    JSON,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


def _enum_values(values):
    return [value.value for value in values]


class RequirementStatus(str, PyEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"
    WAITING_SOURCE = "WAITING_SOURCE"


class RequirementImportBatchStatus(str, PyEnum):
    PREVIEW = "PREVIEW"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class RequirementImportItemStatus(str, PyEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SKIPPED = "SKIPPED"


class RequirementAuditAction(str, PyEnum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    LINKED_TASK = "LINKED_TASK"
    UNLINKED_TASK = "UNLINKED_TASK"
    IMPORT_PREVIEW_CREATED = "IMPORT_PREVIEW_CREATED"
    IMPORT_CONFIRMED = "IMPORT_CONFIRMED"
    SPLIT_PREVIEW_CREATED = "SPLIT_PREVIEW_CREATED"
    SPLIT_CONFIRMED = "SPLIT_CONFIRMED"


class TaskRequirementRelationType(str, PyEnum):
    RELATES_TO = "RELATES_TO"
    COVERS = "COVERS"


class WorkspaceAssetRecordStatus(str, PyEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AiOutputType(str, PyEnum):
    TEXT = "TEXT"
    PATCH = "PATCH"
    PLAN = "PLAN"
    SPEC = "SPEC"
    LOG = "LOG"
    OTHER = "OTHER"


class HumanReviewStatus(str, PyEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    NEED_CLARIFICATION = "NEED_CLARIFICATION"
    NEED_EVIDENCE = "NEED_EVIDENCE"
    REJECTED = "REJECTED"
    REOPENED = "REOPENED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class HumanReviewOutcome(str, PyEnum):
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_MODIFICATION = "ACCEPT_WITH_MODIFICATION"
    REJECT = "REJECT"
    NEED_EVIDENCE = "NEED_EVIDENCE"
    NEED_CLARIFICATION = "NEED_CLARIFICATION"


class HumanDeltaStatus(str, PyEnum):
    PENDING = "PENDING"
    COMPARING = "COMPARING"
    READY = "READY"
    SUPERSEDED = "SUPERSEDED"


class DeltaRegionType(str, PyEnum):
    FILE_ADDED = "FILE_ADDED"
    FILE_DELETED = "FILE_DELETED"
    FILE_RENAMED = "FILE_RENAMED"
    FILE_REWRITTEN = "FILE_REWRITTEN"
    HUNK_MODIFIED = "HUNK_MODIFIED"
    LINE_DIVERGED = "LINE_DIVERGED"


class DeltaRegionSource(str, PyEnum):
    AI_ONLY = "AI_ONLY"
    HUMAN_ONLY = "HUMAN_ONLY"
    BOTH_SAME = "BOTH_SAME"
    DIVERGED = "DIVERGED"


class EvidenceSourceType(str, PyEnum):
    COMMIT = "COMMIT"
    MR = "MR"
    DIFF = "DIFF"
    FILE_PATH = "FILE_PATH"
    TEST_REPORT = "TEST_REPORT"
    REVIEW_RECORD = "REVIEW_RECORD"
    RUN_LOG = "RUN_LOG"
    HUMAN_CONFIRMATION = "HUMAN_CONFIRMATION"
    OTHER = "OTHER"


class EvidenceStatus(str, PyEnum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    INVALID = "INVALID"


class EvidenceType(str, PyEnum):
    CODE = "CODE"
    TEST = "TEST"
    RUNTIME = "RUNTIME"
    REVIEW = "REVIEW"
    DECISION = "DECISION"
    AI = "AI"
    BUSINESS = "BUSINESS"
    FAILURE = "FAILURE"


class DecisionStatus(str, PyEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DecisionSourceType(str, PyEnum):
    CHAT_MESSAGE = "CHAT_MESSAGE"
    SPEC_PLAN_CHANGE = "SPEC_PLAN_CHANGE"
    TASK_CLOSEOUT = "TASK_CLOSEOUT"
    TASK_DETAIL_BACKFILL = "TASK_DETAIL_BACKFILL"


class ClarificationStatus(str, PyEnum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class ClarificationBlockingLevel(str, PyEnum):
    BLOCKING = "BLOCKING"
    NON_BLOCKING = "NON_BLOCKING"


class TaskFinalStatus(str, PyEnum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"


class TaskProcessRecordType(str, PyEnum):
    HUMAN_REVIEW = "HUMAN_REVIEW"
    HUMAN_REVIEW_COMMENT = "HUMAN_REVIEW_COMMENT"
    HUMAN_DELTA = "HUMAN_DELTA"
    EVIDENCE = "EVIDENCE"
    DECISION = "DECISION"
    CLARIFICATION = "CLARIFICATION"
    FINAL_SUMMARY = "FINAL_SUMMARY"
    TASK_BASELINE = "TASK_BASELINE"


class TaskProcessAuditAction(str, PyEnum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    COMMENTED = "COMMENTED"
    FINALIZED = "FINALIZED"


class KnowledgeAssetType(str, PyEnum):
    BUSINESS_CONCEPT = "BUSINESS_CONCEPT"
    API_USAGE_CARD = "API_USAGE_CARD"
    FRAMEWORK_PATTERN = "FRAMEWORK_PATTERN"
    CONSTRAINT_RULE = "CONSTRAINT_RULE"
    REUSABLE_ADR = "REUSABLE_ADR"


class KnowledgeAssetStatus(str, PyEnum):
    DRAFT = "DRAFT"
    PROMOTED = "PROMOTED"
    ARCHIVED = "ARCHIVED"


class SddRequirement(Base):
    __tablename__ = "sdd_requirements"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=True)
    status = Column(
        Enum(RequirementStatus, values_callable=_enum_values),
        nullable=False,
        default=RequirementStatus.WAITING_SOURCE,
        index=True,
    )
    acceptance_criteria_json = Column(JSON, nullable=True)
    priority = Column(String(40), nullable=True)
    parent_requirement_id = Column(
        String(36),
        ForeignKey("sdd_requirements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    import_batch_id = Column(
        String(36),
        ForeignKey("sdd_requirement_import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_kind = Column(String(80), nullable=True)
    source_uri = Column(String(1000), nullable=True)
    source_ref = Column(String(300), nullable=True)
    source_metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="requirements")
    creator = relationship("User", foreign_keys=[created_by_id])
    parent_requirement = relationship("SddRequirement", remote_side=[id], back_populates="child_requirements")
    child_requirements = relationship("SddRequirement", back_populates="parent_requirement")
    import_batch = relationship("SddRequirementImportBatch", back_populates="requirements")
    task_links = relationship("SddTaskRequirement", back_populates="requirement", cascade="all, delete-orphan")
    evidence_items = relationship("SddEvidence", back_populates="requirement")
    audit_logs = relationship(
        "SddRequirementAuditLog",
        back_populates="requirement",
        cascade="all, delete-orphan",
        order_by="SddRequirementAuditLog.created_at.desc()",
    )


class SddRequirementImportBatch(Base):
    __tablename__ = "sdd_requirement_import_batches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    source_kind = Column(String(80), nullable=True)
    source_filename = Column(String(500), nullable=True)
    source_uri = Column(String(1000), nullable=True)
    source_ref = Column(String(300), nullable=True)
    source_metadata_json = Column(JSON, nullable=True)
    normalized_markdown = Column(Text, nullable=True)
    status = Column(
        Enum(RequirementImportBatchStatus, values_callable=_enum_values),
        nullable=False,
        default=RequirementImportBatchStatus.PREVIEW,
        index=True,
    )
    item_count = Column(Integer, nullable=False, default=0)
    confirmed_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace")
    creator = relationship("User", foreign_keys=[created_by_id])
    items = relationship(
        "SddRequirementImportItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="SddRequirementImportItem.order_index.asc()",
    )
    requirements = relationship("SddRequirement", back_populates="import_batch")
    audit_logs = relationship("SddRequirementAuditLog", back_populates="import_batch")


class SddRequirementImportItem(Base):
    __tablename__ = "sdd_requirement_import_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(
        String(36),
        ForeignKey("sdd_requirement_import_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_id = Column(
        String(36),
        ForeignKey("sdd_requirements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=True)
    acceptance_criteria_json = Column(JSON, nullable=True)
    priority = Column(String(40), nullable=True)
    source_ref = Column(String(300), nullable=True)
    source_metadata_json = Column(JSON, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    status = Column(
        Enum(RequirementImportItemStatus, values_callable=_enum_values),
        nullable=False,
        default=RequirementImportItemStatus.PENDING,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    batch = relationship("SddRequirementImportBatch", back_populates="items")
    requirement = relationship("SddRequirement")


class SddRequirementAuditLog(Base):
    __tablename__ = "sdd_requirement_audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id = Column(
        String(36),
        ForeignKey("sdd_requirements.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    import_batch_id = Column(
        String(36),
        ForeignKey("sdd_requirement_import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(Enum(RequirementAuditAction, values_callable=_enum_values), nullable=False, index=True)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    source_metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    requirement = relationship("SddRequirement", back_populates="audit_logs")
    import_batch = relationship("SddRequirementImportBatch", back_populates="audit_logs")
    task = relationship("SddTask")
    actor = relationship("User", foreign_keys=[actor_id])


class SddTaskRequirement(Base):
    __tablename__ = "sdd_task_requirements"
    __table_args__ = (
        UniqueConstraint("requirement_id", "task_id", name="uq_sdd_task_requirements_requirement_task"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id = Column(
        String(36),
        ForeignKey("sdd_requirements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(
        Enum(TaskRequirementRelationType, values_callable=_enum_values),
        nullable=False,
        default=TaskRequirementRelationType.RELATES_TO,
        index=True,
    )
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    requirement = relationship("SddRequirement", back_populates="task_links")
    task = relationship("SddTask", back_populates="requirement_links")
    creator = relationship("User", foreign_keys=[created_by_id])


class SddAiOutput(Base):
    __tablename__ = "sdd_ai_outputs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    ai_job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    output_type = Column(
        Enum(AiOutputType, values_callable=_enum_values),
        nullable=False,
        default=AiOutputType.TEXT,
        index=True,
    )
    title = Column(String(300), nullable=True)
    content_text = Column(Text, nullable=True)
    content_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="ai_outputs")
    ai_job = relationship("SddAiJob", back_populates="outputs")
    asset = relationship("SddAsset")
    asset_version = relationship("SddAssetVersion")


class SddHumanReview(Base):
    __tablename__ = "sdd_human_reviews"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    status = Column(
        Enum(HumanReviewStatus, values_callable=_enum_values),
        nullable=False,
        default=HumanReviewStatus.OPEN,
        index=True,
    )
    outcome = Column(Enum(HumanReviewOutcome, values_callable=_enum_values), nullable=True, index=True)
    review_type = Column(String(80), nullable=True)
    review_scope = Column(String(80), nullable=True)
    priority = Column(String(40), nullable=True)
    title = Column(String(300), nullable=True)
    body = Column(Text, nullable=True)
    source_ref_json = Column(JSON, nullable=True)
    target_ref_json = Column(JSON, nullable=True)
    due_date = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="human_reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
    comments = relationship(
        "SddHumanReviewComment",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="SddHumanReviewComment.created_at.asc()",
    )
    evidence_items = relationship("SddEvidence", back_populates="human_review")
    clarification_links = relationship(
        "SddReviewClarificationLink",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="SddReviewClarificationLink.created_at.asc()",
    )


class SddHumanReviewComment(Base):
    __tablename__ = "sdd_human_review_comments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    review_id = Column(String(36), ForeignKey("sdd_human_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    comment_type = Column(String(80), nullable=True)
    body = Column(Text, nullable=False)
    required_change_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="human_review_comments")
    review = relationship("SddHumanReview", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id])


class SddReviewClarificationLink(Base):
    __tablename__ = "sdd_review_clarification_links"
    __table_args__ = (
        UniqueConstraint("review_id", "clarification_id", name="uq_sdd_review_clarification_links_review_clarification"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    review_id = Column(String(36), ForeignKey("sdd_human_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    clarification_id = Column(String(36), ForeignKey("sdd_clarifications.id", ondelete="CASCADE"), nullable=False, index=True)
    link_type = Column(String(80), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    review = relationship("SddHumanReview", back_populates="clarification_links")
    clarification = relationship("SddClarification", back_populates="review_links")


class SddHumanDelta(Base):
    __tablename__ = "sdd_human_deltas"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    # --- Core references ---
    proposal_id = Column(String(36), ForeignKey("sdd_task_change_proposals.id", ondelete="SET NULL"), nullable=True, index=True)
    final_evidence_id = Column(String(36), ForeignKey("sdd_evidence.id", ondelete="SET NULL"), nullable=True, index=True)

    # --- Status ---
    status = Column(
        Enum(HumanDeltaStatus, values_callable=_enum_values),
        nullable=False,
        default=HumanDeltaStatus.PENDING,
        index=True,
    )

    # --- Comparison result ---
    diff_asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    changed_files_count = Column(Integer, nullable=True)
    insertions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)
    comparison_summary = Column(Text, nullable=True)

    # --- Cache ---
    ai_patch_hash = Column(String(64), nullable=True)
    human_patch_hash = Column(String(64), nullable=True)

    # --- Metadata ---
    change_category = Column(String(100), nullable=True)
    change_reason = Column(Text, nullable=True)
    promote_candidate = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="human_deltas")
    proposal = relationship("SddTaskChangeProposal", foreign_keys=[proposal_id])
    final_evidence = relationship("SddEvidence", foreign_keys=[final_evidence_id])
    diff_asset = relationship("SddAsset", foreign_keys=[diff_asset_id])
    creator = relationship("User", foreign_keys=[created_by_id])
    decisions = relationship("SddDecision", back_populates="human_delta")
    regions = relationship("SddDeltaRegion", back_populates="delta", cascade="all, delete-orphan")


class SddDeltaRegion(Base):
    __tablename__ = "sdd_delta_regions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    delta_id = Column(String(36), ForeignKey("sdd_human_deltas.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String(1000), nullable=False)
    old_file_path = Column(String(1000), nullable=True)
    region_type = Column(
        Enum(DeltaRegionType, values_callable=_enum_values),
        nullable=False,
    )
    region_source = Column(
        Enum(DeltaRegionSource, values_callable=_enum_values),
        nullable=False,
    )
    ai_line_start = Column(Integer, nullable=True)
    ai_line_end = Column(Integer, nullable=True)
    human_line_start = Column(Integer, nullable=True)
    human_line_end = Column(Integer, nullable=True)
    ai_insertions = Column(Integer, nullable=False, default=0)
    ai_deletions = Column(Integer, nullable=False, default=0)
    human_insertions = Column(Integer, nullable=False, default=0)
    human_deletions = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    delta = relationship("SddHumanDelta", back_populates="regions")
    decisions = relationship("SddDecision", back_populates="delta_region")


class SddEvidence(Base):
    __tablename__ = "sdd_evidence"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id = Column(
        String(36),
        ForeignKey("sdd_requirements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    ai_job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    human_review_id = Column(
        String(36),
        ForeignKey("sdd_human_reviews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    confirmed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    status = Column(
        Enum(EvidenceStatus, values_callable=_enum_values),
        nullable=False,
        default=EvidenceStatus.UNCONFIRMED,
        index=True,
    )
    evidence_type = Column(
        Enum(EvidenceType, values_callable=_enum_values),
        nullable=False,
        default=EvidenceType.CODE,
        index=True,
    )
    source_type = Column(
        Enum(EvidenceSourceType, values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    source_uri = Column(String(1000), nullable=True)
    source_label = Column(String(300), nullable=True)
    source_ref = Column(String(300), nullable=True)
    source_path = Column(String(1000), nullable=True)
    source_metadata_json = Column(JSON, nullable=True)
    title = Column(String(300), nullable=True)
    summary = Column(Text, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    requirement = relationship("SddRequirement", back_populates="evidence_items")
    task = relationship("SddTask", back_populates="evidence_items")
    ai_job = relationship("SddAiJob", back_populates="evidence_items")
    human_review = relationship("SddHumanReview", back_populates="evidence_items")
    creator = relationship("User", foreign_keys=[created_by_id])
    confirmed_by = relationship("User", foreign_keys=[confirmed_by_id])
    decisions = relationship("SddDecision", back_populates="source_evidence")
    clarifications = relationship("SddClarification", back_populates="source_evidence")


class SddDecision(Base):
    __tablename__ = "sdd_decisions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id = Column(String(36), ForeignKey("sdd_requirements.id", ondelete="SET NULL"), nullable=True, index=True)
    human_delta_id = Column(String(36), ForeignKey("sdd_human_deltas.id", ondelete="SET NULL"), nullable=True, index=True)
    delta_region_id = Column(String(36), ForeignKey("sdd_delta_regions.id", ondelete="SET NULL"), nullable=True, index=True)
    decided_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    source_evidence_id = Column(String(36), ForeignKey("sdd_evidence.id", ondelete="SET NULL"), nullable=True)
    source_chat_message_id = Column(String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    source_asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    source_asset_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_asset_thread_id = Column(
        String(36),
        ForeignKey("sdd_asset_threads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_resolution_proposal_id = Column(
        String(36),
        ForeignKey("sdd_asset_resolution_proposals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_final_summary_id = Column(
        String(36),
        ForeignKey("sdd_task_final_summaries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        Enum(DecisionStatus, values_callable=_enum_values),
        nullable=False,
        default=DecisionStatus.PROPOSED,
        index=True,
    )
    source_type = Column(
        Enum(DecisionSourceType, values_callable=_enum_values),
        nullable=False,
        default=DecisionSourceType.TASK_DETAIL_BACKFILL,
        index=True,
    )
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    impact_scope = Column(String(300), nullable=True)
    promote_candidate = Column(Boolean, nullable=False, default=False)
    source_metadata_json = Column(JSON, nullable=True)
    delta_line_refs_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="decisions")
    requirement = relationship("SddRequirement")
    human_delta = relationship("SddHumanDelta", back_populates="decisions")
    delta_region = relationship("SddDeltaRegion", back_populates="decisions")
    decided_by = relationship("User", foreign_keys=[decided_by_id])
    source_evidence = relationship("SddEvidence", back_populates="decisions")
    source_chat_message = relationship("ChatMessage")
    source_asset = relationship("SddAsset", foreign_keys=[source_asset_id])
    source_asset_version = relationship("SddAssetVersion", foreign_keys=[source_asset_version_id])
    source_asset_thread = relationship("SddAssetThread", foreign_keys=[source_asset_thread_id])
    source_resolution_proposal = relationship("SddAssetResolutionProposal", foreign_keys=[source_resolution_proposal_id])
    source_final_summary = relationship("SddTaskFinalSummary", foreign_keys=[source_final_summary_id])


class SddClarification(Base):
    __tablename__ = "sdd_clarifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id = Column(String(36), ForeignKey("sdd_requirements.id", ondelete="SET NULL"), nullable=True, index=True)
    requester_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    responder_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    source_evidence_id = Column(String(36), ForeignKey("sdd_evidence.id", ondelete="SET NULL"), nullable=True)
    source_review_id = Column(String(36), ForeignKey("sdd_human_reviews.id", ondelete="SET NULL"), nullable=True, index=True)
    converted_requirement_id = Column(
        String(36),
        ForeignKey("sdd_requirements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        Enum(ClarificationStatus, values_callable=_enum_values),
        nullable=False,
        default=ClarificationStatus.OPEN,
        index=True,
    )
    blocking_level = Column(
        Enum(ClarificationBlockingLevel, values_callable=_enum_values),
        nullable=False,
        default=ClarificationBlockingLevel.NON_BLOCKING,
        index=True,
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    clarification_type = Column(String(80), nullable=True)
    target_ref_json = Column(JSON, nullable=True)
    urgency = Column(String(40), nullable=True)
    answered_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    promote_candidate = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="clarifications")
    requirement = relationship("SddRequirement", foreign_keys=[requirement_id])
    converted_requirement = relationship("SddRequirement", foreign_keys=[converted_requirement_id])
    requester = relationship("User", foreign_keys=[requester_id])
    responder = relationship("User", foreign_keys=[responder_id])
    source_evidence = relationship("SddEvidence", back_populates="clarifications")
    source_review = relationship("SddHumanReview", foreign_keys=[source_review_id])
    review_links = relationship(
        "SddReviewClarificationLink",
        back_populates="clarification",
        cascade="all, delete-orphan",
        order_by="SddReviewClarificationLink.created_at.asc()",
    )
    threads = relationship(
        "SddClarificationThread",
        back_populates="clarification",
        cascade="all, delete-orphan",
        order_by="SddClarificationThread.created_at.asc()",
    )


class SddClarificationThread(Base):
    __tablename__ = "sdd_clarification_threads"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    clarification_id = Column(String(36), ForeignKey("sdd_clarifications.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    entry_type = Column(String(40), nullable=False, default="COMMENT")
    body = Column(Text, nullable=False)
    is_answer = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    clarification = relationship("SddClarification", back_populates="threads")
    author = relationship("User", foreign_keys=[author_id])


class SddTaskFinalSummary(Base):
    __tablename__ = "sdd_task_final_summaries"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_sdd_task_final_summaries_task"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    final_status = Column(
        Enum(TaskFinalStatus, values_callable=_enum_values),
        nullable=False,
        default=TaskFinalStatus.PENDING,
        index=True,
    )
    summary = Column(Text, nullable=True)
    remaining_risk = Column(Text, nullable=True)
    next_steps = Column(Text, nullable=True)
    final_evidence_ids_json = Column(JSON, nullable=True)
    review_checklist_json = Column(JSON, nullable=True)
    clarification_summary_json = Column(JSON, nullable=True)
    delta_summary_json = Column(JSON, nullable=True)
    decision_summary_json = Column(JSON, nullable=True)
    human_confirmation_review_id = Column(
        String(36),
        ForeignKey("sdd_human_reviews.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at = Column(DateTime, nullable=True)
    verified_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="final_summary")
    author = relationship("User", foreign_keys=[author_id])
    verified_by = relationship("User", foreign_keys=[verified_by_id])
    human_confirmation_review = relationship("SddHumanReview", foreign_keys=[human_confirmation_review_id])


class SddTaskBaseline(Base):
    __tablename__ = "sdd_task_baselines"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_sdd_task_baselines_task_version"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_id = Column(String(36), ForeignKey("sdd_task_final_summaries.id", ondelete="SET NULL"), nullable=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    snapshot_json = Column(JSON, nullable=True)
    baselined_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    is_rollback = Column(Boolean, nullable=False, default=False)
    rollback_from_version = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="baselines")
    summary = relationship("SddTaskFinalSummary", foreign_keys=[summary_id])
    baselined_by = relationship("User", foreign_keys=[baselined_by_id])


class SddTaskProcessAuditLog(Base):
    __tablename__ = "sdd_task_process_audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    record_type = Column(Enum(TaskProcessRecordType, values_callable=_enum_values), nullable=False, index=True)
    record_id = Column(String(36), nullable=False, index=True)
    action = Column(Enum(TaskProcessAuditAction, values_callable=_enum_values), nullable=False, index=True)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="process_audit_logs")
    actor = relationship("User", foreign_keys=[actor_id])


class SddKnowledgeAsset(Base):
    __tablename__ = "sdd_knowledge_assets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    promoted_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    source_task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    source_decision_id = Column(String(36), ForeignKey("sdd_decisions.id", ondelete="SET NULL"), nullable=True)
    source_human_delta_id = Column(String(36), ForeignKey("sdd_human_deltas.id", ondelete="SET NULL"), nullable=True)
    source_clarification_id = Column(
        String(36),
        ForeignKey("sdd_clarifications.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_review_id = Column(String(36), ForeignKey("sdd_human_reviews.id", ondelete="SET NULL"), nullable=True)
    source_evidence_id = Column(String(36), ForeignKey("sdd_evidence.id", ondelete="SET NULL"), nullable=True)
    asset_type = Column(
        Enum(KnowledgeAssetType, values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    status = Column(
        Enum(KnowledgeAssetStatus, values_callable=_enum_values),
        nullable=False,
        default=KnowledgeAssetStatus.DRAFT,
        index=True,
    )
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="knowledge_assets")
    promoted_by = relationship("User", foreign_keys=[promoted_by_id])
    source_task = relationship("SddTask")
    source_decision = relationship("SddDecision")
    source_human_delta = relationship("SddHumanDelta")
    source_clarification = relationship("SddClarification")
    source_review = relationship("SddHumanReview")
    source_evidence = relationship("SddEvidence")
