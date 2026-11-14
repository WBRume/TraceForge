ALTER TABLE sdd_ai_jobs DROP CONSTRAINT fk_ai_job_session_turn;

ALTER TABLE sdd_assets DROP CONSTRAINT fk_asset_active_version;

ALTER TABLE sdd_api_mock_projects DROP CONSTRAINT fk_mock_active_source_version;

ALTER TABLE chat_messages DROP CONSTRAINT fk_chat_message_session_turn;

DROP INDEX ix_search_pg_passages_profile;

DROP INDEX ix_search_pg_passages_embedding;

DROP TABLE search_pg_passages;

DROP INDEX ix_search_pg_documents_terms;

DROP INDEX ix_search_pg_documents_task;

DROP INDEX ix_search_pg_documents_scope;

DROP TABLE search_pg_documents;

DROP INDEX ix_sdd_knowledge_assets_workspace_id;

DROP INDEX ix_sdd_knowledge_assets_status;

DROP INDEX ix_sdd_knowledge_assets_source_task_id;

DROP INDEX ix_sdd_knowledge_assets_promoted_by_id;

DROP INDEX ix_sdd_knowledge_assets_asset_type;

DROP TABLE sdd_knowledge_assets;

DROP INDEX ix_sdd_decisions_workspace_id;

DROP INDEX ix_sdd_decisions_task_id;

DROP INDEX ix_sdd_decisions_status;

DROP INDEX ix_sdd_decisions_source_type;

DROP INDEX ix_sdd_decisions_source_resolution_proposal_id;

DROP INDEX ix_sdd_decisions_source_final_summary_id;

DROP INDEX ix_sdd_decisions_source_chat_message_id;

DROP INDEX ix_sdd_decisions_source_asset_version_id;

DROP INDEX ix_sdd_decisions_source_asset_thread_id;

DROP INDEX ix_sdd_decisions_source_asset_id;

DROP INDEX ix_sdd_decisions_requirement_id;

DROP INDEX ix_sdd_decisions_human_delta_id;

DROP INDEX ix_sdd_decisions_delta_region_id;

DROP INDEX ix_sdd_decisions_decided_by_id;

DROP TABLE sdd_decisions;

DROP INDEX ix_sdd_review_clarification_links_workspace_id;

DROP INDEX ix_sdd_review_clarification_links_task_id;

DROP INDEX ix_sdd_review_clarification_links_review_id;

DROP INDEX ix_sdd_review_clarification_links_clarification_id;

DROP TABLE sdd_review_clarification_links;

DROP INDEX ix_sdd_delta_regions_workspace_id;

DROP INDEX ix_sdd_delta_regions_delta_id;

DROP TABLE sdd_delta_regions;

DROP INDEX ix_sdd_clarification_threads_workspace_id;

DROP INDEX ix_sdd_clarification_threads_task_id;

DROP INDEX ix_sdd_clarification_threads_clarification_id;

DROP INDEX ix_sdd_clarification_threads_author_id;

DROP TABLE sdd_clarification_threads;

DROP INDEX ix_task_evidence_attachments_task_id;

DROP INDEX ix_task_evidence_attachments_evidence_id;

DROP TABLE task_evidence_attachments;

DROP INDEX ix_task_session_undo_finalization;

DROP INDEX ix_sdd_task_session_operations_workspace_id;

DROP INDEX ix_sdd_task_session_operations_task_id;

DROP INDEX ix_sdd_task_session_operations_status;

DROP TABLE sdd_task_session_operations;

DROP INDEX ix_sdd_human_deltas_workspace_id;

DROP INDEX ix_sdd_human_deltas_task_id;

DROP INDEX ix_sdd_human_deltas_status;

DROP INDEX ix_sdd_human_deltas_proposal_id;

DROP INDEX ix_sdd_human_deltas_final_evidence_id;

DROP INDEX ix_sdd_human_deltas_diff_asset_id;

DROP INDEX ix_sdd_human_deltas_created_by_id;

DROP TABLE sdd_human_deltas;

DROP INDEX ix_sdd_execution_logs_workspace_id;

DROP INDEX ix_sdd_execution_logs_task_replay_order;

DROP INDEX ix_sdd_execution_logs_task_id;

DROP INDEX ix_sdd_execution_logs_session_turn_id;

DROP TABLE sdd_execution_logs;

DROP INDEX ix_sdd_context_token_segments_workspace_id;

DROP INDEX ix_sdd_context_token_segments_tool_use_id;

DROP INDEX ix_sdd_context_token_segments_task_job;

DROP INDEX ix_sdd_context_token_segments_task_id;

DROP INDEX ix_sdd_context_token_segments_source_ref_id;

DROP INDEX ix_sdd_context_token_segments_source_kind;

DROP INDEX ix_sdd_context_token_segments_snapshot_id;

DROP INDEX ix_sdd_context_token_segments_snapshot_category_created;

DROP INDEX ix_sdd_context_token_segments_snapshot_category;

DROP INDEX ix_sdd_context_token_segments_skill_runtime_event_id;

DROP INDEX ix_sdd_context_token_segments_created_at;

DROP INDEX ix_sdd_context_token_segments_content_hash;

DROP INDEX ix_sdd_context_token_segments_chat_message_id;

DROP INDEX ix_sdd_context_token_segments_category;

DROP INDEX ix_sdd_context_token_segments_asset_version_id;

DROP INDEX ix_sdd_context_token_segments_asset_id;

DROP INDEX ix_sdd_context_token_segments_ai_job_id;

DROP TABLE sdd_context_token_segments;

DROP INDEX ix_sdd_clarifications_workspace_id;

DROP INDEX ix_sdd_clarifications_task_id;

DROP INDEX ix_sdd_clarifications_status;

DROP INDEX ix_sdd_clarifications_source_review_id;

DROP INDEX ix_sdd_clarifications_responder_id;

DROP INDEX ix_sdd_clarifications_requirement_id;

DROP INDEX ix_sdd_clarifications_requester_id;

DROP INDEX ix_sdd_clarifications_converted_requirement_id;

DROP INDEX ix_sdd_clarifications_blocking_level;

DROP TABLE sdd_clarifications;

DROP INDEX ix_sdd_task_session_turns_workspace_id;

DROP INDEX ix_sdd_task_session_turns_task_id;

DROP INDEX ix_sdd_task_session_turns_status;

DROP INDEX ix_sdd_task_session_turns_session_revision;

DROP INDEX ix_sdd_task_session_turns_session_generation;

DROP INDEX ix_sdd_task_session_turns_operation_id;

DROP TABLE sdd_task_session_turns;

DROP INDEX ix_sdd_task_cli_bootstraps_workspace_id;

DROP INDEX ix_sdd_task_cli_bootstraps_task_id;

DROP INDEX ix_sdd_task_cli_bootstraps_status;

DROP INDEX ix_sdd_task_cli_bootstraps_spec_version_id;

DROP INDEX ix_sdd_task_cli_bootstraps_spec_asset_id;

DROP INDEX ix_sdd_task_cli_bootstraps_execution_job_id;

DROP TABLE sdd_task_cli_bootstraps;

DROP INDEX ix_sdd_task_chat_submissions_task_id;

DROP INDEX ix_sdd_task_chat_submissions_status;

DROP INDEX ix_sdd_task_chat_submissions_ai_job_id;

DROP TABLE sdd_task_chat_submissions;

DROP INDEX ix_sdd_task_change_proposal_files_repository_id;

DROP INDEX ix_sdd_task_change_proposal_files_proposal_repo_id;

DROP INDEX ix_sdd_task_change_proposal_files_proposal_id;

DROP TABLE sdd_task_change_proposal_files;

DROP INDEX ix_sdd_skill_runtime_events_workspace_id;

DROP INDEX ix_sdd_skill_runtime_events_tool_use_id;

DROP INDEX ix_sdd_skill_runtime_events_task_id;

DROP INDEX ix_sdd_skill_runtime_events_status;

DROP INDEX ix_sdd_skill_runtime_events_skill_id;

DROP INDEX ix_sdd_skill_runtime_events_materialized_dir;

DROP INDEX ix_sdd_skill_runtime_events_event_type;

DROP INDEX ix_sdd_skill_runtime_events_created_at;

DROP INDEX ix_sdd_skill_runtime_events_ai_job_id;

DROP TABLE sdd_skill_runtime_events;

DROP INDEX ix_job_event_delivery;

DROP TABLE sdd_job_events;

DROP TABLE sdd_job_attempts;

DROP INDEX ix_sdd_evidence_workspace_id;

DROP INDEX ix_sdd_evidence_task_id;

DROP INDEX ix_sdd_evidence_status;

DROP INDEX ix_sdd_evidence_source_type;

DROP INDEX ix_sdd_evidence_requirement_id;

DROP INDEX ix_sdd_evidence_human_review_id;

DROP INDEX ix_sdd_evidence_evidence_type;

DROP INDEX ix_sdd_evidence_created_by_id;

DROP INDEX ix_sdd_evidence_confirmed_by_id;

DROP INDEX ix_sdd_evidence_ai_job_id;

DROP TABLE sdd_evidence;

DROP INDEX ix_sdd_context_token_snapshots_workspace_task;

DROP INDEX ix_sdd_context_token_snapshots_workspace_id;

DROP INDEX ix_sdd_context_token_snapshots_task_id;

DROP INDEX ix_sdd_context_token_snapshots_task_created;

DROP INDEX ix_sdd_context_token_snapshots_status;

DROP INDEX ix_sdd_context_token_snapshots_session_id;

DROP INDEX ix_sdd_context_token_snapshots_ai_job_id;

DROP TABLE sdd_context_token_snapshots;

DROP INDEX ix_sdd_ai_outputs_workspace_id;

DROP INDEX ix_sdd_ai_outputs_task_id;

DROP INDEX ix_sdd_ai_outputs_output_type;

DROP INDEX ix_sdd_ai_outputs_asset_version_id;

DROP INDEX ix_sdd_ai_outputs_asset_id;

DROP INDEX ix_sdd_ai_outputs_ai_job_id;

DROP TABLE sdd_ai_outputs;

DROP INDEX ix_sdd_task_verification_runs_workspace_id;

DROP INDEX ix_sdd_task_verification_runs_user_id;

DROP INDEX ix_sdd_task_verification_runs_task_id;

DROP INDEX ix_sdd_task_verification_runs_status;

DROP INDEX ix_sdd_task_verification_runs_proposal_id;

DROP INDEX ix_sdd_task_verification_runs_log_asset_version_id;

DROP INDEX ix_sdd_task_verification_runs_log_asset_id;

DROP TABLE sdd_task_verification_runs;

DROP INDEX ix_sdd_task_conflict_reports_workspace_id;

DROP INDEX ix_sdd_task_conflict_reports_user_id;

DROP INDEX ix_sdd_task_conflict_reports_task_id;

DROP INDEX ix_sdd_task_conflict_reports_report_asset_version_id;

DROP INDEX ix_sdd_task_conflict_reports_report_asset_id;

DROP INDEX ix_sdd_task_conflict_reports_proposal_id;

DROP TABLE sdd_task_conflict_reports;

DROP INDEX ix_sdd_task_change_proposal_repos_repository_id;

DROP INDEX ix_sdd_task_change_proposal_repos_proposal_id;

DROP INDEX ix_sdd_task_change_proposal_repos_patch_asset_version_id;

DROP INDEX ix_sdd_task_change_proposal_repos_patch_asset_id;

DROP TABLE sdd_task_change_proposal_repos;

DROP INDEX ix_sdd_asset_thread_messages_thread_id;

DROP INDEX ix_sdd_asset_thread_messages_creator_id;

DROP TABLE sdd_asset_thread_messages;

DROP INDEX ix_sdd_asset_thread_anchor_mappings_version_id;

DROP INDEX ix_sdd_asset_thread_anchor_mappings_thread_id;

DROP INDEX ix_sdd_asset_thread_anchor_mappings_created_by;

DROP TABLE sdd_asset_thread_anchor_mappings;

DROP INDEX ix_sdd_asset_resolution_proposals_thread_id;

DROP INDEX ix_sdd_asset_resolution_proposals_creator_id;

DROP INDEX ix_sdd_asset_resolution_proposals_base_version_id;

DROP TABLE sdd_asset_resolution_proposals;

DROP INDEX ix_sdd_api_mock_rules_updated_by;

DROP INDEX ix_sdd_api_mock_rules_project_id;

DROP INDEX ix_sdd_api_mock_rules_endpoint_id;

DROP TABLE sdd_api_mock_rules;

DROP INDEX ix_sdd_api_mock_entities_source_version_id;

DROP INDEX ix_sdd_api_mock_entities_project_id;

DROP INDEX ix_sdd_api_mock_entities_endpoint_id;

DROP TABLE sdd_api_mock_entities;

DROP INDEX ix_sdd_api_mock_collab_events_user_id;

DROP INDEX ix_sdd_api_mock_collab_events_project_id;

DROP INDEX ix_sdd_api_mock_collab_events_endpoint_id;

DROP TABLE sdd_api_mock_collab_events;

DROP INDEX ix_sdd_ai_jobs_workspace_id;

DROP INDEX ix_sdd_ai_jobs_worker_active;

DROP INDEX ix_sdd_ai_jobs_thread_id;

DROP INDEX ix_sdd_ai_jobs_task_id;

DROP INDEX ix_sdd_ai_jobs_status;

DROP INDEX ix_sdd_ai_jobs_session_turn_id;

DROP INDEX ix_sdd_ai_jobs_session_revision;

DROP INDEX ix_sdd_ai_jobs_session_generation;

DROP INDEX ix_sdd_ai_jobs_retry_of_job_id;

DROP INDEX ix_sdd_ai_jobs_reclaim;

DROP INDEX ix_sdd_ai_jobs_queue_source;

DROP INDEX ix_sdd_ai_jobs_queue_key;

DROP INDEX ix_sdd_ai_jobs_queue_claim;

DROP INDEX ix_sdd_ai_jobs_next_reap_at;

DROP INDEX ix_sdd_ai_jobs_listing;

DROP INDEX ix_sdd_ai_jobs_creator_id;

DROP INDEX ix_sdd_ai_jobs_asset_id;

DROP TABLE sdd_ai_jobs;

DROP INDEX ix_pre_input_mentions_user;

DROP TABLE sdd_task_pre_input_mentions;

DROP INDEX ix_sdd_task_pre_input_contributions_pre_input_id;

DROP TABLE sdd_task_pre_input_contributions;

DROP INDEX ix_sdd_task_change_proposals_workspace_id;

DROP INDEX ix_sdd_task_change_proposals_task_id;

DROP INDEX ix_sdd_task_change_proposals_status;

DROP INDEX ix_sdd_task_change_proposals_patch_asset_version_id;

DROP INDEX ix_sdd_task_change_proposals_patch_asset_id;

DROP TABLE sdd_task_change_proposals;

DROP INDEX ix_sdd_task_baselines_workspace_id;

DROP INDEX ix_sdd_task_baselines_task_id;

DROP INDEX ix_sdd_task_baselines_summary_id;

DROP INDEX ix_sdd_task_baselines_baselined_by_id;

DROP TABLE sdd_task_baselines;

DROP INDEX ix_sdd_asset_threads_workspace_id;

DROP INDEX ix_sdd_asset_threads_version_id;

DROP INDEX ix_sdd_asset_threads_task_id;

DROP INDEX ix_sdd_asset_threads_resolved_version_id;

DROP INDEX ix_sdd_asset_threads_resolved_by;

DROP INDEX ix_sdd_asset_threads_creator_id;

DROP INDEX ix_sdd_asset_threads_close_hint_version_id;

DROP INDEX ix_sdd_asset_threads_block_id;

DROP INDEX ix_sdd_asset_threads_asset_id;

DROP TABLE sdd_asset_threads;

DROP INDEX ix_sdd_api_mock_endpoints_source_version_id;

DROP INDEX ix_sdd_api_mock_endpoints_project_id;

DROP TABLE sdd_api_mock_endpoints;

DROP TABLE task_playbook_bindings;

DROP INDEX ix_task_collaboration_snapshots_task_id;

DROP INDEX ix_collaboration_snapshot_lookup;

DROP TABLE task_collaboration_snapshots;

DROP INDEX ix_sdd_test_results_workspace_id;

DROP INDEX ix_sdd_test_results_task_id;

DROP TABLE sdd_test_results;

DROP INDEX ix_sdd_task_requirements_workspace_id;

DROP INDEX ix_sdd_task_requirements_task_id;

DROP INDEX ix_sdd_task_requirements_requirement_id;

DROP INDEX ix_sdd_task_requirements_relation_type;

DROP INDEX ix_sdd_task_requirements_created_by_id;

DROP TABLE sdd_task_requirements;

DROP INDEX ix_sdd_task_pre_inputs_workspace_id;

DROP INDEX ix_sdd_task_pre_inputs_task_id;

DROP INDEX ix_sdd_task_pre_inputs_status;

DROP INDEX ix_sdd_task_pre_inputs_deadline_at;

DROP TABLE sdd_task_pre_inputs;

DROP INDEX ix_sdd_task_final_summaries_workspace_id;

DROP INDEX ix_sdd_task_final_summaries_verified_by_id;

DROP INDEX ix_sdd_task_final_summaries_task_id;

DROP INDEX ix_sdd_task_final_summaries_final_status;

DROP INDEX ix_sdd_task_final_summaries_author_id;

DROP TABLE sdd_task_final_summaries;

DROP INDEX ix_sdd_skill_review_comments_workspace_id;

DROP INDEX ix_sdd_skill_review_comments_version_id;

DROP INDEX ix_sdd_skill_review_comments_skill_id;

DROP INDEX ix_sdd_skill_review_comments_file_path;

DROP INDEX ix_sdd_skill_review_comments_expert_user_id;

DROP TABLE sdd_skill_review_comments;

DROP INDEX ix_sdd_skill_expert_ratings_workspace_id;

DROP INDEX ix_sdd_skill_expert_ratings_version_id;

DROP INDEX ix_sdd_skill_expert_ratings_skill_id;

DROP INDEX ix_sdd_skill_expert_ratings_expert_user_id;

DROP TABLE sdd_skill_expert_ratings;

DROP INDEX ix_sdd_skill_analyses_workspace_id;

DROP INDEX ix_sdd_skill_analyses_version_id;

DROP INDEX ix_sdd_skill_analyses_skill_id;

DROP INDEX ix_sdd_skill_analyses_created_by_id;

DROP INDEX ix_sdd_skill_analyses_commit_sha;

DROP TABLE sdd_skill_analyses;

DROP INDEX ix_sdd_requirement_import_items_workspace_id;

DROP INDEX ix_sdd_requirement_import_items_status;

DROP INDEX ix_sdd_requirement_import_items_requirement_id;

DROP INDEX ix_sdd_requirement_import_items_batch_id;

DROP TABLE sdd_requirement_import_items;

DROP INDEX ix_sdd_requirement_audit_logs_workspace_id;

DROP INDEX ix_sdd_requirement_audit_logs_task_id;

DROP INDEX ix_sdd_requirement_audit_logs_requirement_id;

DROP INDEX ix_sdd_requirement_audit_logs_import_batch_id;

DROP INDEX ix_sdd_requirement_audit_logs_actor_id;

DROP INDEX ix_sdd_requirement_audit_logs_action;

DROP TABLE sdd_requirement_audit_logs;

DROP INDEX ix_sdd_human_review_comments_workspace_id;

DROP INDEX ix_sdd_human_review_comments_task_id;

DROP INDEX ix_sdd_human_review_comments_review_id;

DROP INDEX ix_sdd_human_review_comments_author_id;

DROP TABLE sdd_human_review_comments;

DROP INDEX ix_sdd_diagnosis_results_workspace_id;

DROP INDEX ix_sdd_diagnosis_results_task_id;

DROP INDEX ix_sdd_diagnosis_results_source_chat_message_id;

DROP TABLE sdd_diagnosis_results;

DROP INDEX ix_sdd_case_review_records_workspace_id;

DROP INDEX ix_sdd_case_review_records_reviewer_id;

DROP INDEX ix_sdd_case_review_records_case_id;

DROP TABLE sdd_case_review_records;

DROP INDEX ix_sdd_asset_versions_created_by;

DROP INDEX ix_sdd_asset_versions_base_version_id;

DROP INDEX ix_sdd_asset_versions_asset_id;

DROP TABLE sdd_asset_versions;

DROP INDEX ix_sdd_api_mock_source_versions_project_id;

DROP INDEX ix_sdd_api_mock_source_versions_creator_id;

DROP TABLE sdd_api_mock_source_versions;

DROP INDEX ix_sdd_api_mock_jobs_project_id;

DROP INDEX ix_sdd_api_mock_jobs_creator_id;

DROP TABLE sdd_api_mock_jobs;

DROP INDEX ix_case_playbook_links_case_id;

DROP TABLE case_playbook_links;

DROP INDEX ix_task_webhook_delivery_pending;

DROP TABLE task_webhook_deliveries;

DROP INDEX ix_task_reading_states_workspace_id;

DROP INDEX ix_task_reading_states_workspace;

DROP TABLE task_reading_states;

DROP INDEX ix_task_reading_receipts_seen;

DROP TABLE task_reading_receipts;

DROP INDEX ix_task_reading_items_workspace_id;

DROP INDEX ix_task_reading_items_turn;

DROP INDEX ix_task_reading_items_message;

DROP INDEX ix_task_reading_items_member;

DROP INDEX ix_task_reading_items_active;

DROP TABLE task_reading_items;

DROP TABLE task_collaboration_states;

DROP INDEX ix_task_collaboration_operations_task_id;

DROP TABLE task_collaboration_operations;

DROP TABLE task_collaboration_manifests;

DROP INDEX ix_task_collaboration_handoffs_task_id;

DROP INDEX ix_collaboration_handoff_history;

DROP TABLE task_collaboration_handoffs;

DROP INDEX ix_sdd_task_skills_task_id;

DROP INDEX ix_sdd_task_skills_skill_id;

DROP TABLE sdd_task_skills;

DROP INDEX ix_sdd_task_repositories_task_id;

DROP INDEX ix_sdd_task_repositories_state;

DROP INDEX ix_sdd_task_repositories_repository_id;

DROP TABLE sdd_task_repositories;

DROP INDEX ix_sdd_task_process_audit_logs_workspace_id;

DROP INDEX ix_sdd_task_process_audit_logs_task_id;

DROP INDEX ix_sdd_task_process_audit_logs_record_type;

DROP INDEX ix_sdd_task_process_audit_logs_record_id;

DROP INDEX ix_sdd_task_process_audit_logs_actor_id;

DROP INDEX ix_sdd_task_process_audit_logs_action;

DROP TABLE sdd_task_process_audit_logs;

DROP INDEX ix_sdd_task_followers_workspace_id;

DROP INDEX ix_sdd_task_followers_user_id;

DROP INDEX ix_sdd_task_followers_task_id;

DROP TABLE sdd_task_followers;

DROP INDEX ix_sdd_task_execution_bindings_resource_id;

DROP TABLE sdd_task_execution_bindings;

DROP INDEX ix_sdd_skill_versions_skill_id;

DROP INDEX ix_sdd_skill_versions_creator_id;

DROP TABLE sdd_skill_versions;

DROP INDEX ix_sdd_requirements_workspace_id;

DROP INDEX ix_sdd_requirements_status;

DROP INDEX ix_sdd_requirements_parent_requirement_id;

DROP INDEX ix_sdd_requirements_import_batch_id;

DROP INDEX ix_sdd_requirements_created_by_id;

DROP TABLE sdd_requirements;

DROP INDEX ix_sdd_provision_jobs_workspace_id;

DROP INDEX ix_sdd_provision_jobs_task_id;

DROP INDEX ix_sdd_provision_jobs_job_type;

DROP INDEX ix_sdd_provision_jobs_creator_id;

DROP TABLE sdd_provision_jobs;

DROP INDEX ix_sdd_plan_nodes_workspace_id;

DROP INDEX ix_sdd_plan_nodes_task_id;

DROP TABLE sdd_plan_nodes;

DROP INDEX ix_sdd_human_reviews_workspace_id;

DROP INDEX ix_sdd_human_reviews_task_id;

DROP INDEX ix_sdd_human_reviews_status;

DROP INDEX ix_sdd_human_reviews_reviewer_id;

DROP INDEX ix_sdd_human_reviews_outcome;

DROP TABLE sdd_human_reviews;

DROP INDEX ix_sdd_dashboard_metrics_workspace_id;

DROP INDEX ix_sdd_dashboard_metrics_task_id;

DROP TABLE sdd_dashboard_metrics;

DROP INDEX ix_sdd_cases_workspace_id;

DROP INDEX ix_sdd_cases_status;

DROP INDEX ix_sdd_cases_source_task_id;

DROP INDEX ix_sdd_cases_priority;

DROP INDEX ix_sdd_cases_creator_id;

DROP INDEX ix_sdd_cases_category;

DROP TABLE sdd_cases;

DROP INDEX ix_sdd_assets_workspace_id;

DROP INDEX ix_sdd_assets_task_id;

DROP INDEX ix_sdd_assets_active_version_id;

DROP TABLE sdd_assets;

DROP INDEX ix_sdd_api_mock_projects_workspace_id;

DROP INDEX ix_sdd_api_mock_projects_task_id;

DROP INDEX ix_sdd_api_mock_projects_creator_id;

DROP INDEX ix_sdd_api_mock_projects_active_source_version_id;

DROP TABLE sdd_api_mock_projects;

DROP INDEX ix_playbook_runs_workspace_id;

DROP INDEX ix_playbook_runs_task_id;

DROP TABLE playbook_runs;

DROP INDEX ix_chat_messages_workspace_id;

DROP INDEX ix_chat_messages_task_id;

DROP INDEX ix_chat_messages_session_turn_id;

DROP INDEX ix_chat_messages_session_generation;

DROP INDEX ix_chat_message_context;

DROP TABLE chat_messages;

DROP INDEX ix_workspace_repositories_workspace_id;

DROP INDEX ix_workspace_repositories_state;

DROP INDEX ix_workspace_repositories_repository_id;

DROP TABLE workspace_repositories;

DROP INDEX ix_workspace_members_workspace_id;

DROP INDEX ix_workspace_members_user_id;

DROP TABLE workspace_members;

DROP INDEX ix_workspace_invite_links_workspace_id;

DROP INDEX ix_workspace_invite_links_token;

DROP TABLE workspace_invite_links;

DROP TABLE task_webhook_endpoints;

DROP INDEX ix_sdd_user_notifications_workspace_id;

DROP INDEX ix_sdd_user_notifications_type;

DROP INDEX ix_sdd_user_notifications_recipient_user_id;

DROP INDEX ix_sdd_user_notifications_read_at;

DROP INDEX ix_notifications_recipient_unread;

DROP INDEX ix_notifications_recipient_created;

DROP TABLE sdd_user_notifications;

DROP INDEX ix_sdd_tasks_workspace_id;

DROP INDEX ix_sdd_tasks_workspace_created;

DROP INDEX ix_sdd_tasks_task_type;

DROP INDEX ix_sdd_tasks_session_revision;

DROP INDEX ix_sdd_tasks_session_generation;

DROP INDEX ix_sdd_tasks_creator_id;

DROP INDEX ix_sdd_tasks_baselined_by_id;

DROP TABLE sdd_tasks;

DROP INDEX ix_sdd_skills_workspace_id;

DROP INDEX ix_sdd_skills_last_modifier_id;

DROP INDEX ix_sdd_skills_creator_id;

DROP TABLE sdd_skills;

DROP INDEX ix_sdd_requirement_import_batches_workspace_id;

DROP INDEX ix_sdd_requirement_import_batches_status;

DROP INDEX ix_sdd_requirement_import_batches_created_by_id;

DROP TABLE sdd_requirement_import_batches;

DROP INDEX ix_sdd_local_resources_workspace_id;

DROP INDEX ix_sdd_local_resources_owner_user_id;

DROP TABLE sdd_local_resources;

DROP TABLE playbook_specs;

DROP INDEX ix_mgmt_project_release_repos_repository_id;

DROP INDEX ix_mgmt_project_release_repos_release_id;

DROP TABLE mgmt_project_release_repos;

DROP INDEX ix_mgmt_project_products_project_id;

DROP INDEX ix_mgmt_project_products_product_version_id;

DROP INDEX ix_mgmt_project_products_product_id;

DROP INDEX ix_mgmt_project_products_delivery_status;

DROP TABLE mgmt_project_products;

DROP INDEX ix_mgmt_product_version_repos_repository_id;

DROP INDEX ix_mgmt_product_version_repos_product_version_id;

DROP TABLE mgmt_product_version_repos;

DROP INDEX ix_mgmt_product_version_baseline_exclusions_repository_id;

DROP INDEX ix_mgmt_product_version_baseline_exclusions_product_version_id;

DROP TABLE mgmt_product_version_baseline_exclusions;

DROP INDEX ix_workspaces_project_id;

DROP TABLE workspaces;

DROP INDEX ix_mgmt_project_releases_status;

DROP INDEX ix_mgmt_project_releases_project_id;

DROP INDEX ix_mgmt_project_releases_product_id;

DROP TABLE mgmt_project_releases;

DROP INDEX ix_mgmt_product_versions_status;

DROP INDEX ix_mgmt_product_versions_product_id;

DROP INDEX ix_mgmt_product_versions_baseline_product_version_id;

DROP TABLE mgmt_product_versions;

DROP INDEX ix_mgmt_product_repos_repository_id;

DROP INDEX ix_mgmt_product_repos_product_id;

DROP TABLE mgmt_product_repos;

DROP INDEX ix_oauth_identities_user_id;

DROP TABLE oauth_identities;

DROP INDEX ix_mgmt_repositories_repo_type;

DROP INDEX ix_mgmt_repositories_group_id;

DROP INDEX ix_mgmt_repositories_git_url;

DROP TABLE mgmt_repositories;

DROP INDEX ix_mgmt_projects_lifecycle_status;

DROP INDEX ix_mgmt_projects_code;

DROP TABLE mgmt_projects;

DROP INDEX ix_mgmt_products_status;

DROP INDEX ix_mgmt_products_product_type;

DROP INDEX ix_mgmt_products_code;

DROP INDEX ix_mgmt_products_baseline_product_id;

DROP TABLE mgmt_products;

DROP INDEX ix_users_email;

DROP TABLE users;

DROP INDEX ix_task_status_events_task_id;

DROP TABLE task_status_events;

DROP INDEX ix_task_event_outbox_task_id;

DROP INDEX ix_task_event_outbox_pending;

DROP INDEX ix_task_event_outbox_lease;

DROP TABLE task_event_outbox;

DROP INDEX ix_task_awareness_events_creator_id;

DROP INDEX ix_task_awareness_event_pending;

DROP TABLE task_awareness_events;

DROP TABLE system_configs;

DROP INDEX ix_search_outbox_pending;

DROP INDEX ix_search_outbox_lease;

DROP TABLE search_outbox;

DROP TABLE search_index_targets;

DROP TABLE search_embedding_profiles;

DROP INDEX ix_search_embedding_pending;

DROP INDEX ix_search_embedding_lease;

DROP TABLE search_embedding_jobs;

DROP INDEX ix_search_state_workspace;

DROP INDEX ix_search_state_task;

DROP TABLE search_document_states;

DROP TABLE search_backfill_runs;

DROP INDEX ix_task_share_suggestions_recipient_task_status;

DROP INDEX ix_sdd_task_share_suggestions_task_id;

DROP INDEX ix_sdd_task_share_suggestions_status;

DROP INDEX ix_sdd_task_share_suggestions_share_id;

DROP INDEX ix_sdd_task_share_suggestions_recipient_user_id;

DROP TABLE sdd_task_share_suggestions;

DROP INDEX ix_sdd_task_share_accesses_share_id;

DROP INDEX ix_sdd_task_share_accesses_expires_at;

DROP INDEX ix_sdd_task_share_accesses_access_token_hash;

DROP TABLE sdd_task_share_accesses;

DROP INDEX ix_task_session_shares_task_creator_created;

DROP INDEX ix_task_session_shares_expires;

DROP INDEX ix_sdd_task_session_shares_workspace_id;

DROP INDEX ix_sdd_task_session_shares_token_hash;

DROP INDEX ix_sdd_task_session_shares_token;

DROP INDEX ix_sdd_task_session_shares_task_id;

DROP INDEX ix_sdd_task_session_shares_creator_id;

DROP TABLE sdd_task_session_shares;

DROP INDEX ix_sdd_task_deletion_cleanup_retry_at;

DROP TABLE sdd_task_deletion_cleanup;

DROP INDEX ix_sdd_rag_sync_queue_workspace_id;

DROP INDEX ix_sdd_rag_sync_queue_status;

DROP INDEX ix_sdd_rag_sync_queue_name;

DROP TABLE sdd_rag_sync_queue;

DROP INDEX ix_sdd_rag_outbox_workspace_id;

DROP INDEX ix_sdd_rag_outbox_status;

DROP INDEX ix_sdd_rag_outbox_queue_id;

DROP INDEX ix_sdd_rag_outbox_next_retry_at;

DROP INDEX ix_sdd_rag_outbox_locked_until;

DROP INDEX ix_sdd_rag_outbox_doc_key;

DROP INDEX ix_sdd_rag_outbox_case_id;

DROP TABLE sdd_rag_outbox;

DROP INDEX ix_sdd_local_resource_operations_task_id;

DROP TABLE sdd_local_resource_operations;

DROP INDEX ix_oauth_tickets_provider_uid;

DROP INDEX ix_oauth_tickets_normalized_email;

DROP INDEX ix_oauth_tickets_expires_at;

DROP TABLE oauth_tickets;

DROP INDEX ix_oauth_states_expires_at;

DROP TABLE oauth_states;

DROP INDEX ix_mgmt_repo_groups_parent_id;

DROP TABLE mgmt_repo_groups;

DROP TABLE feature_configs;

DROP TYPE aijobchannel;

DROP TYPE aijobstatus;

DROP TYPE aioutputtype;

DROP TYPE apimockcollabeventtype;

DROP TYPE apimockrulemode;

DROP TYPE assetresolutionproposalstatus;

DROP TYPE assetthreadmessagerole;

DROP TYPE assetthreadstatus;

DROP TYPE assettype;

DROP TYPE changeproposalfiletype;

DROP TYPE changeproposalstatus;

DROP TYPE clarificationblockinglevel;

DROP TYPE clarificationstatus;

DROP TYPE contexttokencategory;

DROP TYPE decisionsourcetype;

DROP TYPE decisionstatus;

DROP TYPE deltaregionsource;

DROP TYPE deltaregiontype;

DROP TYPE evidencesourcetype;

DROP TYPE evidencestatus;

DROP TYPE evidencetype;

DROP TYPE humandeltastatus;

DROP TYPE humanreviewoutcome;

DROP TYPE humanreviewstatus;

DROP TYPE knowledgeassetstatus;

DROP TYPE knowledgeassettype;

DROP TYPE logtype;

DROP TYPE messagerole;

DROP TYPE messagetype;

DROP TYPE phase;

DROP TYPE plannodestatus;

DROP TYPE preinputeditpermission;

DROP TYPE preinputstatus;

DROP TYPE productstatus;

DROP TYPE producttype;

DROP TYPE productversionstatus;

DROP TYPE projectlifecyclestatus;

DROP TYPE provisionjobtype;

DROP TYPE releaserepokind;

DROP TYPE releasestatus;

DROP TYPE reporeftype;

DROP TYPE repositorytype;

DROP TYPE requirementauditaction;

DROP TYPE requirementimportbatchstatus;

DROP TYPE requirementimportitemstatus;

DROP TYPE requirementstatus;

DROP TYPE skillanalysisrefkind;

DROP TYPE skilldimension;

DROP TYPE skillrisklevel;

DROP TYPE skillruntimeeventstatus;

DROP TYPE skillruntimeeventtype;

DROP TYPE skillruntimeevidencelevel;

DROP TYPE taskclibootstrapstatus;

DROP TYPE taskfinalstatus;

DROP TYPE taskprocessauditaction;

DROP TYPE taskprocessrecordtype;

DROP TYPE taskrepositorystate;

DROP TYPE taskrequirementrelationtype;

DROP TYPE tasksessionoperationstatus;

DROP TYPE tasksessionsharemode;

DROP TYPE tasksessionturnstatus;

DROP TYPE tasksharesuggestionstatus;

DROP TYPE taskstatus;

DROP TYPE teststatus;

DROP TYPE testtype;

DROP TYPE verificationrunstatus;

DROP TYPE workspacerepositorystate;

DROP TYPE workspacerole;
