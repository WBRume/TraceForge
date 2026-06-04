<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import BaseSelect from "@/components/BaseSelect.vue";

type ThreadAiJob = {
  id: string;
  status:
    | "PENDING"
    | "RUNNING"
    | "WAITING_HITL"
    | "SUCCESS"
    | "FAILED"
    | "CANCELLED";
  progress: number;
  message?: string | null;
  error_message?: string | null;
  context_json?: Record<string, any> | null;
};

type ProposalPatch = {
  proposal_text?: string;
  new_text?: string;
  display_new_text?: string;
  source_message_ids?: string[];
  rewrite_scope?: "anchor" | "document";
};

type Proposal = {
  id: string;
  status: "draft" | "applied" | "discarded";
  proposed_patch_json?: ProposalPatch;
};

const props = defineProps<{
  visible: boolean;
  proposal: Proposal | null;
  proposalJob?: ThreadAiJob | null;
  canRewrite?: boolean;
  rewriteDisabledReason?: string | null;
}>();

const emit = defineEmits<{
  close: [];
  rewrite: [
    proposalId: string,
    proposalText: string,
    rewriteScope: "anchor" | "document",
  ];
}>();

const { t } = useI18n();

const proposalDraft = ref("");
const rewriteScope = ref<"anchor" | "document">("anchor");
const rewriteScopeOptions = computed(() => [
  { label: t("doc_review.proposal_rewrite_scope_anchor"), value: "anchor" },
  { label: t("doc_review.proposal_rewrite_scope_document"), value: "document" },
]);

watch(
  () => props.proposal,
  (proposal) => {
    const patch = proposal?.proposed_patch_json || {};
    proposalDraft.value = String(
      patch.proposal_text || patch.new_text || patch.display_new_text || "",
    );
    const scope = String(patch.rewrite_scope || "anchor").toLowerCase();
    rewriteScope.value = scope === "document" ? "document" : "anchor";
  },
  { immediate: true, deep: true },
);

const proposalJobStatusText = computed(() => {
  const status = props.proposalJob?.status;
  if (status === "PENDING") return t("doc_review.ai_status_pending");
  if (status === "RUNNING") return t("doc_review.ai_status_running");
  if (status === "WAITING_HITL") return t("doc_review.ai_status_waiting_hitl");
  if (status === "FAILED") return t("doc_review.ai_status_failed");
  if (status === "CANCELLED") return t("doc_review.ai_status_cancelled");
  if (status === "SUCCESS") return t("doc_review.ai_status_success");
  return t("doc_review.proposal_waiting");
});

const isProposalJobBusy = computed(() => {
  const status = props.proposalJob?.status;
  return status === "PENDING" || status === "RUNNING" || status === "WAITING_HITL";
});

const canRewriteNow = computed(
  () =>
    props.canRewrite !== false &&
    !!props.proposal &&
    props.proposal.status === "draft" &&
    !!proposalDraft.value.trim() &&
    !isProposalJobBusy.value,
);

const rewriteActionText = computed(() => {
  if (!isProposalJobBusy.value) return t("doc_review.proposal_rewrite_action");
  return `${proposalJobStatusText.value}...`;
});

const proposalMetaText = computed(() => {
  const patch = props.proposal?.proposed_patch_json;
  if (!patch) return "";
  const sourceCount = Array.isArray(patch.source_message_ids)
    ? patch.source_message_ids.length
    : 0;
  return t("doc_review.proposal_editor_meta", { source: sourceCount });
});

const doRewrite = () => {
  if (!props.proposal) return;
  const text = proposalDraft.value.trim();
  if (!text) return;
  emit("rewrite", props.proposal.id, text, rewriteScope.value);
};
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card glass-panel">
      <header class="modal-head">
        <div class="title-wrap">
          <h3>{{ t("doc_review.proposal_modal_title") }}</h3>
          <p>{{ t("doc_review.proposal_modal_subtitle") }}</p>
        </div>
        <button class="close-btn" @click="emit('close')">×</button>
      </header>

      <template v-if="proposal">
        <p v-if="proposalMetaText" class="proposal-meta">{{ proposalMetaText }}</p>
        <section class="proposal-editor-panel">
          <header class="proposal-editor-head">
            <strong>{{ t("doc_review.proposal_editor_title") }}</strong>
            <span v-if="isProposalJobBusy" class="editor-state">
              {{ rewriteActionText }}
            </span>
          </header>
          <div class="rewrite-scope-row">
            <span class="rewrite-scope-label">{{
              t("doc_review.proposal_rewrite_scope_label")
            }}</span>
            <BaseSelect
              v-model="rewriteScope"
              :options="rewriteScopeOptions"
              size="sm"
              :disabled="isProposalJobBusy"
              class="rewrite-scope-select"
            />
          </div>
          <p class="proposal-editor-hint">
            {{ t("doc_review.proposal_editor_hint") }}
          </p>
          <p v-if="props.canRewrite === false" class="proposal-editor-hint warning">
            {{ props.rewriteDisabledReason || t("doc_review.ai_unavailable_label") }}
          </p>
          <textarea
            v-model="proposalDraft"
            class="proposal-editor custom-scrollbar"
            :placeholder="t('doc_review.proposal_editor_placeholder')"
            :disabled="isProposalJobBusy || props.canRewrite === false"
          />
        </section>
        <footer class="modal-actions">
          <button class="btn-secondary" @click="emit('close')">
            {{ t("doc_review.proposal_modal_close") }}
          </button>
          <button class="btn-primary" :disabled="!canRewriteNow" @click="doRewrite">
            {{ rewriteActionText }}
          </button>
        </footer>
      </template>

      <template v-else>
        <div class="empty-stage">
          <strong>{{ proposalJobStatusText }}</strong>
          <p v-if="proposalJob?.progress">{{ proposalJob.progress }}%</p>
          <p v-if="proposalJob?.error_message" class="error">
            {{ proposalJob.error_message }}
          </p>
          <p v-else class="hint">
            {{ t("doc_review.proposal_waiting_hint") }}
          </p>
        </div>
        <footer class="modal-actions">
          <button class="btn-secondary" @click="emit('close')">
            {{ t("doc_review.proposal_modal_close") }}
          </button>
        </footer>
      </template>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(8px);
}

.modal-card {
  width: min(1240px, 100%);
  max-height: min(92vh, 920px);
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding: 1.1rem;
  border-radius: var(--radius-xl);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.8);
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.title-wrap h3 {
  margin: 0;
  font-size: 16px;
}

.title-wrap p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.proposal-meta {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 20px;
  line-height: 1;
}

.proposal-editor-panel {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(248, 250, 252, 0.78);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: min(60vh, 620px);
}

.proposal-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.proposal-editor-head strong {
  font-size: 14px;
  color: #0f172a;
}

.editor-state {
  font-size: 12px;
  color: #0284c7;
}

.proposal-editor-hint {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}

.proposal-editor-hint.warning {
  color: #b45309;
}

.rewrite-scope-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.rewrite-scope-label {
  font-size: 12px;
  color: #334155;
  font-weight: 600;
}

.rewrite-scope-select {
  width: 260px;
  max-width: 100%;
}

.proposal-editor {
  width: 100%;
  flex: 1;
  min-height: 320px;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(255, 255, 255, 0.94);
  padding: 12px;
  line-height: 1.7;
  font-size: 13px;
  resize: vertical;
}

.proposal-editor:focus {
  outline: none;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.empty-stage {
  min-height: 260px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(248, 250, 252, 0.74);
}

.empty-stage .hint {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.empty-stage .error {
  margin: 0;
  color: #b91c1c;
  font-size: 13px;
}
</style>
