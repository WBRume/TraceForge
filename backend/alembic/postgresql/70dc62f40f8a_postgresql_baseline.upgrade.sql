CREATE EXTENSION IF NOT EXISTS pg_jieba WITH SCHEMA public;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TYPE aijobchannel AS ENUM ('ASSET_THREAD', 'TASK_CHAT', 'BACKGROUND');

CREATE TYPE aijobstatus AS ENUM ('PENDING', 'RUNNING', 'WAITING_HITL', 'INTERRUPTED', 'TERMINATING', 'ORPHANED', 'SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED');

CREATE TYPE aioutputtype AS ENUM ('TEXT', 'PATCH', 'PLAN', 'SPEC', 'LOG', 'OTHER');

CREATE TYPE apimockcollabeventtype AS ENUM ('DRAFT', 'SAVE', 'CONFLICT', 'PRESENCE');

CREATE TYPE apimockrulemode AS ENUM ('STATIC', 'MOCKJS', 'PROXY');

CREATE TYPE assetresolutionproposalstatus AS ENUM ('draft', 'applied', 'discarded');

CREATE TYPE assetthreadmessagerole AS ENUM ('user', 'ai', 'system');

CREATE TYPE assetthreadstatus AS ENUM ('open', 'resolved', 'closed');

CREATE TYPE assettype AS ENUM ('SPEC', 'PROMPT', 'DESIGN_DOC', 'PLAN', 'CODE_DIFF', 'UT_REPORT', 'E2E_REPORT', 'ERROR_STACK', 'DIAGNOSIS_DOC');

CREATE TYPE changeproposalfiletype AS ENUM ('added', 'modified', 'deleted', 'renamed');

CREATE TYPE changeproposalstatus AS ENUM ('draft', 'generated', 'downloaded', 'applied', 'conflict', 'verified', 'rejected');

CREATE TYPE clarificationblockinglevel AS ENUM ('BLOCKING', 'NON_BLOCKING');

CREATE TYPE clarificationstatus AS ENUM ('OPEN', 'ANSWERED', 'ACCEPTED', 'REJECTED', 'CANCELLED', 'CLOSED');

CREATE TYPE contexttokencategory AS ENUM ('TASK_PROMPT', 'SPEC_DOCS', 'RUNTIME_SKILLS', 'SUPERPOWERS_RULES', 'TOOL_INPUT', 'TOOL_RESULT', 'THINKING', 'HISTORY', 'HITL');

CREATE TYPE decisionsourcetype AS ENUM ('CHAT_MESSAGE', 'SPEC_PLAN_CHANGE', 'TASK_CLOSEOUT', 'TASK_DETAIL_BACKFILL');

CREATE TYPE decisionstatus AS ENUM ('PROPOSED', 'ACCEPTED', 'REJECTED', 'SUPERSEDED');

CREATE TYPE deltaregionsource AS ENUM ('AI_ONLY', 'HUMAN_ONLY', 'BOTH_SAME', 'DIVERGED');

CREATE TYPE deltaregiontype AS ENUM ('FILE_ADDED', 'FILE_DELETED', 'FILE_RENAMED', 'FILE_REWRITTEN', 'HUNK_MODIFIED', 'LINE_DIVERGED');

CREATE TYPE evidencesourcetype AS ENUM ('COMMIT', 'MR', 'DIFF', 'FILE_PATH', 'TEST_REPORT', 'REVIEW_RECORD', 'RUN_LOG', 'HUMAN_CONFIRMATION', 'OTHER');

CREATE TYPE evidencestatus AS ENUM ('UNCONFIRMED', 'CONFIRMED', 'INVALID');

CREATE TYPE evidencetype AS ENUM ('CODE', 'TEST', 'RUNTIME', 'REVIEW', 'DECISION', 'AI', 'BUSINESS', 'FAILURE');

CREATE TYPE humandeltastatus AS ENUM ('PENDING', 'COMPARING', 'READY', 'SUPERSEDED');

CREATE TYPE humanreviewoutcome AS ENUM ('ACCEPT', 'ACCEPT_WITH_MODIFICATION', 'REJECT', 'NEED_EVIDENCE', 'NEED_CLARIFICATION');

CREATE TYPE humanreviewstatus AS ENUM ('OPEN', 'IN_REVIEW', 'NEED_CLARIFICATION', 'NEED_EVIDENCE', 'REJECTED', 'REOPENED', 'RESOLVED', 'CLOSED');

CREATE TYPE knowledgeassetstatus AS ENUM ('DRAFT', 'PROMOTED', 'ARCHIVED');

CREATE TYPE knowledgeassettype AS ENUM ('BUSINESS_CONCEPT', 'API_USAGE_CARD', 'FRAMEWORK_PATTERN', 'CONSTRAINT_RULE', 'REUSABLE_ADR');

CREATE TYPE logtype AS ENUM ('STDOUT', 'STDERR', 'STATUS', 'HITL_REQUEST', 'HITL_RESPONSE', 'AGENT_STATE');

CREATE TYPE messagerole AS ENUM ('user', 'assistant', 'system');

CREATE TYPE messagetype AS ENUM ('text', 'thinking', 'plan_card', 'progress_card', 'test_report_card', 'hitl_boolean', 'hitl_select', 'file_upload', 'error', 'init_reason', 'diagnosis_result');

CREATE TYPE phase AS ENUM ('BRAINSTORM', 'GIT_WORKTREE', 'PLAN', 'CODE', 'UT', 'CODE_REVIEW', 'BUILD', 'E2E_UI', 'E2E_API');

CREATE TYPE plannodestatus AS ENUM ('PENDING', 'RUNNING', 'PASSED', 'FAILED', 'SKIPPED');

CREATE TYPE preinputeditpermission AS ENUM ('ALL', 'MENTIONED', 'EXPERTS', 'NONE');

CREATE TYPE preinputstatus AS ENUM ('COLLECTING', 'SUBMITTED', 'CANCELLED');

CREATE TYPE productstatus AS ENUM ('ACTIVE', 'ARCHIVED');

CREATE TYPE producttype AS ENUM ('OOTB', 'CUSTOM');

CREATE TYPE productversionstatus AS ENUM ('PLANNED', 'ACTIVE', 'EOL');

CREATE TYPE projectlifecyclestatus AS ENUM ('INITIATED', 'DEVELOPING', 'DELIVERING', 'MAINTAINING', 'RETIRED');

CREATE TYPE provisionjobtype AS ENUM ('CREATE_WORKSPACE', 'CREATE_TASK', 'IMPORT_SKILL', 'SYNC_REPO_REFS');

CREATE TYPE releaserepokind AS ENUM ('OOTB', 'CUSTOM');

CREATE TYPE releasestatus AS ENUM ('DRAFT', 'PUBLISHED', 'RETIRED');

CREATE TYPE reporeftype AS ENUM ('BRANCH', 'TAG');

CREATE TYPE repositorytype AS ENUM ('OOTB', 'CUSTOM');

CREATE TYPE requirementauditaction AS ENUM ('CREATED', 'UPDATED', 'STATUS_CHANGED', 'LINKED_TASK', 'UNLINKED_TASK', 'IMPORT_PREVIEW_CREATED', 'IMPORT_CONFIRMED', 'SPLIT_PREVIEW_CREATED', 'SPLIT_CONFIRMED');

CREATE TYPE requirementimportbatchstatus AS ENUM ('PREVIEW', 'CONFIRMED', 'CANCELLED');

CREATE TYPE requirementimportitemstatus AS ENUM ('PENDING', 'CONFIRMED', 'SKIPPED');

CREATE TYPE requirementstatus AS ENUM ('DRAFT', 'ACTIVE', 'READY', 'IN_PROGRESS', 'VERIFIED', 'REJECTED', 'ARCHIVED', 'WAITING_SOURCE');

CREATE TYPE skillanalysisrefkind AS ENUM ('WORKTREE', 'LATEST', 'VERSION');

CREATE TYPE skilldimension AS ENUM ('GLOBAL', 'WORKSPACE');

CREATE TYPE skillrisklevel AS ENUM ('LOW', 'MEDIUM', 'HIGH');

CREATE TYPE skillruntimeeventstatus AS ENUM ('PENDING', 'RESULT_RETURNED', 'FAILED');

CREATE TYPE skillruntimeeventtype AS ENUM ('ENTRY_READ', 'FILE_READ', 'DIR_LIST', 'FILE_SEARCH', 'SCRIPT_EXEC', 'FILE_WRITE', 'TOOL_RESULT', 'USAGE_CONFIRMED');

CREATE TYPE skillruntimeevidencelevel AS ENUM ('EXACT_PATH', 'COMMAND_PATH', 'RESULT_LINKED');

CREATE TYPE taskclibootstrapstatus AS ENUM ('PENDING', 'RUNNING', 'READY', 'FAILED', 'STALE');

CREATE TYPE taskfinalstatus AS ENUM ('PENDING', 'PARTIAL', 'REJECTED', 'VERIFIED');

CREATE TYPE taskprocessauditaction AS ENUM ('CREATED', 'UPDATED', 'COMMENTED', 'FINALIZED');

CREATE TYPE taskprocessrecordtype AS ENUM ('HUMAN_REVIEW', 'HUMAN_REVIEW_COMMENT', 'HUMAN_DELTA', 'EVIDENCE', 'DECISION', 'CLARIFICATION', 'FINAL_SUMMARY', 'TASK_BASELINE');

CREATE TYPE taskrepositorystate AS ENUM ('PENDING', 'READY', 'FAILED');

CREATE TYPE taskrequirementrelationtype AS ENUM ('RELATES_TO', 'COVERS');

CREATE TYPE tasksessionoperationstatus AS ENUM ('REVERTING', 'REVERTED', 'FAILED');

CREATE TYPE tasksessionsharemode AS ENUM ('READ', 'INPUT');

CREATE TYPE tasksessionturnstatus AS ENUM ('ACTIVE', 'REVERTING', 'REVERTED');

CREATE TYPE tasksharesuggestionstatus AS ENUM ('PENDING', 'ADOPTED', 'DISMISSED');

CREATE TYPE taskstatus AS ENUM ('PROVISIONING', 'INITIALIZED', 'RUNNING', 'ROUND_COMPLETED', 'AWAITING_INPUT', 'INTERRUPTED', 'COMPLETED', 'FAILED');

CREATE TYPE teststatus AS ENUM ('PASS', 'FAIL', 'ERROR', 'SKIP');

CREATE TYPE testtype AS ENUM ('UT', 'E2E_UI', 'E2E_API', 'E2E_FULL');

CREATE TYPE verificationrunstatus AS ENUM ('running', 'success', 'failed', 'conflict', 'cancelled');

CREATE TYPE workspacerepositorystate AS ENUM ('PENDING', 'READY', 'FAILED');

CREATE TYPE workspacerole AS ENUM ('OWNER', 'DEVELOPER', 'VIEWER');

CREATE TABLE feature_configs (
    feature VARCHAR(40) NOT NULL,
    encrypted_values TEXT NOT NULL,
    revision INTEGER NOT NULL,
    agent_address_generations JSON,
    updated_by VARCHAR(36),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (feature)
);

CREATE TABLE mgmt_repo_groups (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    parent_id VARCHAR(36),
    order_index INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(parent_id) REFERENCES mgmt_repo_groups (id) ON DELETE CASCADE
);

CREATE INDEX ix_mgmt_repo_groups_parent_id ON mgmt_repo_groups (parent_id);

CREATE TABLE oauth_states (
    id VARCHAR(36) NOT NULL,
    state VARCHAR(64) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    intent VARCHAR(20) NOT NULL,
    client_type VARCHAR(20) NOT NULL,
    user_id VARCHAR(36),
    redirect_uri VARCHAR(500) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    used_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_oauth_states_state UNIQUE (state)
);

CREATE INDEX ix_oauth_states_expires_at ON oauth_states (expires_at);

CREATE TABLE oauth_tickets (
    id VARCHAR(36) NOT NULL,
    ticket VARCHAR(64) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    provider_uid VARCHAR(255) NOT NULL,
    intent VARCHAR(20) NOT NULL,
    client_type VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL,
    user_id VARCHAR(36),
    profile_json TEXT NOT NULL,
    normalized_email VARCHAR(255),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITHOUT TIME ZONE,
    failed_attempts INTEGER DEFAULT '0' NOT NULL,
    locked_until TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_oauth_tickets_ticket UNIQUE (ticket)
);

CREATE INDEX ix_oauth_tickets_expires_at ON oauth_tickets (expires_at);

CREATE INDEX ix_oauth_tickets_normalized_email ON oauth_tickets (normalized_email);

CREATE INDEX ix_oauth_tickets_provider_uid ON oauth_tickets (provider_uid);

CREATE TABLE sdd_local_resource_operations (
    id VARCHAR(64) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    kind VARCHAR(40) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    state VARCHAR(24) NOT NULL,
    result_json JSON,
    binding_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX ix_sdd_local_resource_operations_task_id ON sdd_local_resource_operations (task_id);

CREATE TABLE sdd_rag_outbox (
    id VARCHAR(36) NOT NULL,
    doc_key VARCHAR(200) NOT NULL,
    case_id VARCHAR(36),
    workspace_id VARCHAR(36),
    title VARCHAR(500),
    version INTEGER,
    queue_id VARCHAR(36),
    payload_json JSON NOT NULL,
    status VARCHAR(20) NOT NULL,
    exported_at TIMESTAMP WITHOUT TIME ZONE,
    retry_count INTEGER NOT NULL,
    error_message TEXT,
    next_retry_at TIMESTAMP WITHOUT TIME ZONE,
    locked_until TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX ix_sdd_rag_outbox_case_id ON sdd_rag_outbox (case_id);

CREATE UNIQUE INDEX ix_sdd_rag_outbox_doc_key ON sdd_rag_outbox (doc_key);

CREATE INDEX ix_sdd_rag_outbox_locked_until ON sdd_rag_outbox (locked_until);

CREATE INDEX ix_sdd_rag_outbox_next_retry_at ON sdd_rag_outbox (next_retry_at);

CREATE INDEX ix_sdd_rag_outbox_queue_id ON sdd_rag_outbox (queue_id);

CREATE INDEX ix_sdd_rag_outbox_status ON sdd_rag_outbox (status);

CREATE INDEX ix_sdd_rag_outbox_workspace_id ON sdd_rag_outbox (workspace_id);

CREATE TABLE sdd_rag_sync_queue (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(36),
    status VARCHAR(20) NOT NULL,
    consumed_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_sdd_rag_sync_queue_name ON sdd_rag_sync_queue (name);

CREATE INDEX ix_sdd_rag_sync_queue_status ON sdd_rag_sync_queue (status);

CREATE INDEX ix_sdd_rag_sync_queue_workspace_id ON sdd_rag_sync_queue (workspace_id);

CREATE TABLE sdd_task_deletion_cleanup (
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    resource_profile JSON,
    retry_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (task_id)
);

CREATE INDEX ix_sdd_task_deletion_cleanup_retry_at ON sdd_task_deletion_cleanup (retry_at);

CREATE TABLE sdd_task_session_shares (
    id VARCHAR(36) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    token VARCHAR(64),
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    session_generation INTEGER NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    mode tasksessionsharemode NOT NULL,
    instruction_text TEXT,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoke_reason VARCHAR(200),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX ix_sdd_task_session_shares_creator_id ON sdd_task_session_shares (creator_id);

CREATE INDEX ix_sdd_task_session_shares_task_id ON sdd_task_session_shares (task_id);

CREATE UNIQUE INDEX ix_sdd_task_session_shares_token ON sdd_task_session_shares (token);

CREATE UNIQUE INDEX ix_sdd_task_session_shares_token_hash ON sdd_task_session_shares (token_hash);

CREATE INDEX ix_sdd_task_session_shares_workspace_id ON sdd_task_session_shares (workspace_id);

CREATE INDEX ix_task_session_shares_expires ON sdd_task_session_shares (expires_at);

CREATE INDEX ix_task_session_shares_task_creator_created ON sdd_task_session_shares (task_id, creator_id, created_at);

CREATE TABLE sdd_task_share_accesses (
    id VARCHAR(36) NOT NULL,
    share_id VARCHAR(36) NOT NULL,
    visitor_id VARCHAR(48) NOT NULL,
    access_token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_sdd_task_share_accesses_access_token_hash ON sdd_task_share_accesses (access_token_hash);

CREATE INDEX ix_sdd_task_share_accesses_expires_at ON sdd_task_share_accesses (expires_at);

CREATE INDEX ix_sdd_task_share_accesses_share_id ON sdd_task_share_accesses (share_id);

CREATE TABLE sdd_task_share_suggestions (
    id VARCHAR(36) NOT NULL,
    source_kind VARCHAR(16) DEFAULT 'SHARE' NOT NULL,
    share_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    session_generation INTEGER NOT NULL,
    recipient_user_id VARCHAR(36) NOT NULL,
    visitor_id VARCHAR(48) NOT NULL,
    sender_user_id VARCHAR(36),
    display_name VARCHAR(100),
    original_content TEXT NOT NULL,
    edited_content TEXT,
    client_submission_id VARCHAR(128) NOT NULL,
    status tasksharesuggestionstatus NOT NULL,
    version INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    adopted_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_task_share_suggestion_idem UNIQUE (share_id, visitor_id, client_submission_id)
);

CREATE INDEX ix_sdd_task_share_suggestions_recipient_user_id ON sdd_task_share_suggestions (recipient_user_id);

CREATE INDEX ix_sdd_task_share_suggestions_share_id ON sdd_task_share_suggestions (share_id);

CREATE INDEX ix_sdd_task_share_suggestions_status ON sdd_task_share_suggestions (status);

CREATE INDEX ix_sdd_task_share_suggestions_task_id ON sdd_task_share_suggestions (task_id);

CREATE INDEX ix_task_share_suggestions_recipient_task_status ON sdd_task_share_suggestions (recipient_user_id, task_id, status, created_at);

CREATE TABLE search_backfill_runs (
    id VARCHAR(36) NOT NULL,
    target_id VARCHAR(36) NOT NULL,
    stage VARCHAR(16) NOT NULL,
    boundary TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    cursor JSON,
    processed BIGINT NOT NULL,
    failed INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,
    available_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    lease_token VARCHAR(36),
    lease_until TIMESTAMP WITHOUT TIME ZONE,
    attempts INTEGER NOT NULL,
    last_error_code VARCHAR(80),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id)
);

CREATE TABLE search_document_states (
    entity_key VARCHAR(80) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    source_id VARCHAR(36) NOT NULL,
    source_version BIGINT NOT NULL,
    projection_hash VARCHAR(64),
    deleted BOOLEAN NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (entity_key)
);

CREATE INDEX ix_search_state_task ON search_document_states (task_id, entity_key);

CREATE INDEX ix_search_state_workspace ON search_document_states (workspace_id, entity_key);

CREATE TABLE search_embedding_jobs (
    id VARCHAR(36) NOT NULL,
    target_id VARCHAR(36) NOT NULL,
    profile_id VARCHAR(36) NOT NULL,
    entity_key VARCHAR(80) NOT NULL,
    source_version BIGINT NOT NULL,
    projection_hash VARCHAR(64) NOT NULL,
    input_hash VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    available_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    lease_token VARCHAR(36),
    lease_until TIMESTAMP WITHOUT TIME ZONE,
    attempts INTEGER NOT NULL,
    last_error_code VARCHAR(80),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_search_embedding_version UNIQUE (target_id, entity_key, source_version, profile_id)
);

CREATE INDEX ix_search_embedding_lease ON search_embedding_jobs (status, lease_until, id);

CREATE INDEX ix_search_embedding_pending ON search_embedding_jobs (status, available_at, id);

CREATE TABLE search_embedding_profiles (
    id VARCHAR(36) NOT NULL,
    revision INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,
    endpoint VARCHAR(500) NOT NULL,
    model_id VARCHAR(200) NOT NULL,
    protocol VARCHAR(40) DEFAULT 'openai_compatible' NOT NULL,
    encrypted_api_key TEXT,
    dimension INTEGER,
    chunk_chars INTEGER NOT NULL,
    chunk_overlap INTEGER NOT NULL,
    query_prefix VARCHAR(200) NOT NULL,
    document_prefix VARCHAR(200) NOT NULL,
    fingerprint VARCHAR(64),
    last_error_code VARCHAR(80),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE search_index_targets (
    target_id VARCHAR(36) NOT NULL,
    physical_index VARCHAR(120) NOT NULL,
    connection_fingerprint VARCHAR(64),
    schema_version INTEGER NOT NULL,
    embedding_profile_id VARCHAR(36),
    dimension INTEGER,
    status VARCHAR(16) NOT NULL,
    verified BOOLEAN NOT NULL,
    activation_phase VARCHAR(24),
    activation_token VARCHAR(36),
    activation_until TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (target_id),
    UNIQUE (physical_index)
);

CREATE TABLE search_outbox (
    id BIGSERIAL NOT NULL,
    event_kind VARCHAR(24) NOT NULL,
    entity_key VARCHAR(80),
    source_version BIGINT,
    workspace_id VARCHAR(36),
    task_id VARCHAR(36),
    scan_cursor VARCHAR(160),
    status VARCHAR(16) NOT NULL,
    available_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    lease_token VARCHAR(36),
    lease_until TIMESTAMP WITHOUT TIME ZONE,
    attempts INTEGER NOT NULL,
    last_error_code VARCHAR(80),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_search_outbox_version UNIQUE (event_kind, entity_key, source_version)
);

CREATE INDEX ix_search_outbox_lease ON search_outbox (status, lease_until, id);

CREATE INDEX ix_search_outbox_pending ON search_outbox (status, available_at, id);

CREATE TABLE system_configs (
    key VARCHAR(100) NOT NULL,
    value VARCHAR(500) NOT NULL,
    description VARCHAR(500),
    updated_by VARCHAR(36),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (key)
);

CREATE TABLE task_awareness_events (
    id VARCHAR(36) NOT NULL,
    event_key VARCHAR(190) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    event_type VARCHAR(40) NOT NULL,
    payload_json JSON NOT NULL,
    available_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    published_at TIMESTAMP WITHOUT TIME ZONE,
    lease_token VARCHAR(36),
    lease_expires_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (event_key)
);

CREATE INDEX ix_task_awareness_event_pending ON task_awareness_events (published_at, available_at);

CREATE INDEX ix_task_awareness_events_creator_id ON task_awareness_events (creator_id);

CREATE TABLE task_event_outbox (
    id BIGSERIAL NOT NULL,
    event_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    receipt_id VARCHAR(36),
    receipt_version INTEGER,
    payload_json JSON NOT NULL,
    status VARCHAR(16) NOT NULL,
    available_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    lease_token VARCHAR(36),
    lease_until TIMESTAMP WITHOUT TIME ZONE,
    attempts INTEGER NOT NULL,
    last_error_code VARCHAR(80),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    UNIQUE (event_id)
);

CREATE INDEX ix_task_event_outbox_lease ON task_event_outbox (status, lease_until, id);

CREATE INDEX ix_task_event_outbox_pending ON task_event_outbox (status, available_at, id);

CREATE INDEX ix_task_event_outbox_task_id ON task_event_outbox (task_id);

CREATE TABLE task_status_events (
    id BIGSERIAL NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    event_key VARCHAR(190) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    trigger VARCHAR(40) NOT NULL,
    from_status VARCHAR(40),
    to_status VARCHAR(40) NOT NULL,
    status_seq BIGINT,
    outcome VARCHAR(40) NOT NULL,
    actor_id VARCHAR(36),
    job_id VARCHAR(36),
    session_generation INTEGER NOT NULL,
    session_revision INTEGER NOT NULL,
    reason VARCHAR(1000),
    result_json JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_task_status_event_key UNIQUE (task_id, event_key),
    CONSTRAINT uq_task_status_event_seq UNIQUE (task_id, status_seq)
);

CREATE INDEX ix_task_status_events_task_id ON task_status_events (task_id);

CREATE TABLE users (
    id VARCHAR(36) NOT NULL,
    email VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    avatar_url VARCHAR(500),
    avatar_svg TEXT,
    is_admin BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE mgmt_products (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(200) NOT NULL,
    code VARCHAR(100) NOT NULL,
    product_line VARCHAR(100),
    version_no VARCHAR(50) NOT NULL,
    release_date TIMESTAMP WITHOUT TIME ZONE,
    description TEXT,
    status productstatus NOT NULL,
    product_type producttype NOT NULL,
    baseline_product_id VARCHAR(36),
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(baseline_product_id) REFERENCES mgmt_products (id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_mgmt_products_baseline_product_id ON mgmt_products (baseline_product_id);

CREATE UNIQUE INDEX ix_mgmt_products_code ON mgmt_products (code);

CREATE INDEX ix_mgmt_products_product_type ON mgmt_products (product_type);

CREATE INDEX ix_mgmt_products_status ON mgmt_products (status);

CREATE TABLE mgmt_projects (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(200) NOT NULL,
    code VARCHAR(100) NOT NULL,
    customer VARCHAR(200),
    organization VARCHAR(200),
    lifecycle_status projectlifecyclestatus NOT NULL,
    description TEXT,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_mgmt_projects_code ON mgmt_projects (code);

CREATE INDEX ix_mgmt_projects_lifecycle_status ON mgmt_projects (lifecycle_status);

CREATE TABLE mgmt_repositories (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(200) NOT NULL,
    git_url VARCHAR(500) NOT NULL,
    repo_type repositorytype NOT NULL,
    default_branch VARCHAR(120) NOT NULL,
    group_id VARCHAR(36),
    description TEXT,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(group_id) REFERENCES mgmt_repo_groups (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_mgmt_repositories_git_url ON mgmt_repositories (git_url);

CREATE INDEX ix_mgmt_repositories_group_id ON mgmt_repositories (group_id);

CREATE INDEX ix_mgmt_repositories_repo_type ON mgmt_repositories (repo_type);

CREATE TABLE oauth_identities (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    provider_uid VARCHAR(255) NOT NULL,
    provider_email VARCHAR(255),
    provider_display_name VARCHAR(255),
    provider_avatar_url VARCHAR(500),
    email_verified BOOLEAN,
    raw_profile_json TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    last_login_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT uq_oauth_provider_uid UNIQUE (provider, provider_uid)
);

CREATE INDEX ix_oauth_identities_user_id ON oauth_identities (user_id);

CREATE TABLE mgmt_product_repos (
    id VARCHAR(36) NOT NULL,
    product_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36) NOT NULL,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(product_id) REFERENCES mgmt_products (id) ON DELETE CASCADE,
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE CASCADE,
    CONSTRAINT uq_mgmt_product_repos_product_repo UNIQUE (product_id, repository_id)
);

CREATE INDEX ix_mgmt_product_repos_product_id ON mgmt_product_repos (product_id);

CREATE INDEX ix_mgmt_product_repos_repository_id ON mgmt_product_repos (repository_id);

CREATE TABLE mgmt_product_versions (
    id VARCHAR(36) NOT NULL,
    product_id VARCHAR(36) NOT NULL,
    version_no VARCHAR(50) NOT NULL,
    status productversionstatus NOT NULL,
    release_date TIMESTAMP WITHOUT TIME ZONE,
    description TEXT,
    baseline_product_version_id VARCHAR(36),
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(baseline_product_version_id) REFERENCES mgmt_product_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(product_id) REFERENCES mgmt_products (id) ON DELETE CASCADE,
    CONSTRAINT uq_mgmt_product_versions_product_version UNIQUE (product_id, version_no)
);

CREATE INDEX ix_mgmt_product_versions_baseline_product_version_id ON mgmt_product_versions (baseline_product_version_id);

CREATE INDEX ix_mgmt_product_versions_product_id ON mgmt_product_versions (product_id);

CREATE INDEX ix_mgmt_product_versions_status ON mgmt_product_versions (status);

CREATE TABLE mgmt_project_releases (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    release_no VARCHAR(50) NOT NULL,
    name VARCHAR(200) NOT NULL,
    product_id VARCHAR(36),
    status releasestatus NOT NULL,
    release_date TIMESTAMP WITHOUT TIME ZONE,
    notes TEXT,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(product_id) REFERENCES mgmt_products (id) ON DELETE SET NULL,
    FOREIGN KEY(project_id) REFERENCES mgmt_projects (id) ON DELETE CASCADE,
    CONSTRAINT uq_mgmt_project_releases_project_no UNIQUE (project_id, release_no)
);

CREATE INDEX ix_mgmt_project_releases_product_id ON mgmt_project_releases (product_id);

CREATE INDEX ix_mgmt_project_releases_project_id ON mgmt_project_releases (project_id);

CREATE INDEX ix_mgmt_project_releases_status ON mgmt_project_releases (status);

CREATE TABLE workspaces (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    project_path VARCHAR(500),
    git_repo_url VARCHAR(500),
    project_id VARCHAR(36),
    owner_id VARCHAR(36) NOT NULL,
    agent_backend VARCHAR(40),
    plan_doc_roots JSON,
    custom_project_name VARCHAR(200),
    custom_product_name VARCHAR(200),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(owner_id) REFERENCES users (id),
    FOREIGN KEY(project_id) REFERENCES mgmt_projects (id) ON DELETE SET NULL
);

CREATE INDEX ix_workspaces_project_id ON workspaces (project_id);

CREATE TABLE mgmt_product_version_baseline_exclusions (
    id VARCHAR(36) NOT NULL,
    product_version_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36) NOT NULL,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(product_version_id) REFERENCES mgmt_product_versions (id) ON DELETE CASCADE,
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE CASCADE,
    CONSTRAINT uq_mgmt_product_version_baseline_exclusion UNIQUE (product_version_id, repository_id)
);

CREATE INDEX ix_mgmt_product_version_baseline_exclusions_product_version_id ON mgmt_product_version_baseline_exclusions (product_version_id);

CREATE INDEX ix_mgmt_product_version_baseline_exclusions_repository_id ON mgmt_product_version_baseline_exclusions (repository_id);

CREATE TABLE mgmt_product_version_repos (
    id VARCHAR(36) NOT NULL,
    product_version_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36) NOT NULL,
    ref_type reporeftype NOT NULL,
    ref_name VARCHAR(255) NOT NULL,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(product_version_id) REFERENCES mgmt_product_versions (id) ON DELETE CASCADE,
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE CASCADE,
    CONSTRAINT uq_mgmt_product_version_repos_version_repo UNIQUE (product_version_id, repository_id)
);

CREATE INDEX ix_mgmt_product_version_repos_product_version_id ON mgmt_product_version_repos (product_version_id);

CREATE INDEX ix_mgmt_product_version_repos_repository_id ON mgmt_product_version_repos (repository_id);

CREATE TABLE mgmt_project_products (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    product_id VARCHAR(36) NOT NULL,
    product_version_id VARCHAR(36),
    delivery_status projectlifecyclestatus NOT NULL,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(product_id) REFERENCES mgmt_products (id) ON DELETE CASCADE,
    FOREIGN KEY(product_version_id) REFERENCES mgmt_product_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(project_id) REFERENCES mgmt_projects (id) ON DELETE CASCADE,
    CONSTRAINT uq_mgmt_project_products_project_product UNIQUE (project_id, product_id)
);

CREATE INDEX ix_mgmt_project_products_delivery_status ON mgmt_project_products (delivery_status);

CREATE INDEX ix_mgmt_project_products_product_id ON mgmt_project_products (product_id);

CREATE INDEX ix_mgmt_project_products_product_version_id ON mgmt_project_products (product_version_id);

CREATE INDEX ix_mgmt_project_products_project_id ON mgmt_project_products (project_id);

CREATE TABLE mgmt_project_release_repos (
    id VARCHAR(36) NOT NULL,
    release_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36) NOT NULL,
    ref_type reporeftype NOT NULL,
    ref_name VARCHAR(255) NOT NULL,
    repo_kind releaserepokind NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(release_id) REFERENCES mgmt_project_releases (id) ON DELETE CASCADE,
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE CASCADE
);

CREATE INDEX ix_mgmt_project_release_repos_release_id ON mgmt_project_release_repos (release_id);

CREATE INDEX ix_mgmt_project_release_repos_repository_id ON mgmt_project_release_repos (repository_id);

CREATE TABLE playbook_specs (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    spec_key VARCHAR(120) NOT NULL,
    version VARCHAR(40) NOT NULL,
    spec_digest VARCHAR(71) NOT NULL,
    bundle_digest VARCHAR(71) NOT NULL,
    validation_state VARCHAR(40) NOT NULL,
    spec_json JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_playbook_spec_version UNIQUE (workspace_id, spec_key, version)
);

CREATE TABLE sdd_local_resources (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    name VARCHAR(120) NOT NULL,
    backend VARCHAR(40) NOT NULL,
    host_id VARCHAR(64),
    profile_revision INTEGER NOT NULL,
    service_url VARCHAR(500) NOT NULL,
    resource_service_url VARCHAR(500) NOT NULL,
    encrypted_credentials TEXT NOT NULL,
    workspace_root VARCHAR(500) NOT NULL,
    repositories_json JSON NOT NULL,
    verification_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(owner_user_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_local_resources_owner_user_id ON sdd_local_resources (owner_user_id);

CREATE INDEX ix_sdd_local_resources_workspace_id ON sdd_local_resources (workspace_id);

CREATE TABLE sdd_requirement_import_batches (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    created_by_id VARCHAR(36),
    source_kind VARCHAR(80),
    source_filename VARCHAR(500),
    source_uri VARCHAR(1000),
    source_ref VARCHAR(300),
    source_metadata_json JSON,
    normalized_markdown TEXT,
    draft_json JSON,
    status requirementimportbatchstatus NOT NULL,
    item_count INTEGER NOT NULL,
    confirmed_count INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_requirement_import_batches_created_by_id ON sdd_requirement_import_batches (created_by_id);

CREATE INDEX ix_sdd_requirement_import_batches_status ON sdd_requirement_import_batches (status);

CREATE INDEX ix_sdd_requirement_import_batches_workspace_id ON sdd_requirement_import_batches (workspace_id);

CREATE TABLE sdd_skills (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    dimension skilldimension NOT NULL,
    workspace_id VARCHAR(36),
    creator_id VARCHAR(36) NOT NULL,
    last_modifier_id VARCHAR(36) NOT NULL,
    package_path VARCHAR(500) NOT NULL,
    entry_file_path VARCHAR(500) NOT NULL,
    manifest_path VARCHAR(500),
    head_commit_sha VARCHAR(64),
    latest_version_no INTEGER NOT NULL,
    source_type VARCHAR(50),
    source_repo_url VARCHAR(1000),
    source_skill_name VARCHAR(200),
    source_subdir VARCHAR(1000),
    source_locked BOOLEAN NOT NULL,
    source_commit_sha VARCHAR(64),
    source_last_synced_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(last_modifier_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_skills_creator_id ON sdd_skills (creator_id);

CREATE INDEX ix_sdd_skills_last_modifier_id ON sdd_skills (last_modifier_id);

CREATE INDEX ix_sdd_skills_workspace_id ON sdd_skills (workspace_id);

CREATE TABLE sdd_tasks (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    task_type VARCHAR(40) NOT NULL,
    task_meta_json JSON,
    business_state VARCHAR(40) DEFAULT 'TASK_IN_PROGRESS' NOT NULL,
    name VARCHAR(300) NOT NULL,
    description TEXT,
    spec_doc_path VARCHAR(500),
    project_path VARCHAR(500),
    execution_location VARCHAR(16) DEFAULT 'SERVER' NOT NULL,
    local_resource_id VARCHAR(36),
    git_repo_url VARCHAR(500),
    status taskstatus NOT NULL,
    status_seq BIGINT DEFAULT '0' NOT NULL,
    status_run_id VARCHAR(36),
    retry_count INTEGER NOT NULL,
    current_phase VARCHAR(50),
    error_message TEXT,
    session_id VARCHAR(120),
    agent_session_verification JSON,
    session_generation INTEGER DEFAULT '0' NOT NULL,
    session_revision INTEGER DEFAULT '0' NOT NULL,
    next_chat_seq BIGINT,
    reading_change_seq BIGINT DEFAULT '0' NOT NULL,
    reading_epoch BIGINT DEFAULT '1' NOT NULL,
    reading_ready BOOLEAN DEFAULT '0' NOT NULL,
    agent_backend VARCHAR(40),
    interrupt_reason TEXT,
    interrupted_by_id VARCHAR(36),
    interrupted_at TIMESTAMP WITHOUT TIME ZONE,
    baselined_at TIMESTAMP WITHOUT TIME ZONE,
    baselined_by_id VARCHAR(36),
    baseline_snapshot_json JSON,
    baseline_version INTEGER NOT NULL,
    requirement_duration_hours INTEGER NOT NULL,
    total_cost_usd FLOAT NOT NULL,
    total_duration_ms BIGINT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(baselined_by_id) REFERENCES users (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(interrupted_by_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_tasks_baselined_by_id ON sdd_tasks (baselined_by_id);

CREATE INDEX ix_sdd_tasks_creator_id ON sdd_tasks (creator_id);

CREATE INDEX ix_sdd_tasks_session_generation ON sdd_tasks (session_generation);

CREATE INDEX ix_sdd_tasks_session_revision ON sdd_tasks (session_revision);

CREATE INDEX ix_sdd_tasks_task_type ON sdd_tasks (task_type);

CREATE INDEX ix_sdd_tasks_workspace_created ON sdd_tasks (workspace_id, created_at, id);

CREATE INDEX ix_sdd_tasks_workspace_id ON sdd_tasks (workspace_id);

CREATE TABLE sdd_user_notifications (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36),
    recipient_user_id VARCHAR(36) NOT NULL,
    type VARCHAR(50) NOT NULL,
    title VARCHAR(300) NOT NULL,
    body TEXT,
    payload_json JSON,
    read_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(recipient_user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_notifications_recipient_created ON sdd_user_notifications (recipient_user_id, created_at, id);

CREATE INDEX ix_notifications_recipient_unread ON sdd_user_notifications (recipient_user_id, read_at, created_at, id);

CREATE INDEX ix_sdd_user_notifications_read_at ON sdd_user_notifications (read_at);

CREATE INDEX ix_sdd_user_notifications_recipient_user_id ON sdd_user_notifications (recipient_user_id);

CREATE INDEX ix_sdd_user_notifications_type ON sdd_user_notifications (type);

CREATE INDEX ix_sdd_user_notifications_workspace_id ON sdd_user_notifications (workspace_id);

CREATE TABLE task_webhook_endpoints (
    id VARCHAR(36) NOT NULL,
    scope_key VARCHAR(80) NOT NULL,
    user_id VARCHAR(36),
    workspace_id VARCHAR(36),
    enabled BOOLEAN NOT NULL,
    url TEXT NOT NULL,
    delivery_location VARCHAR(20) NOT NULL,
    events_json JSON NOT NULL,
    workspace_filter_ids JSON,
    notify_task_creator BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    UNIQUE (scope_key)
);

CREATE TABLE workspace_invite_links (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    token VARCHAR(64) NOT NULL,
    role workspacerole NOT NULL,
    permissions_json VARCHAR(2048) NOT NULL,
    is_expert BOOLEAN NOT NULL,
    max_uses INTEGER,
    used_count INTEGER NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_workspace_invite_links_token ON workspace_invite_links (token);

CREATE INDEX ix_workspace_invite_links_workspace_id ON workspace_invite_links (workspace_id);

CREATE TABLE workspace_members (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    role workspacerole NOT NULL,
    permissions_json VARCHAR(2048) NOT NULL,
    is_expert BOOLEAN NOT NULL,
    joined_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_workspace_members_workspace_user UNIQUE (workspace_id, user_id)
);

CREATE INDEX ix_workspace_members_user_id ON workspace_members (user_id);

CREATE INDEX ix_workspace_members_workspace_id ON workspace_members (workspace_id);

CREATE TABLE workspace_repositories (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36),
    repo_url VARCHAR(500) NOT NULL,
    repo_name VARCHAR(200) NOT NULL,
    repo_slug VARCHAR(120) NOT NULL,
    branch_name VARCHAR(255) NOT NULL,
    ref_type VARCHAR(20),
    base_dir VARCHAR(500),
    state workspacerepositorystate NOT NULL,
    base_commit_sha VARCHAR(64),
    error_message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_workspace_repositories_ws_repo UNIQUE (workspace_id, repository_id)
);

CREATE INDEX ix_workspace_repositories_repository_id ON workspace_repositories (repository_id);

CREATE INDEX ix_workspace_repositories_state ON workspace_repositories (state);

CREATE INDEX ix_workspace_repositories_workspace_id ON workspace_repositories (workspace_id);

CREATE TABLE chat_messages (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    role messagerole NOT NULL,
    content TEXT NOT NULL,
    message_type messagetype NOT NULL,
    metadata_json JSON,
    session_turn_id VARCHAR(36),
    session_generation INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    sort_seq BIGINT,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
);

CREATE INDEX ix_chat_message_context ON chat_messages (task_id, created_at, sort_seq, id);

CREATE INDEX ix_chat_messages_session_generation ON chat_messages (session_generation);

CREATE INDEX ix_chat_messages_session_turn_id ON chat_messages (session_turn_id);

CREATE INDEX ix_chat_messages_task_id ON chat_messages (task_id);

CREATE INDEX ix_chat_messages_workspace_id ON chat_messages (workspace_id);

CREATE TABLE playbook_runs (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    spec_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    idempotency_key VARCHAR(120) NOT NULL,
    request_digest VARCHAR(71) NOT NULL,
    epoch INTEGER NOT NULL,
    state_version INTEGER NOT NULL,
    event_seq INTEGER NOT NULL,
    published_seq INTEGER DEFAULT '0' NOT NULL,
    lease_owner VARCHAR(64),
    lease_until FLOAT(53) DEFAULT '0' NOT NULL,
    phase VARCHAR(24) NOT NULL,
    state VARCHAR(32) NOT NULL,
    active_step VARCHAR(120) NOT NULL,
    data_json JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(spec_id) REFERENCES playbook_specs (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_playbook_attach_key UNIQUE (task_id, idempotency_key)
);

CREATE INDEX ix_playbook_runs_task_id ON playbook_runs (task_id);

CREATE INDEX ix_playbook_runs_workspace_id ON playbook_runs (workspace_id);

CREATE TABLE sdd_api_mock_projects (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    proxy_enabled BOOLEAN NOT NULL,
    proxy_base_url VARCHAR(1000),
    temp_workspace_path VARCHAR(1000) NOT NULL,
    active_source_version_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_api_mock_project_workspace_task UNIQUE (workspace_id, task_id)
);

CREATE INDEX ix_sdd_api_mock_projects_active_source_version_id ON sdd_api_mock_projects (active_source_version_id);

CREATE INDEX ix_sdd_api_mock_projects_creator_id ON sdd_api_mock_projects (creator_id);

CREATE INDEX ix_sdd_api_mock_projects_task_id ON sdd_api_mock_projects (task_id);

CREATE INDEX ix_sdd_api_mock_projects_workspace_id ON sdd_api_mock_projects (workspace_id);

CREATE TABLE sdd_assets (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    asset_type assettype NOT NULL,
    name VARCHAR(300) NOT NULL,
    content_text TEXT,
    content_json JSON,
    active_version_id VARCHAR(36),
    source_file_name VARCHAR(500),
    source_ext VARCHAR(32),
    source_mime VARCHAR(120),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
);

CREATE INDEX ix_sdd_assets_active_version_id ON sdd_assets (active_version_id);

CREATE INDEX ix_sdd_assets_task_id ON sdd_assets (task_id);

CREATE INDEX ix_sdd_assets_workspace_id ON sdd_assets (workspace_id);

CREATE TABLE sdd_cases (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    source_task_id VARCHAR(36),
    title VARCHAR(300) NOT NULL,
    problem_description TEXT,
    product_name VARCHAR(200),
    product_version VARCHAR(100),
    site_name VARCHAR(200),
    code_context TEXT,
    analysis_process TEXT,
    root_cause TEXT,
    solution TEXT,
    category VARCHAR(20) NOT NULL,
    priority VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL,
    archive_origin VARCHAR(16) DEFAULT 'MANUAL' NOT NULL,
    review_round INTEGER NOT NULL,
    diagnosis_detail_json JSON,
    submitted_at TIMESTAMP WITHOUT TIME ZONE,
    reviewed_at TIMESTAMP WITHOUT TIME ZONE,
    rejected_comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(source_task_id) REFERENCES sdd_tasks (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_cases_category ON sdd_cases (category);

CREATE INDEX ix_sdd_cases_creator_id ON sdd_cases (creator_id);

CREATE INDEX ix_sdd_cases_priority ON sdd_cases (priority);

CREATE INDEX ix_sdd_cases_source_task_id ON sdd_cases (source_task_id);

CREATE INDEX ix_sdd_cases_status ON sdd_cases (status);

CREATE INDEX ix_sdd_cases_workspace_id ON sdd_cases (workspace_id);

CREATE TABLE sdd_dashboard_metrics (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    metric_type VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    recorded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
);

CREATE INDEX ix_sdd_dashboard_metrics_task_id ON sdd_dashboard_metrics (task_id);

CREATE INDEX ix_sdd_dashboard_metrics_workspace_id ON sdd_dashboard_metrics (workspace_id);

CREATE TABLE sdd_human_reviews (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    reviewer_id VARCHAR(36),
    status humanreviewstatus NOT NULL,
    outcome humanreviewoutcome,
    review_type VARCHAR(80),
    review_scope VARCHAR(80),
    priority VARCHAR(40),
    title VARCHAR(300),
    body TEXT,
    source_ref_json JSON,
    target_ref_json JSON,
    due_date TIMESTAMP WITHOUT TIME ZONE,
    resolved_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(reviewer_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_human_reviews_outcome ON sdd_human_reviews (outcome);

CREATE INDEX ix_sdd_human_reviews_reviewer_id ON sdd_human_reviews (reviewer_id);

CREATE INDEX ix_sdd_human_reviews_status ON sdd_human_reviews (status);

CREATE INDEX ix_sdd_human_reviews_task_id ON sdd_human_reviews (task_id);

CREATE INDEX ix_sdd_human_reviews_workspace_id ON sdd_human_reviews (workspace_id);

CREATE TABLE sdd_plan_nodes (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    parent_id VARCHAR(36),
    title VARCHAR(300) NOT NULL,
    description TEXT,
    status plannodestatus NOT NULL,
    order_index INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(parent_id) REFERENCES sdd_plan_nodes (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
);

CREATE INDEX ix_sdd_plan_nodes_task_id ON sdd_plan_nodes (task_id);

CREATE INDEX ix_sdd_plan_nodes_workspace_id ON sdd_plan_nodes (workspace_id);

CREATE TABLE sdd_provision_jobs (
    id VARCHAR(36) NOT NULL,
    job_type provisionjobtype NOT NULL,
    context_json JSON,
    creator_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36),
    task_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE SET NULL
);

CREATE INDEX ix_sdd_provision_jobs_creator_id ON sdd_provision_jobs (creator_id);

CREATE INDEX ix_sdd_provision_jobs_job_type ON sdd_provision_jobs (job_type);

CREATE INDEX ix_sdd_provision_jobs_task_id ON sdd_provision_jobs (task_id);

CREATE INDEX ix_sdd_provision_jobs_workspace_id ON sdd_provision_jobs (workspace_id);

CREATE TABLE sdd_requirements (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    created_by_id VARCHAR(36),
    title VARCHAR(300) NOT NULL,
    body TEXT,
    status requirementstatus NOT NULL,
    acceptance_criteria_json JSON,
    priority VARCHAR(40),
    parent_requirement_id VARCHAR(36),
    import_batch_id VARCHAR(36),
    source_kind VARCHAR(80),
    source_uri VARCHAR(1000),
    source_ref VARCHAR(300),
    source_metadata_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by_id) REFERENCES users (id),
    FOREIGN KEY(import_batch_id) REFERENCES sdd_requirement_import_batches (id) ON DELETE SET NULL,
    FOREIGN KEY(parent_requirement_id) REFERENCES sdd_requirements (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_requirements_created_by_id ON sdd_requirements (created_by_id);

CREATE INDEX ix_sdd_requirements_import_batch_id ON sdd_requirements (import_batch_id);

CREATE INDEX ix_sdd_requirements_parent_requirement_id ON sdd_requirements (parent_requirement_id);

CREATE INDEX ix_sdd_requirements_status ON sdd_requirements (status);

CREATE INDEX ix_sdd_requirements_workspace_id ON sdd_requirements (workspace_id);

CREATE TABLE sdd_skill_versions (
    id VARCHAR(36) NOT NULL,
    skill_id VARCHAR(36) NOT NULL,
    version_no INTEGER NOT NULL,
    commit_sha VARCHAR(64) NOT NULL,
    parent_commit_sha VARCHAR(64),
    tree_sha VARCHAR(64),
    changed_files_count INTEGER,
    change_note TEXT,
    creator_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(skill_id) REFERENCES sdd_skills (id) ON DELETE CASCADE,
    CONSTRAINT uq_skill_versions_skill_commit UNIQUE (skill_id, commit_sha),
    CONSTRAINT uq_skill_versions_skill_version UNIQUE (skill_id, version_no)
);

CREATE INDEX ix_sdd_skill_versions_creator_id ON sdd_skill_versions (creator_id);

CREATE INDEX ix_sdd_skill_versions_skill_id ON sdd_skill_versions (skill_id);

CREATE TABLE sdd_task_execution_bindings (
    task_id VARCHAR(36) NOT NULL,
    resource_id VARCHAR(36) NOT NULL,
    binding_version INTEGER NOT NULL,
    profile_json JSON NOT NULL,
    receipt_json JSON,
    PRIMARY KEY (task_id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_task_execution_bindings_resource_id ON sdd_task_execution_bindings (resource_id);

CREATE TABLE sdd_task_followers (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_task_followers_task_user UNIQUE (task_id, user_id)
);

CREATE INDEX ix_sdd_task_followers_task_id ON sdd_task_followers (task_id);

CREATE INDEX ix_sdd_task_followers_user_id ON sdd_task_followers (user_id);

CREATE INDEX ix_sdd_task_followers_workspace_id ON sdd_task_followers (workspace_id);

CREATE TABLE sdd_task_process_audit_logs (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    actor_id VARCHAR(36),
    record_type taskprocessrecordtype NOT NULL,
    record_id VARCHAR(36) NOT NULL,
    action taskprocessauditaction NOT NULL,
    before_json JSON,
    after_json JSON,
    reason TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(actor_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_task_process_audit_logs_action ON sdd_task_process_audit_logs (action);

CREATE INDEX ix_sdd_task_process_audit_logs_actor_id ON sdd_task_process_audit_logs (actor_id);

CREATE INDEX ix_sdd_task_process_audit_logs_record_id ON sdd_task_process_audit_logs (record_id);

CREATE INDEX ix_sdd_task_process_audit_logs_record_type ON sdd_task_process_audit_logs (record_type);

CREATE INDEX ix_sdd_task_process_audit_logs_task_id ON sdd_task_process_audit_logs (task_id);

CREATE INDEX ix_sdd_task_process_audit_logs_workspace_id ON sdd_task_process_audit_logs (workspace_id);

CREATE TABLE sdd_task_repositories (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36),
    repo_url VARCHAR(500) NOT NULL,
    repo_name VARCHAR(200) NOT NULL,
    repo_slug VARCHAR(120) NOT NULL,
    branch_name VARCHAR(255) NOT NULL,
    base_commit_sha VARCHAR(64),
    rel_path VARCHAR(200) NOT NULL,
    state taskrepositorystate NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_task_repositories_task_repo UNIQUE (task_id, repository_id)
);

CREATE INDEX ix_sdd_task_repositories_repository_id ON sdd_task_repositories (repository_id);

CREATE INDEX ix_sdd_task_repositories_state ON sdd_task_repositories (state);

CREATE INDEX ix_sdd_task_repositories_task_id ON sdd_task_repositories (task_id);

CREATE TABLE sdd_task_skills (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    skill_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(skill_id) REFERENCES sdd_skills (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_task_skills_task_skill UNIQUE (task_id, skill_id)
);

CREATE INDEX ix_sdd_task_skills_skill_id ON sdd_task_skills (skill_id);

CREATE INDEX ix_sdd_task_skills_task_id ON sdd_task_skills (task_id);

CREATE TABLE task_collaboration_handoffs (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    operation_id VARCHAR(128) NOT NULL,
    submission_id VARCHAR(36),
    source VARCHAR(32) NOT NULL,
    actor_user_id VARCHAR(36) NOT NULL,
    client_id VARCHAR(128) NOT NULL,
    binding_id VARCHAR(36) NOT NULL,
    lease_epoch INTEGER NOT NULL,
    base_snapshot_id VARCHAR(36) NOT NULL,
    input_snapshot_id VARCHAR(36) NOT NULL,
    repository_deltas_json JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    CONSTRAINT uq_collaboration_handoff UNIQUE (task_id, operation_id)
);

CREATE INDEX ix_collaboration_handoff_history ON task_collaboration_handoffs (task_id, created_at, id);

CREATE INDEX ix_task_collaboration_handoffs_task_id ON task_collaboration_handoffs (task_id);

CREATE TABLE task_collaboration_manifests (
    task_id VARCHAR(36) NOT NULL,
    content_digest VARCHAR(64) NOT NULL,
    repositories_zstd BYTEA NOT NULL,
    PRIMARY KEY (task_id, content_digest),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE
);

CREATE TABLE task_collaboration_operations (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    operation_id VARCHAR(128) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL,
    result_json JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    CONSTRAINT uq_collaboration_operation UNIQUE (task_id, operation_id)
);

CREATE INDEX ix_task_collaboration_operations_task_id ON task_collaboration_operations (task_id);

CREATE TABLE task_collaboration_states (
    task_id VARCHAR(36) NOT NULL,
    enabled BOOLEAN NOT NULL,
    sync_phase VARCHAR(32) NOT NULL,
    state_version INTEGER NOT NULL,
    workspace_revision INTEGER NOT NULL,
    session_generation INTEGER NOT NULL,
    session_revision INTEGER NOT NULL,
    repository_set_digest VARCHAR(64) NOT NULL,
    binding_id VARCHAR(36) NOT NULL,
    driver_user_id VARCHAR(36) NOT NULL,
    client_id VARCHAR(128) NOT NULL,
    instance_id VARCHAR(128) NOT NULL,
    lease_epoch INTEGER NOT NULL,
    lease_expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    snapshot_id VARCHAR(36),
    input_snapshot_id VARCHAR(36),
    progress_snapshot_id VARCHAR(36),
    progress_seq INTEGER NOT NULL,
    final_progress_seq INTEGER,
    run_id VARCHAR(36),
    execution_epoch INTEGER NOT NULL,
    pending_submission_id VARCHAR(36),
    input_submission_id VARCHAR(36),
    input_cut_seq INTEGER,
    reconciled_revision INTEGER NOT NULL,
    recovery_kind VARCHAR(32),
    recovery_message VARCHAR(1000),
    recovery_operation_id VARCHAR(128),
    restore_operation_id VARCHAR(80),
    conflicts_json JSON NOT NULL,
    pending_local_changes_json JSON NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (task_id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE
);

CREATE TABLE task_reading_items (
    task_id VARCHAR(36) NOT NULL,
    item_key VARCHAR(100) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    kind VARCHAR(24) NOT NULL,
    message_id VARCHAR(36),
    change_seq BIGINT NOT NULL,
    first_change_seq BIGINT NOT NULL,
    content_fingerprint VARCHAR(64),
    active BOOLEAN NOT NULL,
    role VARCHAR(24),
    creator_id VARCHAR(36),
    session_turn_id VARCHAR(36),
    session_generation INTEGER,
    order_created_at TIMESTAMP WITHOUT TIME ZONE,
    order_sort_seq BIGINT,
    order_message_id VARCHAR(36),
    operation_id VARCHAR(64),
    deleted_change_seq BIGINT,
    affected_count INTEGER,
    boundary_before_id VARCHAR(36),
    boundary_after_id VARCHAR(36),
    changed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (task_id, item_key),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    CONSTRAINT uq_task_reading_items_task_change_seq UNIQUE (task_id, change_seq)
);

CREATE INDEX ix_task_reading_items_active ON task_reading_items (task_id, active, change_seq);

CREATE INDEX ix_task_reading_items_member ON task_reading_items (task_id, role, creator_id, active, change_seq);

CREATE INDEX ix_task_reading_items_message ON task_reading_items (task_id, message_id);

CREATE INDEX ix_task_reading_items_turn ON task_reading_items (task_id, session_generation, session_turn_id, active, change_seq);

CREATE INDEX ix_task_reading_items_workspace_id ON task_reading_items (workspace_id);

CREATE TABLE task_reading_receipts (
    user_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    reading_epoch BIGINT NOT NULL,
    item_key VARCHAR(100) NOT NULL,
    seen_change_seq BIGINT NOT NULL,
    seen_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id, task_id, reading_epoch, item_key),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_task_reading_receipts_seen ON task_reading_receipts (user_id, task_id, reading_epoch, seen_change_seq);

CREATE TABLE task_reading_states (
    user_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    reading_epoch BIGINT DEFAULT '1' NOT NULL,
    baseline_seq BIGINT DEFAULT '0' NOT NULL,
    read_frontier_seq BIGINT DEFAULT '0' NOT NULL,
    state_revision BIGINT DEFAULT '0' NOT NULL,
    resume_message_id VARCHAR(36),
    resume_order_key VARCHAR(255),
    resume_content_seq BIGINT,
    resume_offset_ratio FLOAT,
    resume_revision BIGINT DEFAULT '0' NOT NULL,
    resume_updated_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id, task_id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_task_reading_states_workspace ON task_reading_states (workspace_id, user_id);

CREATE INDEX ix_task_reading_states_workspace_id ON task_reading_states (workspace_id);

CREATE TABLE task_webhook_deliveries (
    id VARCHAR(36) NOT NULL,
    event_id VARCHAR(36) NOT NULL,
    endpoint_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL,
    attempts INTEGER NOT NULL,
    available_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    lease_token VARCHAR(36),
    lease_expires_at TIMESTAMP WITHOUT TIME ZONE,
    last_error VARCHAR(300),
    notified_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(endpoint_id) REFERENCES task_webhook_endpoints (id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES task_awareness_events (id) ON DELETE CASCADE,
    CONSTRAINT uq_task_webhook_event_endpoint UNIQUE (event_id, endpoint_id)
);

CREATE INDEX ix_task_webhook_delivery_pending ON task_webhook_deliveries (status, available_at);

CREATE TABLE case_playbook_links (
    id VARCHAR(36) NOT NULL,
    case_id VARCHAR(36) NOT NULL,
    spec_id VARCHAR(36),
    source_run_id VARCHAR(36),
    revision_json JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(case_id) REFERENCES sdd_cases (id) ON DELETE CASCADE,
    FOREIGN KEY(source_run_id) REFERENCES playbook_runs (id),
    FOREIGN KEY(spec_id) REFERENCES playbook_specs (id),
    UNIQUE (source_run_id)
);

CREATE INDEX ix_case_playbook_links_case_id ON case_playbook_links (case_id);

CREATE TABLE sdd_api_mock_jobs (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    job_type VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(project_id) REFERENCES sdd_api_mock_projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_api_mock_jobs_creator_id ON sdd_api_mock_jobs (creator_id);

CREATE INDEX ix_sdd_api_mock_jobs_project_id ON sdd_api_mock_jobs (project_id);

CREATE TABLE sdd_api_mock_source_versions (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    source_name VARCHAR(500),
    raw_content TEXT,
    normalized_oas_json JSON,
    storage_path VARCHAR(1000),
    summary_json JSON,
    is_active BOOLEAN NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(project_id) REFERENCES sdd_api_mock_projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_api_mock_source_versions_creator_id ON sdd_api_mock_source_versions (creator_id);

CREATE INDEX ix_sdd_api_mock_source_versions_project_id ON sdd_api_mock_source_versions (project_id);

CREATE TABLE sdd_asset_versions (
    id VARCHAR(36) NOT NULL,
    asset_id VARCHAR(36) NOT NULL,
    version_no INTEGER NOT NULL,
    base_version_id VARCHAR(36),
    original_path VARCHAR(1000),
    original_ext VARCHAR(32),
    original_mime VARCHAR(120),
    normalized_markdown TEXT,
    blocks_json JSON,
    render_json JSON,
    change_note TEXT,
    created_by VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(asset_id) REFERENCES sdd_assets (id) ON DELETE CASCADE,
    FOREIGN KEY(base_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES users (id),
    CONSTRAINT uq_sdd_asset_versions_asset_version UNIQUE (asset_id, version_no)
);

CREATE INDEX ix_sdd_asset_versions_asset_id ON sdd_asset_versions (asset_id);

CREATE INDEX ix_sdd_asset_versions_base_version_id ON sdd_asset_versions (base_version_id);

CREATE INDEX ix_sdd_asset_versions_created_by ON sdd_asset_versions (created_by);

CREATE TABLE sdd_case_review_records (
    id VARCHAR(36) NOT NULL,
    case_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    reviewer_id VARCHAR(36),
    action VARCHAR(20) NOT NULL,
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(case_id) REFERENCES sdd_cases (id) ON DELETE CASCADE,
    FOREIGN KEY(reviewer_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_case_review_records_case_id ON sdd_case_review_records (case_id);

CREATE INDEX ix_sdd_case_review_records_reviewer_id ON sdd_case_review_records (reviewer_id);

CREATE INDEX ix_sdd_case_review_records_workspace_id ON sdd_case_review_records (workspace_id);

CREATE TABLE sdd_diagnosis_results (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    created_by_id VARCHAR(36) NOT NULL,
    summary TEXT,
    root_cause TEXT,
    evidence_json JSON,
    fix_steps_json JSON,
    fix_code TEXT,
    confidence INTEGER NOT NULL,
    code_context_json JSON,
    similar_cases_json JSON,
    call_chain_json JSON,
    source_chat_message_id VARCHAR(36),
    extracted_from_ai BOOLEAN NOT NULL,
    extracted_at TIMESTAMP WITHOUT TIME ZONE,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by_id) REFERENCES users (id),
    FOREIGN KEY(source_chat_message_id) REFERENCES chat_messages (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_diagnosis_results_source_chat_message_id ON sdd_diagnosis_results (source_chat_message_id);

CREATE UNIQUE INDEX ix_sdd_diagnosis_results_task_id ON sdd_diagnosis_results (task_id);

CREATE INDEX ix_sdd_diagnosis_results_workspace_id ON sdd_diagnosis_results (workspace_id);

CREATE TABLE sdd_human_review_comments (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    review_id VARCHAR(36) NOT NULL,
    author_id VARCHAR(36),
    comment_type VARCHAR(80),
    body TEXT NOT NULL,
    required_change_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(author_id) REFERENCES users (id),
    FOREIGN KEY(review_id) REFERENCES sdd_human_reviews (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_human_review_comments_author_id ON sdd_human_review_comments (author_id);

CREATE INDEX ix_sdd_human_review_comments_review_id ON sdd_human_review_comments (review_id);

CREATE INDEX ix_sdd_human_review_comments_task_id ON sdd_human_review_comments (task_id);

CREATE INDEX ix_sdd_human_review_comments_workspace_id ON sdd_human_review_comments (workspace_id);

CREATE TABLE sdd_requirement_audit_logs (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    requirement_id VARCHAR(36),
    import_batch_id VARCHAR(36),
    task_id VARCHAR(36),
    actor_id VARCHAR(36),
    action requirementauditaction NOT NULL,
    before_json JSON,
    after_json JSON,
    reason TEXT,
    source_metadata_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(actor_id) REFERENCES users (id),
    FOREIGN KEY(import_batch_id) REFERENCES sdd_requirement_import_batches (id) ON DELETE SET NULL,
    FOREIGN KEY(requirement_id) REFERENCES sdd_requirements (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_requirement_audit_logs_action ON sdd_requirement_audit_logs (action);

CREATE INDEX ix_sdd_requirement_audit_logs_actor_id ON sdd_requirement_audit_logs (actor_id);

CREATE INDEX ix_sdd_requirement_audit_logs_import_batch_id ON sdd_requirement_audit_logs (import_batch_id);

CREATE INDEX ix_sdd_requirement_audit_logs_requirement_id ON sdd_requirement_audit_logs (requirement_id);

CREATE INDEX ix_sdd_requirement_audit_logs_task_id ON sdd_requirement_audit_logs (task_id);

CREATE INDEX ix_sdd_requirement_audit_logs_workspace_id ON sdd_requirement_audit_logs (workspace_id);

CREATE TABLE sdd_requirement_import_items (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    batch_id VARCHAR(36) NOT NULL,
    requirement_id VARCHAR(36),
    title VARCHAR(300) NOT NULL,
    body TEXT,
    acceptance_criteria_json JSON,
    priority VARCHAR(40),
    source_ref VARCHAR(300),
    source_metadata_json JSON,
    order_index INTEGER NOT NULL,
    status requirementimportitemstatus NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(batch_id) REFERENCES sdd_requirement_import_batches (id) ON DELETE CASCADE,
    FOREIGN KEY(requirement_id) REFERENCES sdd_requirements (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_requirement_import_items_batch_id ON sdd_requirement_import_items (batch_id);

CREATE INDEX ix_sdd_requirement_import_items_requirement_id ON sdd_requirement_import_items (requirement_id);

CREATE INDEX ix_sdd_requirement_import_items_status ON sdd_requirement_import_items (status);

CREATE INDEX ix_sdd_requirement_import_items_workspace_id ON sdd_requirement_import_items (workspace_id);

CREATE TABLE sdd_skill_analyses (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    skill_id VARCHAR(36) NOT NULL,
    version_id VARCHAR(36),
    commit_sha VARCHAR(64),
    ref_kind skillanalysisrefkind NOT NULL,
    risk_level skillrisklevel,
    complexity skillrisklevel,
    review_priority skillrisklevel,
    file_stats_json JSON,
    file_type_distribution_json JSON,
    key_files_json JSON,
    risk_items_json JSON,
    review_suggestions_json JSON,
    created_by_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(created_by_id) REFERENCES users (id),
    FOREIGN KEY(skill_id) REFERENCES sdd_skills (id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES sdd_skill_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_skill_analyses_commit_sha ON sdd_skill_analyses (commit_sha);

CREATE INDEX ix_sdd_skill_analyses_created_by_id ON sdd_skill_analyses (created_by_id);

CREATE INDEX ix_sdd_skill_analyses_skill_id ON sdd_skill_analyses (skill_id);

CREATE INDEX ix_sdd_skill_analyses_version_id ON sdd_skill_analyses (version_id);

CREATE INDEX ix_sdd_skill_analyses_workspace_id ON sdd_skill_analyses (workspace_id);

CREATE TABLE sdd_skill_expert_ratings (
    id VARCHAR(36) NOT NULL,
    skill_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    version_id VARCHAR(36),
    expert_user_id VARCHAR(36) NOT NULL,
    score INTEGER NOT NULL,
    note TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(expert_user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(skill_id) REFERENCES sdd_skills (id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES sdd_skill_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_skill_expert_ratings_skill_workspace_user UNIQUE (skill_id, workspace_id, expert_user_id)
);

CREATE INDEX ix_sdd_skill_expert_ratings_expert_user_id ON sdd_skill_expert_ratings (expert_user_id);

CREATE INDEX ix_sdd_skill_expert_ratings_skill_id ON sdd_skill_expert_ratings (skill_id);

CREATE INDEX ix_sdd_skill_expert_ratings_version_id ON sdd_skill_expert_ratings (version_id);

CREATE INDEX ix_sdd_skill_expert_ratings_workspace_id ON sdd_skill_expert_ratings (workspace_id);

CREATE TABLE sdd_skill_review_comments (
    id VARCHAR(36) NOT NULL,
    skill_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    version_id VARCHAR(36) NOT NULL,
    expert_user_id VARCHAR(36) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    selected_text TEXT,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    column_start INTEGER NOT NULL,
    column_end INTEGER NOT NULL,
    char_start INTEGER,
    char_end INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(expert_user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(skill_id) REFERENCES sdd_skills (id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES sdd_skill_versions (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_skill_review_comments_expert_user_id ON sdd_skill_review_comments (expert_user_id);

CREATE INDEX ix_sdd_skill_review_comments_file_path ON sdd_skill_review_comments (file_path);

CREATE INDEX ix_sdd_skill_review_comments_skill_id ON sdd_skill_review_comments (skill_id);

CREATE INDEX ix_sdd_skill_review_comments_version_id ON sdd_skill_review_comments (version_id);

CREATE INDEX ix_sdd_skill_review_comments_workspace_id ON sdd_skill_review_comments (workspace_id);

CREATE TABLE sdd_task_final_summaries (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    author_id VARCHAR(36),
    final_status taskfinalstatus NOT NULL,
    summary TEXT,
    remaining_risk TEXT,
    next_steps TEXT,
    final_evidence_ids_json JSON,
    review_checklist_json JSON,
    clarification_summary_json JSON,
    delta_summary_json JSON,
    decision_summary_json JSON,
    human_confirmation_review_id VARCHAR(36),
    verified_at TIMESTAMP WITHOUT TIME ZONE,
    verified_by_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(author_id) REFERENCES users (id),
    FOREIGN KEY(human_confirmation_review_id) REFERENCES sdd_human_reviews (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(verified_by_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_task_final_summaries_task UNIQUE (task_id)
);

CREATE INDEX ix_sdd_task_final_summaries_author_id ON sdd_task_final_summaries (author_id);

CREATE INDEX ix_sdd_task_final_summaries_final_status ON sdd_task_final_summaries (final_status);

CREATE INDEX ix_sdd_task_final_summaries_task_id ON sdd_task_final_summaries (task_id);

CREATE INDEX ix_sdd_task_final_summaries_verified_by_id ON sdd_task_final_summaries (verified_by_id);

CREATE INDEX ix_sdd_task_final_summaries_workspace_id ON sdd_task_final_summaries (workspace_id);

CREATE TABLE sdd_task_pre_inputs (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    main_text TEXT NOT NULL,
    document_json JSON,
    edit_permission preinputeditpermission NOT NULL,
    status preinputstatus NOT NULL,
    wait_seconds INTEGER NOT NULL,
    deadline_at TIMESTAMP WITHOUT TIME ZONE,
    submitted_at TIMESTAMP WITHOUT TIME ZONE,
    submitted_message_id VARCHAR(36),
    submitted_by_id VARCHAR(36),
    submit_reason VARCHAR(20),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(submitted_by_id) REFERENCES users (id),
    FOREIGN KEY(submitted_message_id) REFERENCES chat_messages (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_task_pre_inputs_deadline_at ON sdd_task_pre_inputs (deadline_at);

CREATE INDEX ix_sdd_task_pre_inputs_status ON sdd_task_pre_inputs (status);

CREATE INDEX ix_sdd_task_pre_inputs_task_id ON sdd_task_pre_inputs (task_id);

CREATE INDEX ix_sdd_task_pre_inputs_workspace_id ON sdd_task_pre_inputs (workspace_id);

CREATE TABLE sdd_task_requirements (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    requirement_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    relation_type taskrequirementrelationtype NOT NULL,
    created_by_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(created_by_id) REFERENCES users (id),
    FOREIGN KEY(requirement_id) REFERENCES sdd_requirements (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_task_requirements_requirement_task UNIQUE (requirement_id, task_id)
);

CREATE INDEX ix_sdd_task_requirements_created_by_id ON sdd_task_requirements (created_by_id);

CREATE INDEX ix_sdd_task_requirements_relation_type ON sdd_task_requirements (relation_type);

CREATE INDEX ix_sdd_task_requirements_requirement_id ON sdd_task_requirements (requirement_id);

CREATE INDEX ix_sdd_task_requirements_task_id ON sdd_task_requirements (task_id);

CREATE INDEX ix_sdd_task_requirements_workspace_id ON sdd_task_requirements (workspace_id);

CREATE TABLE sdd_test_results (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    plan_node_id VARCHAR(36),
    test_type testtype NOT NULL,
    test_name VARCHAR(300) NOT NULL,
    status teststatus NOT NULL,
    duration_ms INTEGER,
    error_detail TEXT,
    report_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(plan_node_id) REFERENCES sdd_plan_nodes (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
);

CREATE INDEX ix_sdd_test_results_task_id ON sdd_test_results (task_id);

CREATE INDEX ix_sdd_test_results_workspace_id ON sdd_test_results (workspace_id);

CREATE TABLE task_collaboration_snapshots (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    manifest_json JSON NOT NULL,
    content_digest VARCHAR(64) NOT NULL,
    source VARCHAR(32) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_collaboration_snapshot_manifest FOREIGN KEY(task_id, content_digest) REFERENCES task_collaboration_manifests (task_id, content_digest) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_collaboration_snapshot_lookup ON task_collaboration_snapshots (task_id, content_digest, source, created_at, id);

CREATE INDEX ix_task_collaboration_snapshots_task_id ON task_collaboration_snapshots (task_id);

CREATE TABLE task_playbook_bindings (
    task_id VARCHAR(36) NOT NULL,
    active_run_id VARCHAR(36),
    PRIMARY KEY (task_id),
    FOREIGN KEY(active_run_id) REFERENCES playbook_runs (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE
);

CREATE TABLE sdd_api_mock_endpoints (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    source_version_id VARCHAR(36) NOT NULL,
    method VARCHAR(16) NOT NULL,
    path VARCHAR(800) NOT NULL,
    operation_id VARCHAR(255),
    tag VARCHAR(255),
    summary TEXT,
    row_version INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES sdd_api_mock_projects (id) ON DELETE CASCADE,
    FOREIGN KEY(source_version_id) REFERENCES sdd_api_mock_source_versions (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_api_mock_endpoints_project_id ON sdd_api_mock_endpoints (project_id);

CREATE INDEX ix_sdd_api_mock_endpoints_source_version_id ON sdd_api_mock_endpoints (source_version_id);

CREATE TABLE sdd_asset_threads (
    id VARCHAR(36) NOT NULL,
    asset_id VARCHAR(36) NOT NULL,
    version_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    block_id VARCHAR(120) NOT NULL,
    selected_text TEXT,
    char_start INTEGER,
    char_end INTEGER,
    status assetthreadstatus NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    resolved_by VARCHAR(36),
    resolved_at TIMESTAMP WITHOUT TIME ZONE,
    resolved_version_id VARCHAR(36),
    close_hint_state VARCHAR(32) NOT NULL,
    close_hint_reason VARCHAR(64),
    cli_session_id VARCHAR(120),
    close_hint_version_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(asset_id) REFERENCES sdd_assets (id) ON DELETE CASCADE,
    FOREIGN KEY(close_hint_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(resolved_by) REFERENCES users (id),
    FOREIGN KEY(resolved_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES sdd_asset_versions (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_asset_threads_asset_id ON sdd_asset_threads (asset_id);

CREATE INDEX ix_sdd_asset_threads_block_id ON sdd_asset_threads (block_id);

CREATE INDEX ix_sdd_asset_threads_close_hint_version_id ON sdd_asset_threads (close_hint_version_id);

CREATE INDEX ix_sdd_asset_threads_creator_id ON sdd_asset_threads (creator_id);

CREATE INDEX ix_sdd_asset_threads_resolved_by ON sdd_asset_threads (resolved_by);

CREATE INDEX ix_sdd_asset_threads_resolved_version_id ON sdd_asset_threads (resolved_version_id);

CREATE INDEX ix_sdd_asset_threads_task_id ON sdd_asset_threads (task_id);

CREATE INDEX ix_sdd_asset_threads_version_id ON sdd_asset_threads (version_id);

CREATE INDEX ix_sdd_asset_threads_workspace_id ON sdd_asset_threads (workspace_id);

CREATE TABLE sdd_task_baselines (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    summary_id VARCHAR(36),
    version INTEGER NOT NULL,
    snapshot_json JSON,
    baselined_by_id VARCHAR(36),
    is_rollback BOOLEAN NOT NULL,
    rollback_from_version INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(baselined_by_id) REFERENCES users (id),
    FOREIGN KEY(summary_id) REFERENCES sdd_task_final_summaries (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_task_baselines_task_version UNIQUE (task_id, version)
);

CREATE INDEX ix_sdd_task_baselines_baselined_by_id ON sdd_task_baselines (baselined_by_id);

CREATE INDEX ix_sdd_task_baselines_summary_id ON sdd_task_baselines (summary_id);

CREATE INDEX ix_sdd_task_baselines_task_id ON sdd_task_baselines (task_id);

CREATE INDEX ix_sdd_task_baselines_workspace_id ON sdd_task_baselines (workspace_id);

CREATE TABLE sdd_task_change_proposals (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    proposal_no INTEGER NOT NULL,
    patch_set_no INTEGER NOT NULL,
    status changeproposalstatus NOT NULL,
    base_repo_url VARCHAR(1000),
    base_branch VARCHAR(255) NOT NULL,
    base_commit_sha VARCHAR(64) NOT NULL,
    cloud_task_branch VARCHAR(255) NOT NULL,
    cloud_head_sha VARCHAR(64),
    changed_files_count INTEGER NOT NULL,
    insertions INTEGER NOT NULL,
    deletions INTEGER NOT NULL,
    summary TEXT,
    risk_notes TEXT,
    patch_asset_id VARCHAR(36),
    patch_asset_version_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(patch_asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(patch_asset_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_task_change_proposals_task_patch_set_no UNIQUE (task_id, patch_set_no),
    CONSTRAINT uq_task_change_proposals_task_proposal_no UNIQUE (task_id, proposal_no)
);

CREATE INDEX ix_sdd_task_change_proposals_patch_asset_id ON sdd_task_change_proposals (patch_asset_id);

CREATE INDEX ix_sdd_task_change_proposals_patch_asset_version_id ON sdd_task_change_proposals (patch_asset_version_id);

CREATE INDEX ix_sdd_task_change_proposals_status ON sdd_task_change_proposals (status);

CREATE INDEX ix_sdd_task_change_proposals_task_id ON sdd_task_change_proposals (task_id);

CREATE INDEX ix_sdd_task_change_proposals_workspace_id ON sdd_task_change_proposals (workspace_id);

CREATE TABLE sdd_task_pre_input_contributions (
    id VARCHAR(36) NOT NULL,
    pre_input_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(pre_input_id) REFERENCES sdd_task_pre_inputs (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id),
    CONSTRAINT uq_pre_input_contribution_user UNIQUE (pre_input_id, user_id)
);

CREATE INDEX ix_sdd_task_pre_input_contributions_pre_input_id ON sdd_task_pre_input_contributions (pre_input_id);

CREATE TABLE sdd_task_pre_input_mentions (
    pre_input_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (pre_input_id, user_id),
    FOREIGN KEY(pre_input_id) REFERENCES sdd_task_pre_inputs (id) ON DELETE CASCADE
);

CREATE INDEX ix_pre_input_mentions_user ON sdd_task_pre_input_mentions (user_id, pre_input_id);

CREATE TABLE sdd_ai_jobs (
    id VARCHAR(36) NOT NULL,
    queue_source VARCHAR(40),
    job_type VARCHAR(80),
    resource_id VARCHAR(190),
    execution_backend VARCHAR(40) DEFAULT 'durable' NOT NULL,
    external_task_id VARCHAR(190),
    visibility VARCHAR(20) DEFAULT 'workspace' NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    state_changed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    stage VARCHAR(128),
    completion_json JSON,
    retry_of_job_id VARCHAR(36),
    command_key VARCHAR(190),
    schedule_id VARCHAR(80),
    scheduled_for TIMESTAMP WITHOUT TIME ZONE,
    workspace_id VARCHAR(36),
    task_id VARCHAR(36),
    asset_id VARCHAR(36),
    thread_id VARCHAR(36),
    channel aijobchannel NOT NULL,
    queue_key VARCHAR(190) NOT NULL,
    status aijobstatus NOT NULL,
    progress INTEGER NOT NULL,
    message TEXT,
    prompt_text TEXT,
    context_json JSON,
    provider_execution_json JSON,
    agent_service_binding JSON,
    result_json JSON,
    error_message TEXT,
    session_id VARCHAR(120),
    agent_backend VARCHAR(40),
    session_turn_id VARCHAR(36),
    session_generation INTEGER,
    session_revision INTEGER,
    interrupt_reason TEXT,
    interrupted_by_id VARCHAR(36),
    interrupted_at TIMESTAMP WITHOUT TIME ZONE,
    creator_id VARCHAR(36) NOT NULL,
    started_at TIMESTAMP WITHOUT TIME ZONE,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    awareness_state VARCHAR(40),
    awareness_version INTEGER DEFAULT '0' NOT NULL,
    awareness_pending_json JSON,
    attempt_count INTEGER DEFAULT '0' NOT NULL,
    max_attempts INTEGER DEFAULT '1' NOT NULL,
    run_token VARCHAR(36),
    worker_id VARCHAR(190),
    worker_boot_id VARCHAR(36),
    heartbeat_at TIMESTAMP WITHOUT TIME ZONE,
    lease_expires_at TIMESTAMP WITHOUT TIME ZONE,
    cancel_requested_at TIMESTAMP WITHOUT TIME ZONE,
    process_pid BIGINT,
    process_started_at TIMESTAMP WITHOUT TIME ZONE,
    process_group_id BIGINT,
    process_containment_id VARCHAR(120),
    process_execution_kind VARCHAR(20),
    termination_attempts INTEGER DEFAULT '0' NOT NULL,
    failure_code VARCHAR(64),
    terminal_reason TEXT,
    orphaned_at TIMESTAMP WITHOUT TIME ZONE,
    first_failure_at TIMESTAMP WITHOUT TIME ZONE,
    last_reap_attempt_at TIMESTAMP WITHOUT TIME ZONE,
    last_reap_verified_at TIMESTAMP WITHOUT TIME ZONE,
    next_reap_at TIMESTAMP WITHOUT TIME ZONE,
    reap_failure_count INTEGER DEFAULT '0' NOT NULL,
    last_reap_error TEXT,
    manual_intervention_required BOOLEAN DEFAULT '0' NOT NULL,
    manual_intervention_operator_id VARCHAR(36),
    manual_intervention_reason TEXT,
    manual_intervention_evidence TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(interrupted_by_id) REFERENCES users (id),
    FOREIGN KEY(manual_intervention_operator_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE SET NULL,
    FOREIGN KEY(thread_id) REFERENCES sdd_asset_threads (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    UNIQUE (command_key)
);

CREATE INDEX ix_sdd_ai_jobs_asset_id ON sdd_ai_jobs (asset_id);

CREATE INDEX ix_sdd_ai_jobs_creator_id ON sdd_ai_jobs (creator_id);

CREATE INDEX ix_sdd_ai_jobs_listing ON sdd_ai_jobs (queue_source, workspace_id, status, state_changed_at, id);

CREATE INDEX ix_sdd_ai_jobs_next_reap_at ON sdd_ai_jobs (next_reap_at);

CREATE INDEX ix_sdd_ai_jobs_queue_claim ON sdd_ai_jobs (queue_key, status, created_at, id);

CREATE INDEX ix_sdd_ai_jobs_queue_key ON sdd_ai_jobs (queue_key);

CREATE INDEX ix_sdd_ai_jobs_queue_source ON sdd_ai_jobs (queue_source);

CREATE INDEX ix_sdd_ai_jobs_reclaim ON sdd_ai_jobs (status, lease_expires_at);

CREATE INDEX ix_sdd_ai_jobs_retry_of_job_id ON sdd_ai_jobs (retry_of_job_id);

CREATE INDEX ix_sdd_ai_jobs_session_generation ON sdd_ai_jobs (session_generation);

CREATE INDEX ix_sdd_ai_jobs_session_revision ON sdd_ai_jobs (session_revision);

CREATE INDEX ix_sdd_ai_jobs_session_turn_id ON sdd_ai_jobs (session_turn_id);

CREATE INDEX ix_sdd_ai_jobs_status ON sdd_ai_jobs (status);

CREATE INDEX ix_sdd_ai_jobs_task_id ON sdd_ai_jobs (task_id);

CREATE INDEX ix_sdd_ai_jobs_thread_id ON sdd_ai_jobs (thread_id);

CREATE INDEX ix_sdd_ai_jobs_worker_active ON sdd_ai_jobs (worker_id, worker_boot_id, status);

CREATE INDEX ix_sdd_ai_jobs_workspace_id ON sdd_ai_jobs (workspace_id);

CREATE TABLE sdd_api_mock_collab_events (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    endpoint_id VARCHAR(36),
    user_id VARCHAR(36) NOT NULL,
    event_type apimockcollabeventtype NOT NULL,
    payload_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(endpoint_id) REFERENCES sdd_api_mock_endpoints (id) ON DELETE SET NULL,
    FOREIGN KEY(project_id) REFERENCES sdd_api_mock_projects (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_sdd_api_mock_collab_events_endpoint_id ON sdd_api_mock_collab_events (endpoint_id);

CREATE INDEX ix_sdd_api_mock_collab_events_project_id ON sdd_api_mock_collab_events (project_id);

CREATE INDEX ix_sdd_api_mock_collab_events_user_id ON sdd_api_mock_collab_events (user_id);

CREATE TABLE sdd_api_mock_entities (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    source_version_id VARCHAR(36) NOT NULL,
    endpoint_id VARCHAR(36),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    row_version INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(endpoint_id) REFERENCES sdd_api_mock_endpoints (id) ON DELETE SET NULL,
    FOREIGN KEY(project_id) REFERENCES sdd_api_mock_projects (id) ON DELETE CASCADE,
    FOREIGN KEY(source_version_id) REFERENCES sdd_api_mock_source_versions (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_api_mock_entities_endpoint_id ON sdd_api_mock_entities (endpoint_id);

CREATE INDEX ix_sdd_api_mock_entities_project_id ON sdd_api_mock_entities (project_id);

CREATE INDEX ix_sdd_api_mock_entities_source_version_id ON sdd_api_mock_entities (source_version_id);

CREATE TABLE sdd_api_mock_rules (
    id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    endpoint_id VARCHAR(36) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL,
    sort_order INTEGER NOT NULL,
    mode apimockrulemode NOT NULL,
    request_path_params_json JSON,
    request_query_json JSON,
    request_body_json JSON,
    static_body_json JSON,
    mockjs_template TEXT,
    status_code INTEGER NOT NULL,
    headers_json JSON,
    cookies_json JSON,
    delay_ms INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL,
    updated_by VARCHAR(36) NOT NULL,
    row_version INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(endpoint_id) REFERENCES sdd_api_mock_endpoints (id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES sdd_api_mock_projects (id) ON DELETE CASCADE,
    FOREIGN KEY(updated_by) REFERENCES users (id)
);

CREATE INDEX ix_sdd_api_mock_rules_endpoint_id ON sdd_api_mock_rules (endpoint_id);

CREATE INDEX ix_sdd_api_mock_rules_project_id ON sdd_api_mock_rules (project_id);

CREATE INDEX ix_sdd_api_mock_rules_updated_by ON sdd_api_mock_rules (updated_by);

CREATE TABLE sdd_asset_resolution_proposals (
    id VARCHAR(36) NOT NULL,
    thread_id VARCHAR(36) NOT NULL,
    base_version_id VARCHAR(36) NOT NULL,
    proposed_patch_json JSON,
    diff_text TEXT,
    status assetresolutionproposalstatus NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(base_version_id) REFERENCES sdd_asset_versions (id) ON DELETE CASCADE,
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(thread_id) REFERENCES sdd_asset_threads (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_asset_resolution_proposals_base_version_id ON sdd_asset_resolution_proposals (base_version_id);

CREATE INDEX ix_sdd_asset_resolution_proposals_creator_id ON sdd_asset_resolution_proposals (creator_id);

CREATE INDEX ix_sdd_asset_resolution_proposals_thread_id ON sdd_asset_resolution_proposals (thread_id);

CREATE TABLE sdd_asset_thread_anchor_mappings (
    id VARCHAR(36) NOT NULL,
    thread_id VARCHAR(36) NOT NULL,
    version_id VARCHAR(36) NOT NULL,
    block_id VARCHAR(120) NOT NULL,
    selected_text TEXT,
    char_start INTEGER,
    char_end INTEGER,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(created_by) REFERENCES users (id),
    FOREIGN KEY(thread_id) REFERENCES sdd_asset_threads (id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES sdd_asset_versions (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_asset_thread_anchor_mapping_thread_version UNIQUE (thread_id, version_id)
);

CREATE INDEX ix_sdd_asset_thread_anchor_mappings_created_by ON sdd_asset_thread_anchor_mappings (created_by);

CREATE INDEX ix_sdd_asset_thread_anchor_mappings_thread_id ON sdd_asset_thread_anchor_mappings (thread_id);

CREATE INDEX ix_sdd_asset_thread_anchor_mappings_version_id ON sdd_asset_thread_anchor_mappings (version_id);

CREATE TABLE sdd_asset_thread_messages (
    id VARCHAR(36) NOT NULL,
    thread_id VARCHAR(36) NOT NULL,
    role assetthreadmessagerole NOT NULL,
    content TEXT NOT NULL,
    creator_id VARCHAR(36),
    metadata_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(thread_id) REFERENCES sdd_asset_threads (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_asset_thread_messages_creator_id ON sdd_asset_thread_messages (creator_id);

CREATE INDEX ix_sdd_asset_thread_messages_thread_id ON sdd_asset_thread_messages (thread_id);

CREATE TABLE sdd_task_change_proposal_repos (
    id VARCHAR(36) NOT NULL,
    proposal_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36),
    repo_url VARCHAR(1000),
    repo_name VARCHAR(200) NOT NULL,
    repo_slug VARCHAR(120) NOT NULL,
    base_branch VARCHAR(255) NOT NULL,
    base_commit_sha VARCHAR(64) NOT NULL,
    cloud_task_branch VARCHAR(255) NOT NULL,
    cloud_head_sha VARCHAR(64),
    changed_files_count INTEGER NOT NULL,
    insertions INTEGER NOT NULL,
    deletions INTEGER NOT NULL,
    patch_asset_id VARCHAR(36),
    patch_asset_version_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(patch_asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(patch_asset_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(proposal_id) REFERENCES sdd_task_change_proposals (id) ON DELETE CASCADE,
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE SET NULL
);

CREATE INDEX ix_sdd_task_change_proposal_repos_patch_asset_id ON sdd_task_change_proposal_repos (patch_asset_id);

CREATE INDEX ix_sdd_task_change_proposal_repos_patch_asset_version_id ON sdd_task_change_proposal_repos (patch_asset_version_id);

CREATE INDEX ix_sdd_task_change_proposal_repos_proposal_id ON sdd_task_change_proposal_repos (proposal_id);

CREATE INDEX ix_sdd_task_change_proposal_repos_repository_id ON sdd_task_change_proposal_repos (repository_id);

CREATE TABLE sdd_task_conflict_reports (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    proposal_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    agent_id VARCHAR(120),
    machine_name VARCHAR(255),
    base_commit_sha VARCHAR(64) NOT NULL,
    local_head_sha VARCHAR(64),
    conflicted_files_json JSON,
    git_apply_stderr TEXT,
    conflict_excerpt TEXT,
    report_asset_id VARCHAR(36),
    report_asset_version_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(proposal_id) REFERENCES sdd_task_change_proposals (id) ON DELETE CASCADE,
    FOREIGN KEY(report_asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(report_asset_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_task_conflict_reports_proposal_id ON sdd_task_conflict_reports (proposal_id);

CREATE INDEX ix_sdd_task_conflict_reports_report_asset_id ON sdd_task_conflict_reports (report_asset_id);

CREATE INDEX ix_sdd_task_conflict_reports_report_asset_version_id ON sdd_task_conflict_reports (report_asset_version_id);

CREATE INDEX ix_sdd_task_conflict_reports_task_id ON sdd_task_conflict_reports (task_id);

CREATE INDEX ix_sdd_task_conflict_reports_user_id ON sdd_task_conflict_reports (user_id);

CREATE INDEX ix_sdd_task_conflict_reports_workspace_id ON sdd_task_conflict_reports (workspace_id);

CREATE TABLE sdd_task_verification_runs (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    proposal_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    agent_id VARCHAR(120),
    machine_name VARCHAR(255),
    os_name VARCHAR(255),
    command TEXT,
    status verificationrunstatus NOT NULL,
    duration_ms BIGINT,
    base_commit_sha VARCHAR(64) NOT NULL,
    local_head_sha VARCHAR(64),
    log_excerpt TEXT,
    log_asset_id VARCHAR(36),
    log_asset_version_id VARCHAR(36),
    started_at TIMESTAMP WITHOUT TIME ZONE,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(log_asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(log_asset_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(proposal_id) REFERENCES sdd_task_change_proposals (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_task_verification_runs_log_asset_id ON sdd_task_verification_runs (log_asset_id);

CREATE INDEX ix_sdd_task_verification_runs_log_asset_version_id ON sdd_task_verification_runs (log_asset_version_id);

CREATE INDEX ix_sdd_task_verification_runs_proposal_id ON sdd_task_verification_runs (proposal_id);

CREATE INDEX ix_sdd_task_verification_runs_status ON sdd_task_verification_runs (status);

CREATE INDEX ix_sdd_task_verification_runs_task_id ON sdd_task_verification_runs (task_id);

CREATE INDEX ix_sdd_task_verification_runs_user_id ON sdd_task_verification_runs (user_id);

CREATE INDEX ix_sdd_task_verification_runs_workspace_id ON sdd_task_verification_runs (workspace_id);

CREATE TABLE sdd_ai_outputs (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36),
    ai_job_id VARCHAR(36) NOT NULL,
    asset_id VARCHAR(36),
    asset_version_id VARCHAR(36),
    output_type aioutputtype NOT NULL,
    title VARCHAR(300),
    content_text TEXT,
    content_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(ai_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(asset_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_ai_outputs_ai_job_id ON sdd_ai_outputs (ai_job_id);

CREATE INDEX ix_sdd_ai_outputs_asset_id ON sdd_ai_outputs (asset_id);

CREATE INDEX ix_sdd_ai_outputs_asset_version_id ON sdd_ai_outputs (asset_version_id);

CREATE INDEX ix_sdd_ai_outputs_output_type ON sdd_ai_outputs (output_type);

CREATE INDEX ix_sdd_ai_outputs_task_id ON sdd_ai_outputs (task_id);

CREATE INDEX ix_sdd_ai_outputs_workspace_id ON sdd_ai_outputs (workspace_id);

CREATE TABLE sdd_context_token_snapshots (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    ai_job_id VARCHAR(36),
    session_id VARCHAR(120),
    model VARCHAR(120),
    status VARCHAR(40) NOT NULL,
    input_tokens BIGINT,
    output_tokens BIGINT,
    cache_read_tokens BIGINT,
    cache_creation_tokens BIGINT,
    thinking_tokens BIGINT,
    tool_io_tokens BIGINT,
    total_tokens BIGINT,
    total_cost_usd FLOAT,
    duration_ms BIGINT,
    raw_usage_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(ai_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_context_token_snapshots_ai_job_id ON sdd_context_token_snapshots (ai_job_id);

CREATE INDEX ix_sdd_context_token_snapshots_session_id ON sdd_context_token_snapshots (session_id);

CREATE INDEX ix_sdd_context_token_snapshots_status ON sdd_context_token_snapshots (status);

CREATE INDEX ix_sdd_context_token_snapshots_task_created ON sdd_context_token_snapshots (task_id, created_at);

CREATE INDEX ix_sdd_context_token_snapshots_task_id ON sdd_context_token_snapshots (task_id);

CREATE INDEX ix_sdd_context_token_snapshots_workspace_id ON sdd_context_token_snapshots (workspace_id);

CREATE INDEX ix_sdd_context_token_snapshots_workspace_task ON sdd_context_token_snapshots (workspace_id, task_id);

CREATE TABLE sdd_evidence (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    requirement_id VARCHAR(36),
    task_id VARCHAR(36),
    ai_job_id VARCHAR(36),
    human_review_id VARCHAR(36),
    created_by_id VARCHAR(36),
    confirmed_by_id VARCHAR(36),
    status evidencestatus NOT NULL,
    evidence_type evidencetype NOT NULL,
    source_type evidencesourcetype NOT NULL,
    source_uri VARCHAR(1000),
    source_label VARCHAR(300),
    source_ref VARCHAR(300),
    source_path VARCHAR(1000),
    source_metadata_json JSON,
    title VARCHAR(300),
    summary TEXT,
    confirmed_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(ai_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY(confirmed_by_id) REFERENCES users (id),
    FOREIGN KEY(created_by_id) REFERENCES users (id),
    FOREIGN KEY(human_review_id) REFERENCES sdd_human_reviews (id) ON DELETE SET NULL,
    FOREIGN KEY(requirement_id) REFERENCES sdd_requirements (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_evidence_ai_job_id ON sdd_evidence (ai_job_id);

CREATE INDEX ix_sdd_evidence_confirmed_by_id ON sdd_evidence (confirmed_by_id);

CREATE INDEX ix_sdd_evidence_created_by_id ON sdd_evidence (created_by_id);

CREATE INDEX ix_sdd_evidence_evidence_type ON sdd_evidence (evidence_type);

CREATE INDEX ix_sdd_evidence_human_review_id ON sdd_evidence (human_review_id);

CREATE INDEX ix_sdd_evidence_requirement_id ON sdd_evidence (requirement_id);

CREATE INDEX ix_sdd_evidence_source_type ON sdd_evidence (source_type);

CREATE INDEX ix_sdd_evidence_status ON sdd_evidence (status);

CREATE INDEX ix_sdd_evidence_task_id ON sdd_evidence (task_id);

CREATE INDEX ix_sdd_evidence_workspace_id ON sdd_evidence (workspace_id);

CREATE TABLE sdd_job_attempts (
    id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36) NOT NULL,
    number INTEGER NOT NULL,
    run_token VARCHAR(36) NOT NULL,
    worker_id VARCHAR(190),
    worker_boot_id VARCHAR(36),
    started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    outcome VARCHAR(40),
    failure_code VARCHAR(64),
    PRIMARY KEY (id),
    FOREIGN KEY(job_id) REFERENCES sdd_ai_jobs (id) ON DELETE CASCADE,
    CONSTRAINT uq_job_attempt_number UNIQUE (job_id, number)
);

CREATE TABLE sdd_job_events (
    id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36) NOT NULL,
    version INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    payload_json JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    published_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(job_id) REFERENCES sdd_ai_jobs (id) ON DELETE CASCADE,
    CONSTRAINT uq_job_event_version UNIQUE (job_id, version)
);

CREATE INDEX ix_job_event_delivery ON sdd_job_events (published_at, created_at);

CREATE TABLE sdd_skill_runtime_events (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    skill_id VARCHAR(36),
    ai_job_id VARCHAR(36),
    tool_use_id VARCHAR(200),
    event_type skillruntimeeventtype NOT NULL,
    evidence_level skillruntimeevidencelevel NOT NULL,
    materialized_dir VARCHAR(500),
    matched_path VARCHAR(1000),
    relative_path VARCHAR(1000),
    tool_name VARCHAR(200),
    tool_input_json JSON,
    tool_result_preview TEXT,
    status skillruntimeeventstatus NOT NULL,
    confidence FLOAT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(ai_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY(skill_id) REFERENCES sdd_skills (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_skill_runtime_events_ai_job_id ON sdd_skill_runtime_events (ai_job_id);

CREATE INDEX ix_sdd_skill_runtime_events_created_at ON sdd_skill_runtime_events (created_at);

CREATE INDEX ix_sdd_skill_runtime_events_event_type ON sdd_skill_runtime_events (event_type);

CREATE INDEX ix_sdd_skill_runtime_events_materialized_dir ON sdd_skill_runtime_events (materialized_dir);

CREATE INDEX ix_sdd_skill_runtime_events_skill_id ON sdd_skill_runtime_events (skill_id);

CREATE INDEX ix_sdd_skill_runtime_events_status ON sdd_skill_runtime_events (status);

CREATE INDEX ix_sdd_skill_runtime_events_task_id ON sdd_skill_runtime_events (task_id);

CREATE INDEX ix_sdd_skill_runtime_events_tool_use_id ON sdd_skill_runtime_events (tool_use_id);

CREATE INDEX ix_sdd_skill_runtime_events_workspace_id ON sdd_skill_runtime_events (workspace_id);

CREATE TABLE sdd_task_change_proposal_files (
    id VARCHAR(36) NOT NULL,
    proposal_id VARCHAR(36) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    old_path VARCHAR(1000),
    new_path VARCHAR(1000),
    repository_id VARCHAR(36),
    proposal_repo_id VARCHAR(36),
    change_type changeproposalfiletype NOT NULL,
    insertions INTEGER NOT NULL,
    deletions INTEGER NOT NULL,
    diff_excerpt TEXT,
    is_binary BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(proposal_id) REFERENCES sdd_task_change_proposals (id) ON DELETE CASCADE,
    FOREIGN KEY(proposal_repo_id) REFERENCES sdd_task_change_proposal_repos (id) ON DELETE SET NULL,
    FOREIGN KEY(repository_id) REFERENCES mgmt_repositories (id) ON DELETE SET NULL
);

CREATE INDEX ix_sdd_task_change_proposal_files_proposal_id ON sdd_task_change_proposal_files (proposal_id);

CREATE INDEX ix_sdd_task_change_proposal_files_proposal_repo_id ON sdd_task_change_proposal_files (proposal_repo_id);

CREATE INDEX ix_sdd_task_change_proposal_files_repository_id ON sdd_task_change_proposal_files (repository_id);

CREATE TABLE sdd_task_chat_submissions (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    client_message_id VARCHAR(128) NOT NULL,
    content TEXT NOT NULL,
    metadata_json JSON,
    payload_hash VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL,
    version INTEGER NOT NULL,
    active_task_id VARCHAR(36),
    session_generation INTEGER NOT NULL,
    session_revision INTEGER NOT NULL,
    ai_job_id VARCHAR(36),
    chat_message_id VARCHAR(36),
    error_message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(ai_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY(chat_message_id) REFERENCES chat_messages (id) ON DELETE SET NULL,
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_chat_submission_active_task UNIQUE (active_task_id),
    CONSTRAINT uq_chat_submission_client UNIQUE (task_id, creator_id, client_message_id)
);

CREATE INDEX ix_sdd_task_chat_submissions_ai_job_id ON sdd_task_chat_submissions (ai_job_id);

CREATE INDEX ix_sdd_task_chat_submissions_status ON sdd_task_chat_submissions (status);

CREATE INDEX ix_sdd_task_chat_submissions_task_id ON sdd_task_chat_submissions (task_id);

CREATE TABLE sdd_task_cli_bootstraps (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    spec_asset_id VARCHAR(36),
    spec_version_id VARCHAR(36),
    status taskclibootstrapstatus NOT NULL,
    progress INTEGER NOT NULL,
    message TEXT,
    execution_job_id VARCHAR(36),
    baseline_dir VARCHAR(700),
    baseline_session_id VARCHAR(120),
    agent_backend VARCHAR(40),
    error_message TEXT,
    refresh_mode VARCHAR(16) NOT NULL,
    refresh_context_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(execution_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY(spec_asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(spec_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_task_cli_bootstraps_execution_job_id ON sdd_task_cli_bootstraps (execution_job_id);

CREATE INDEX ix_sdd_task_cli_bootstraps_spec_asset_id ON sdd_task_cli_bootstraps (spec_asset_id);

CREATE INDEX ix_sdd_task_cli_bootstraps_spec_version_id ON sdd_task_cli_bootstraps (spec_version_id);

CREATE INDEX ix_sdd_task_cli_bootstraps_status ON sdd_task_cli_bootstraps (status);

CREATE UNIQUE INDEX ix_sdd_task_cli_bootstraps_task_id ON sdd_task_cli_bootstraps (task_id);

CREATE INDEX ix_sdd_task_cli_bootstraps_workspace_id ON sdd_task_cli_bootstraps (workspace_id);

CREATE TABLE sdd_task_session_turns (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    user_message_id VARCHAR(36),
    ai_job_id VARCHAR(36),
    session_generation INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    session_revision INTEGER NOT NULL,
    provider VARCHAR(40) NOT NULL,
    provider_session_id VARCHAR(120),
    provider_message_ids_json JSON,
    checkpoint_path VARCHAR(1000),
    worktree_snapshot_path VARCHAR(1000),
    status tasksessionturnstatus NOT NULL,
    operation_id VARCHAR(80),
    reverted_at TIMESTAMP WITHOUT TIME ZONE,
    reverted_by_id VARCHAR(36),
    error_code VARCHAR(80),
    error_message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(ai_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY(reverted_by_id) REFERENCES users (id),
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(user_message_id) REFERENCES chat_messages (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    UNIQUE (ai_job_id),
    CONSTRAINT uq_task_session_turn_index UNIQUE (task_id, session_generation, turn_index),
    UNIQUE (user_message_id)
);

CREATE INDEX ix_sdd_task_session_turns_operation_id ON sdd_task_session_turns (operation_id);

CREATE INDEX ix_sdd_task_session_turns_session_generation ON sdd_task_session_turns (session_generation);

CREATE INDEX ix_sdd_task_session_turns_session_revision ON sdd_task_session_turns (session_revision);

CREATE INDEX ix_sdd_task_session_turns_status ON sdd_task_session_turns (status);

CREATE INDEX ix_sdd_task_session_turns_task_id ON sdd_task_session_turns (task_id);

CREATE INDEX ix_sdd_task_session_turns_workspace_id ON sdd_task_session_turns (workspace_id);

CREATE TABLE sdd_clarifications (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    requirement_id VARCHAR(36),
    requester_id VARCHAR(36),
    responder_id VARCHAR(36),
    source_evidence_id VARCHAR(36),
    source_review_id VARCHAR(36),
    converted_requirement_id VARCHAR(36),
    status clarificationstatus NOT NULL,
    blocking_level clarificationblockinglevel NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    clarification_type VARCHAR(80),
    target_ref_json JSON,
    urgency VARCHAR(40),
    answered_at TIMESTAMP WITHOUT TIME ZONE,
    accepted_at TIMESTAMP WITHOUT TIME ZONE,
    promote_candidate BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(converted_requirement_id) REFERENCES sdd_requirements (id) ON DELETE SET NULL,
    FOREIGN KEY(requester_id) REFERENCES users (id),
    FOREIGN KEY(requirement_id) REFERENCES sdd_requirements (id) ON DELETE SET NULL,
    FOREIGN KEY(responder_id) REFERENCES users (id),
    FOREIGN KEY(source_evidence_id) REFERENCES sdd_evidence (id) ON DELETE SET NULL,
    FOREIGN KEY(source_review_id) REFERENCES sdd_human_reviews (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_clarifications_blocking_level ON sdd_clarifications (blocking_level);

CREATE INDEX ix_sdd_clarifications_converted_requirement_id ON sdd_clarifications (converted_requirement_id);

CREATE INDEX ix_sdd_clarifications_requester_id ON sdd_clarifications (requester_id);

CREATE INDEX ix_sdd_clarifications_requirement_id ON sdd_clarifications (requirement_id);

CREATE INDEX ix_sdd_clarifications_responder_id ON sdd_clarifications (responder_id);

CREATE INDEX ix_sdd_clarifications_source_review_id ON sdd_clarifications (source_review_id);

CREATE INDEX ix_sdd_clarifications_status ON sdd_clarifications (status);

CREATE INDEX ix_sdd_clarifications_task_id ON sdd_clarifications (task_id);

CREATE INDEX ix_sdd_clarifications_workspace_id ON sdd_clarifications (workspace_id);

CREATE TABLE sdd_context_token_segments (
    id VARCHAR(36) NOT NULL,
    snapshot_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    ai_job_id VARCHAR(36),
    category contexttokencategory NOT NULL,
    provider_tokens BIGINT,
    attribution_units BIGINT NOT NULL,
    char_count BIGINT NOT NULL,
    byte_count BIGINT NOT NULL,
    source_kind VARCHAR(80) NOT NULL,
    source_ref_id VARCHAR(120),
    chat_message_id VARCHAR(36),
    asset_id VARCHAR(36),
    asset_version_id VARCHAR(36),
    skill_runtime_event_id VARCHAR(36),
    tool_use_id VARCHAR(200),
    content_hash VARCHAR(64),
    locator_json JSON,
    title VARCHAR(300),
    preview VARCHAR(600),
    metadata_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(ai_job_id) REFERENCES sdd_ai_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY(asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(asset_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(chat_message_id) REFERENCES chat_messages (id) ON DELETE SET NULL,
    FOREIGN KEY(skill_runtime_event_id) REFERENCES sdd_skill_runtime_events (id) ON DELETE SET NULL,
    FOREIGN KEY(snapshot_id) REFERENCES sdd_context_token_snapshots (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_context_token_segments_ai_job_id ON sdd_context_token_segments (ai_job_id);

CREATE INDEX ix_sdd_context_token_segments_asset_id ON sdd_context_token_segments (asset_id);

CREATE INDEX ix_sdd_context_token_segments_asset_version_id ON sdd_context_token_segments (asset_version_id);

CREATE INDEX ix_sdd_context_token_segments_category ON sdd_context_token_segments (category);

CREATE INDEX ix_sdd_context_token_segments_chat_message_id ON sdd_context_token_segments (chat_message_id);

CREATE INDEX ix_sdd_context_token_segments_content_hash ON sdd_context_token_segments (content_hash);

CREATE INDEX ix_sdd_context_token_segments_created_at ON sdd_context_token_segments (created_at);

CREATE INDEX ix_sdd_context_token_segments_skill_runtime_event_id ON sdd_context_token_segments (skill_runtime_event_id);

CREATE INDEX ix_sdd_context_token_segments_snapshot_category ON sdd_context_token_segments (snapshot_id, category);

CREATE INDEX ix_sdd_context_token_segments_snapshot_category_created ON sdd_context_token_segments (snapshot_id, category, created_at);

CREATE INDEX ix_sdd_context_token_segments_snapshot_id ON sdd_context_token_segments (snapshot_id);

CREATE INDEX ix_sdd_context_token_segments_source_kind ON sdd_context_token_segments (source_kind);

CREATE INDEX ix_sdd_context_token_segments_source_ref_id ON sdd_context_token_segments (source_ref_id);

CREATE INDEX ix_sdd_context_token_segments_task_id ON sdd_context_token_segments (task_id);

CREATE INDEX ix_sdd_context_token_segments_task_job ON sdd_context_token_segments (task_id, ai_job_id);

CREATE INDEX ix_sdd_context_token_segments_tool_use_id ON sdd_context_token_segments (tool_use_id);

CREATE INDEX ix_sdd_context_token_segments_workspace_id ON sdd_context_token_segments (workspace_id);

CREATE TABLE sdd_execution_logs (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    creator_id VARCHAR(36) NOT NULL,
    plan_node_id VARCHAR(36),
    phase phase,
    log_type logtype NOT NULL,
    content TEXT NOT NULL,
    event_order BIGINT,
    session_turn_id VARCHAR(36),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(creator_id) REFERENCES users (id),
    FOREIGN KEY(plan_node_id) REFERENCES sdd_plan_nodes (id),
    FOREIGN KEY(session_turn_id) REFERENCES sdd_task_session_turns (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
);

CREATE INDEX ix_sdd_execution_logs_session_turn_id ON sdd_execution_logs (session_turn_id);

CREATE INDEX ix_sdd_execution_logs_task_id ON sdd_execution_logs (task_id);

CREATE INDEX ix_sdd_execution_logs_task_replay_order ON sdd_execution_logs (task_id, event_order, created_at, id);

CREATE INDEX ix_sdd_execution_logs_workspace_id ON sdd_execution_logs (workspace_id);

CREATE TABLE sdd_human_deltas (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    created_by_id VARCHAR(36),
    collaboration_handoff_id VARCHAR(36),
    proposal_id VARCHAR(36),
    final_evidence_id VARCHAR(36),
    status humandeltastatus NOT NULL,
    diff_asset_id VARCHAR(36),
    changed_files_count INTEGER,
    insertions INTEGER,
    deletions INTEGER,
    comparison_summary TEXT,
    ai_patch_hash VARCHAR(64),
    human_patch_hash VARCHAR(64),
    change_category VARCHAR(100),
    change_reason TEXT,
    promote_candidate BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(collaboration_handoff_id) REFERENCES task_collaboration_handoffs (id) ON DELETE SET NULL,
    FOREIGN KEY(created_by_id) REFERENCES users (id),
    FOREIGN KEY(diff_asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(final_evidence_id) REFERENCES sdd_evidence (id) ON DELETE SET NULL,
    FOREIGN KEY(proposal_id) REFERENCES sdd_task_change_proposals (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    UNIQUE (collaboration_handoff_id)
);

CREATE INDEX ix_sdd_human_deltas_created_by_id ON sdd_human_deltas (created_by_id);

CREATE INDEX ix_sdd_human_deltas_diff_asset_id ON sdd_human_deltas (diff_asset_id);

CREATE INDEX ix_sdd_human_deltas_final_evidence_id ON sdd_human_deltas (final_evidence_id);

CREATE INDEX ix_sdd_human_deltas_proposal_id ON sdd_human_deltas (proposal_id);

CREATE INDEX ix_sdd_human_deltas_status ON sdd_human_deltas (status);

CREATE INDEX ix_sdd_human_deltas_task_id ON sdd_human_deltas (task_id);

CREATE INDEX ix_sdd_human_deltas_workspace_id ON sdd_human_deltas (workspace_id);

CREATE TABLE sdd_task_session_operations (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    operation_id VARCHAR(80) NOT NULL,
    target_turn_id VARCHAR(36),
    status tasksessionoperationstatus NOT NULL,
    current_state_backup_path VARCHAR(1000),
    finalize_after TIMESTAMP WITHOUT TIME ZONE,
    error_code VARCHAR(80),
    error_message TEXT,
    actor_user_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(actor_user_id) REFERENCES users (id),
    FOREIGN KEY(target_turn_id) REFERENCES sdd_task_session_turns (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_task_session_operation_task_id UNIQUE (task_id, operation_id)
);

CREATE INDEX ix_sdd_task_session_operations_status ON sdd_task_session_operations (status);

CREATE INDEX ix_sdd_task_session_operations_task_id ON sdd_task_session_operations (task_id);

CREATE INDEX ix_sdd_task_session_operations_workspace_id ON sdd_task_session_operations (workspace_id);

CREATE INDEX ix_task_session_undo_finalization ON sdd_task_session_operations (finalize_after, id);

CREATE TABLE task_evidence_attachments (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    uploader_id VARCHAR(36),
    evidence_id VARCHAR(36),
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(255) NOT NULL,
    size BIGINT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(evidence_id) REFERENCES sdd_evidence (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(uploader_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_task_evidence_attachments_evidence_id ON task_evidence_attachments (evidence_id);

CREATE INDEX ix_task_evidence_attachments_task_id ON task_evidence_attachments (task_id);

CREATE TABLE sdd_clarification_threads (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    clarification_id VARCHAR(36) NOT NULL,
    author_id VARCHAR(36),
    entry_type VARCHAR(40) NOT NULL,
    body TEXT NOT NULL,
    is_answer BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(author_id) REFERENCES users (id),
    FOREIGN KEY(clarification_id) REFERENCES sdd_clarifications (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_clarification_threads_author_id ON sdd_clarification_threads (author_id);

CREATE INDEX ix_sdd_clarification_threads_clarification_id ON sdd_clarification_threads (clarification_id);

CREATE INDEX ix_sdd_clarification_threads_task_id ON sdd_clarification_threads (task_id);

CREATE INDEX ix_sdd_clarification_threads_workspace_id ON sdd_clarification_threads (workspace_id);

CREATE TABLE sdd_delta_regions (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    delta_id VARCHAR(36) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    old_file_path VARCHAR(1000),
    region_type deltaregiontype NOT NULL,
    region_source deltaregionsource NOT NULL,
    ai_line_start INTEGER,
    ai_line_end INTEGER,
    human_line_start INTEGER,
    human_line_end INTEGER,
    ai_insertions INTEGER NOT NULL,
    ai_deletions INTEGER NOT NULL,
    human_insertions INTEGER NOT NULL,
    human_deletions INTEGER NOT NULL,
    summary TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(delta_id) REFERENCES sdd_human_deltas (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_delta_regions_delta_id ON sdd_delta_regions (delta_id);

CREATE INDEX ix_sdd_delta_regions_workspace_id ON sdd_delta_regions (workspace_id);

CREATE TABLE sdd_review_clarification_links (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    review_id VARCHAR(36) NOT NULL,
    clarification_id VARCHAR(36) NOT NULL,
    link_type VARCHAR(80),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(clarification_id) REFERENCES sdd_clarifications (id) ON DELETE CASCADE,
    FOREIGN KEY(review_id) REFERENCES sdd_human_reviews (id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
    CONSTRAINT uq_sdd_review_clarification_links_review_clarification UNIQUE (review_id, clarification_id)
);

CREATE INDEX ix_sdd_review_clarification_links_clarification_id ON sdd_review_clarification_links (clarification_id);

CREATE INDEX ix_sdd_review_clarification_links_review_id ON sdd_review_clarification_links (review_id);

CREATE INDEX ix_sdd_review_clarification_links_task_id ON sdd_review_clarification_links (task_id);

CREATE INDEX ix_sdd_review_clarification_links_workspace_id ON sdd_review_clarification_links (workspace_id);

CREATE TABLE sdd_decisions (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    requirement_id VARCHAR(36),
    human_delta_id VARCHAR(36),
    delta_region_id VARCHAR(36),
    decided_by_id VARCHAR(36),
    source_evidence_id VARCHAR(36),
    source_chat_message_id VARCHAR(36),
    source_asset_id VARCHAR(36),
    source_asset_version_id VARCHAR(36),
    source_asset_thread_id VARCHAR(36),
    source_resolution_proposal_id VARCHAR(36),
    source_final_summary_id VARCHAR(36),
    status decisionstatus NOT NULL,
    source_type decisionsourcetype NOT NULL,
    title VARCHAR(300) NOT NULL,
    body TEXT,
    rationale TEXT,
    impact_scope VARCHAR(300),
    promote_candidate BOOLEAN NOT NULL,
    source_metadata_json JSON,
    delta_line_refs_json JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(decided_by_id) REFERENCES users (id),
    FOREIGN KEY(delta_region_id) REFERENCES sdd_delta_regions (id) ON DELETE SET NULL,
    FOREIGN KEY(human_delta_id) REFERENCES sdd_human_deltas (id) ON DELETE SET NULL,
    FOREIGN KEY(requirement_id) REFERENCES sdd_requirements (id) ON DELETE SET NULL,
    FOREIGN KEY(source_asset_id) REFERENCES sdd_assets (id) ON DELETE SET NULL,
    FOREIGN KEY(source_asset_thread_id) REFERENCES sdd_asset_threads (id) ON DELETE SET NULL,
    FOREIGN KEY(source_asset_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(source_chat_message_id) REFERENCES chat_messages (id) ON DELETE SET NULL,
    FOREIGN KEY(source_evidence_id) REFERENCES sdd_evidence (id) ON DELETE SET NULL,
    FOREIGN KEY(source_final_summary_id) REFERENCES sdd_task_final_summaries (id) ON DELETE SET NULL,
    FOREIGN KEY(source_resolution_proposal_id) REFERENCES sdd_asset_resolution_proposals (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES sdd_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_decisions_decided_by_id ON sdd_decisions (decided_by_id);

CREATE INDEX ix_sdd_decisions_delta_region_id ON sdd_decisions (delta_region_id);

CREATE INDEX ix_sdd_decisions_human_delta_id ON sdd_decisions (human_delta_id);

CREATE INDEX ix_sdd_decisions_requirement_id ON sdd_decisions (requirement_id);

CREATE INDEX ix_sdd_decisions_source_asset_id ON sdd_decisions (source_asset_id);

CREATE INDEX ix_sdd_decisions_source_asset_thread_id ON sdd_decisions (source_asset_thread_id);

CREATE INDEX ix_sdd_decisions_source_asset_version_id ON sdd_decisions (source_asset_version_id);

CREATE INDEX ix_sdd_decisions_source_chat_message_id ON sdd_decisions (source_chat_message_id);

CREATE INDEX ix_sdd_decisions_source_final_summary_id ON sdd_decisions (source_final_summary_id);

CREATE INDEX ix_sdd_decisions_source_resolution_proposal_id ON sdd_decisions (source_resolution_proposal_id);

CREATE INDEX ix_sdd_decisions_source_type ON sdd_decisions (source_type);

CREATE INDEX ix_sdd_decisions_status ON sdd_decisions (status);

CREATE INDEX ix_sdd_decisions_task_id ON sdd_decisions (task_id);

CREATE INDEX ix_sdd_decisions_workspace_id ON sdd_decisions (workspace_id);

CREATE TABLE sdd_knowledge_assets (
    id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    promoted_by_id VARCHAR(36),
    source_task_id VARCHAR(36),
    source_decision_id VARCHAR(36),
    source_human_delta_id VARCHAR(36),
    source_clarification_id VARCHAR(36),
    source_review_id VARCHAR(36),
    source_evidence_id VARCHAR(36),
    asset_type knowledgeassettype NOT NULL,
    status knowledgeassetstatus NOT NULL,
    title VARCHAR(300) NOT NULL,
    body TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY(promoted_by_id) REFERENCES users (id),
    FOREIGN KEY(source_clarification_id) REFERENCES sdd_clarifications (id) ON DELETE SET NULL,
    FOREIGN KEY(source_decision_id) REFERENCES sdd_decisions (id) ON DELETE SET NULL,
    FOREIGN KEY(source_evidence_id) REFERENCES sdd_evidence (id) ON DELETE SET NULL,
    FOREIGN KEY(source_human_delta_id) REFERENCES sdd_human_deltas (id) ON DELETE SET NULL,
    FOREIGN KEY(source_review_id) REFERENCES sdd_human_reviews (id) ON DELETE SET NULL,
    FOREIGN KEY(source_task_id) REFERENCES sdd_tasks (id) ON DELETE SET NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);

CREATE INDEX ix_sdd_knowledge_assets_asset_type ON sdd_knowledge_assets (asset_type);

CREATE INDEX ix_sdd_knowledge_assets_promoted_by_id ON sdd_knowledge_assets (promoted_by_id);

CREATE INDEX ix_sdd_knowledge_assets_source_task_id ON sdd_knowledge_assets (source_task_id);

CREATE INDEX ix_sdd_knowledge_assets_status ON sdd_knowledge_assets (status);

CREATE INDEX ix_sdd_knowledge_assets_workspace_id ON sdd_knowledge_assets (workspace_id);

CREATE TABLE search_pg_documents (
    entity_key VARCHAR(80) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    workspace_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    message_id VARCHAR(36),
    role VARCHAR(16),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    source_version BIGINT NOT NULL,
    projection_hash VARCHAR(64),
    deleted BOOLEAN NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    terms TSVECTOR GENERATED ALWAYS AS (setweight(to_tsvector('public.jiebaqry'::regconfig, title), 'A') || setweight(to_tsvector('public.jiebaqry'::regconfig, content), 'D')) STORED,
    PRIMARY KEY (entity_key)
);

CREATE INDEX ix_search_pg_documents_scope ON search_pg_documents (workspace_id, kind, created_at);

CREATE INDEX ix_search_pg_documents_task ON search_pg_documents (task_id);

CREATE INDEX ix_search_pg_documents_terms ON search_pg_documents USING gin (terms);

CREATE TABLE search_pg_passages (
    entity_key VARCHAR(80) NOT NULL,
    profile_id VARCHAR(36) NOT NULL,
    chunk_no INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    embedding VECTOR(1024) NOT NULL,
    PRIMARY KEY (entity_key, profile_id, chunk_no),
    FOREIGN KEY(entity_key) REFERENCES search_pg_documents (entity_key) ON DELETE CASCADE
);

CREATE INDEX ix_search_pg_passages_embedding ON search_pg_passages USING hnsw (embedding vector_cosine_ops);

CREATE INDEX ix_search_pg_passages_profile ON search_pg_passages (profile_id);

ALTER TABLE chat_messages ADD CONSTRAINT fk_chat_message_session_turn FOREIGN KEY(session_turn_id) REFERENCES sdd_task_session_turns (id) ON DELETE SET NULL;

ALTER TABLE sdd_api_mock_projects ADD CONSTRAINT fk_mock_active_source_version FOREIGN KEY(active_source_version_id) REFERENCES sdd_api_mock_source_versions (id) ON DELETE SET NULL;

ALTER TABLE sdd_assets ADD CONSTRAINT fk_asset_active_version FOREIGN KEY(active_version_id) REFERENCES sdd_asset_versions (id) ON DELETE SET NULL;

ALTER TABLE sdd_ai_jobs ADD CONSTRAINT fk_ai_job_session_turn FOREIGN KEY(session_turn_id) REFERENCES sdd_task_session_turns (id) ON DELETE SET NULL;
