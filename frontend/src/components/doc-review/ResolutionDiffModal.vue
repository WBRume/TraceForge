<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { Loader2 } from "lucide-vue-next";
import DecisionInlineFields from "./DecisionInlineFields.vue";

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
  block_id?: string;
  rewrite_scope?: string;
  rewrite_status?: string;
  proposal_text?: string;
  new_text?: string;
  display_new_text?: string;
  merged_block_ast?: any;
  merged_blocks_ast?: any[];
  source_message_ids?: string[];
  change_stats?: Record<string, any>;
};

type Proposal = {
  id: string;
  status: "draft" | "applied" | "discarded";
  proposed_patch_json?: ProposalPatch;
};

type RevisionMeta = {
  change_id: string;
  op: "insert" | "delete";
  status: string;
};

type RevisionRun = {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strike?: boolean;
  superscript?: boolean;
  subscript?: boolean;
  color?: string;
  highlight?: string;
  font_size?: number;
  font_name?: string;
  revision?: RevisionMeta;
};

type ChangeItem = {
  change_id: string;
  op: "insert" | "delete";
  text: string;
  block_id: string;
};

type ResolutionDecisionDraft = {
  enabled: boolean;
  title: string;
  body: string;
  impact_scope: string;
  promote_candidate: boolean;
};

const props = defineProps<{
  visible: boolean;
  proposal: Proposal | null;
  proposalJob?: ThreadAiJob | null;
  canApply?: boolean;
  canRewrite?: boolean;
  rewriteDisabledReason?: string | null;
  applying?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  apply: [
    proposalId: string,
    payload: { finalBlockAst?: any; finalBlocksAst?: any[] },
    decision?: {
      title: string;
      body?: string | null;
      impact_scope?: string | null;
      promote_candidate?: boolean;
    } | null,
  ];
  regenerate: [
    proposalId: string,
    proposalText: string,
    rewriteScope: "anchor" | "document",
  ];
}>();

const { t } = useI18n();

const localBlocks = ref<any[]>([]);
const activeChangeId = ref("");
const isEditingDocument = ref(false);
const editingDocumentDraft = ref("");
const decisionDraft = ref<ResolutionDecisionDraft>({
  enabled: false,
  title: "",
  body: "",
  impact_scope: "",
  promote_candidate: false,
});
const decisionTitleInvalid = ref(false);

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

const normalizeRuns = (raw: unknown, fallbackText = ""): RevisionRun[] => {
  if (Array.isArray(raw)) {
    const out: RevisionRun[] = [];
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const text = String((item as any).text || "");
      if (!text) continue;
      const run: RevisionRun = { ...(item as any), text };
      if (run.revision && typeof run.revision === "object") {
        run.revision = {
          change_id: String(run.revision.change_id || "").trim(),
          op: run.revision.op === "delete" ? "delete" : "insert",
          status: String(run.revision.status || "pending"),
        };
      }
      out.push(run);
    }
    if (out.length) return out;
  }
  const text = String(fallbackText || "");
  if (!text) return [];
  return [{ text }];
};

const normalizeBlock = (raw: any, index: number) => {
  const block = clone(raw || {});
  if (!block.id) block.id = `blk-${index + 1}`;
  if (!block.type) block.type = "paragraph";
  block.runs = normalizeRuns(block.runs, String(block.text || ""));
  block.text = block.runs.map((run: RevisionRun) => run.text).join("");
  return block;
};

const loadBlocksFromProposal = (proposal: Proposal | null) => {
  if (!proposal) {
    localBlocks.value = [];
    activeChangeId.value = "";
    return;
  }
  const patch = proposal.proposed_patch_json || {};
  const mergedBlocks = Array.isArray(patch.merged_blocks_ast)
    ? patch.merged_blocks_ast
    : [];
  const mergedSingle =
    patch.merged_block_ast && typeof patch.merged_block_ast === "object"
      ? [patch.merged_block_ast]
      : [];
  const finalBlocks = Array.isArray((patch as any).final_blocks_ast)
    ? (patch as any).final_blocks_ast
    : [];
  const finalSingle =
    (patch as any).final_block_ast && typeof (patch as any).final_block_ast === "object"
      ? [(patch as any).final_block_ast]
      : [];
  const newBlocks = Array.isArray((patch as any).new_blocks_ast)
    ? (patch as any).new_blocks_ast
    : [];
  const newSingle =
    (patch as any).new_block_ast && typeof (patch as any).new_block_ast === "object"
      ? [(patch as any).new_block_ast]
      : [];
  const source: any[] =
    mergedBlocks.length
      ? mergedBlocks
      : mergedSingle.length
        ? mergedSingle
        : finalBlocks.length
          ? finalBlocks
          : finalSingle.length
            ? finalSingle
            : newBlocks.length
              ? newBlocks
              : newSingle;
  localBlocks.value = source.map((item: any, index: number) => normalizeBlock(item, index));
  activeChangeId.value = "";
};

const resetDecisionDraft = (proposal: Proposal | null) => {
  const rawText = String(
    proposal?.proposed_patch_json?.proposal_text ||
      proposal?.proposed_patch_json?.new_text ||
      proposal?.proposed_patch_json?.display_new_text ||
      "",
  ).trim();
  const title = rawText.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || "";
  decisionDraft.value = {
    enabled: false,
    title: title.slice(0, 80),
    body: rawText,
    impact_scope: "",
    promote_candidate: false,
  };
  decisionTitleInvalid.value = false;
};

watch(
  () => props.proposal,
  (proposal) => {
    loadBlocksFromProposal(proposal);
    resetDecisionDraft(proposal);
    isEditingDocument.value = false;
    editingDocumentDraft.value = "";
  },
  { immediate: true, deep: true },
);

watch(
  () => props.visible,
  (visible) => {
    if (!visible) {
      activeChangeId.value = "";
      isEditingDocument.value = false;
      editingDocumentDraft.value = "";
      decisionTitleInvalid.value = false;
    }
  },
);

const rewriteStatus = computed(() =>
  String(props.proposal?.proposed_patch_json?.rewrite_status || "")
    .trim()
    .toLowerCase(),
);
const isRewriteReady = computed(() => rewriteStatus.value === "ready");
const rewriteScope = computed(() =>
  String(props.proposal?.proposed_patch_json?.rewrite_scope || "anchor")
    .trim()
    .toLowerCase(),
);
const isJobBusy = computed(() => {
  const status = props.proposalJob?.status;
  return status === "PENDING" || status === "RUNNING" || status === "WAITING_HITL";
});

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

const proposalProgress = computed(() => {
  const value = Number(props.proposalJob?.progress || 0);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
});

const isRevisionWaiting = computed(() => {
  const status = props.proposalJob?.status;
  if (status === "FAILED" || status === "CANCELLED") {
    return false;
  }
  if (isJobBusy.value) {
    return true;
  }
  return !!props.proposal && props.proposal.status === "draft" && !isRewriteReady.value;
});
const hasRenderableRevision = computed(() => localBlocks.value.length > 0);
const revisionReady = computed(
  () => hasRenderableRevision.value && !isRevisionWaiting.value && isRewriteReady.value,
);
const revisionEmptyTitle = computed(() => {
  if (isRevisionWaiting.value) return proposalJobStatusText.value;
  if (rewriteStatus.value === "ready" || props.proposalJob?.status === "SUCCESS") {
    return t("doc_review.revision_ready_no_structured_title");
  }
  return t("doc_review.revision_unavailable_title");
});
const revisionEmptyHint = computed(() => {
  if (isRevisionWaiting.value) return t("doc_review.revision_waiting_hint");
  if (rewriteStatus.value === "ready" || props.proposalJob?.status === "SUCCESS") {
    return t("doc_review.revision_ready_no_structured_hint");
  }
  return t("doc_review.revision_unavailable_hint");
});

const pendingChanges = computed<ChangeItem[]>(() => {
  const map = new Map<string, ChangeItem>();
  for (const block of localBlocks.value) {
    const blockId = String(block?.id || "");
    const runs = normalizeRuns(block?.runs, String(block?.text || ""));
    for (const run of runs) {
      const revision = run.revision;
      if (!revision || revision.status !== "pending" || !revision.change_id) continue;
      const existing = map.get(revision.change_id);
      if (existing) {
        existing.text += run.text;
        continue;
      }
      map.set(revision.change_id, {
        change_id: revision.change_id,
        op: revision.op,
        text: run.text,
        block_id: blockId,
      });
    }
  }
  return Array.from(map.values());
});

const hasPendingChanges = computed(() => pendingChanges.value.length > 0);
const pendingCountText = computed(() =>
  t("doc_review.revision_pending_count", { count: pendingChanges.value.length }),
);
const hasEmptyContentForApply = computed(() => {
  if (!localBlocks.value.length) return true;
  if (rewriteScope.value === "document" || localBlocks.value.length > 1) {
    return localBlocks.value.some((raw: any, index: number) => {
      const block = normalizeBlock(raw, index);
      return !String(block.text || "").trim();
    });
  }
  const block = normalizeBlock(localBlocks.value[0], 0);
  return !String(block.text || "").trim();
});
const applyDisabledReason = computed(() => {
  if (isEditingDocument.value) return t("doc_review.revision_apply_while_editing");
  if (hasPendingChanges.value) return "";
  if (hasEmptyContentForApply.value) return t("doc_review.revision_apply_empty_block");
  return "";
});
const canApplyNow = computed(
  () =>
    !!props.canApply &&
    !!props.proposal &&
    props.proposal.status === "draft" &&
    !isEditingDocument.value &&
    !isRevisionWaiting.value &&
    !hasPendingChanges.value &&
    !hasEmptyContentForApply.value &&
    localBlocks.value.length > 0 &&
    !props.applying,
);
const revisionPrimaryText = computed(() => {
  if (props.applying) return t("doc_review.proposal_modal_applying");
  if (isRevisionWaiting.value) return `${proposalJobStatusText.value}...`;
  return t("doc_review.revision_apply");
});
const proposalRewriteText = computed(() => {
  const patch = props.proposal?.proposed_patch_json;
  if (!patch) return "";
  return String(
    patch.proposal_text || patch.new_text || patch.display_new_text || "",
  ).trim();
});
const canRegenerateNow = computed(
  () =>
    props.canRewrite !== false &&
    !!props.proposal &&
    props.proposal.status === "draft" &&
    !!proposalRewriteText.value &&
    !isJobBusy.value &&
    !props.applying,
);
const regenerateActionText = computed(() => {
  if (isJobBusy.value) return `${proposalJobStatusText.value}...`;
  return t("doc_review.revision_regenerate");
});

const proposalMetaText = computed(() => {
  const patch = props.proposal?.proposed_patch_json;
  if (!patch) return "";
  const sourceCount = Array.isArray(patch.source_message_ids)
    ? patch.source_message_ids.length
    : 0;
  const stats = patch.change_stats || {};
  const inserted = Number(stats.inserted_segments || 0);
  const deleted = Number(stats.deleted_segments || 0);
  return t("doc_review.revision_meta", {
    source: sourceCount,
    insert: inserted,
    delete: deleted,
  });
});

const syncLocalText = () => {
  if (!localBlocks.value.length) return;
  localBlocks.value = localBlocks.value.map((raw: any, index: number) =>
    normalizeBlock(raw, index),
  );
};

const applyDecision = (changeId: string, decision: "accept" | "reject") => {
  if (!localBlocks.value.length || !changeId) return;
  localBlocks.value = localBlocks.value.map((raw: any, index: number) => {
    const block = normalizeBlock(raw, index);
    const nextRuns: RevisionRun[] = [];
    for (const run of block.runs as RevisionRun[]) {
      const revision = run.revision;
      if (!revision || revision.change_id !== changeId || revision.status !== "pending") {
        nextRuns.push(run);
        continue;
      }
      if (revision.op === "delete") {
        if (decision === "accept") continue;
        const keep = { ...run };
        delete keep.revision;
        nextRuns.push(keep);
        continue;
      }
      if (revision.op === "insert") {
        if (decision === "accept") {
          const keep = { ...run };
          delete keep.revision;
          nextRuns.push(keep);
        }
        continue;
      }
      nextRuns.push(run);
    }
    block.runs = nextRuns;
    block.text = nextRuns.map((run) => run.text).join("");
    return block;
  });
  syncLocalText();
  if (activeChangeId.value === changeId) {
    activeChangeId.value = "";
  }
};

const acceptAll = () => {
  for (const id of pendingChanges.value.map((item) => item.change_id)) {
    applyDecision(id, "accept");
  }
};

const rejectAll = () => {
  for (const id of pendingChanges.value.map((item) => item.change_id)) {
    applyDecision(id, "reject");
  }
};

const runStyle = (run: RevisionRun) => {
  const style: Record<string, string> = {};
  if (run.color) style.color = run.color;
  if (run.highlight) style.backgroundColor = run.highlight;
  if (typeof run.font_size === "number" && Number.isFinite(run.font_size)) {
    style.fontSize = `${Math.min(72, Math.max(8, run.font_size))}px`;
  }
  if (run.font_name) style.fontFamily = run.font_name;
  return style;
};

const runClass = (run: RevisionRun) => {
  const revision = run.revision;
  return {
    bold: !!run.bold,
    italic: !!run.italic,
    underline: !!run.underline,
    strike: !!run.strike,
    superscript: !!run.superscript,
    subscript: !!run.subscript,
    "revision-delete": revision?.op === "delete",
    "revision-insert": revision?.op === "insert",
    "is-active-change":
      !!revision?.change_id && activeChangeId.value === revision.change_id,
  };
};

const setActiveChange = (changeId: string) => {
  activeChangeId.value = changeId;
};

const blockPlainText = (raw: any, index: number) => {
  const block = normalizeBlock(raw, index);
  const text = String(block.text || "").trim();
  if (!text) return "";
  if ((block.type || "paragraph") === "list_item") {
    const marker = String(block.meta?.marker || "•").trim() || "•";
    return `${marker} ${text}`;
  }
  return text;
};

const composeDocumentText = () =>
  localBlocks.value
    .map((raw: any, index: number) => blockPlainText(raw, index))
    .filter((line: string) => !!line.trim())
    .join("\n\n");

const startEditDocument = () => {
  syncLocalText();
  isEditingDocument.value = true;
  editingDocumentDraft.value = composeDocumentText();
};

const cancelEditDocument = () => {
  isEditingDocument.value = false;
  editingDocumentDraft.value = "";
};

const saveEditDocument = () => {
  const normalized = editingDocumentDraft.value.replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    localBlocks.value = [];
    isEditingDocument.value = false;
    editingDocumentDraft.value = "";
    activeChangeId.value = "";
    return;
  }

  const existing = localBlocks.value.map((raw: any, index: number) =>
    normalizeBlock(raw, index),
  );

  if (rewriteScope.value !== "document" && existing.length <= 1) {
    const fallback = existing[0] || { id: "blk-1", type: "paragraph", meta: {} };
    const nextBlock = normalizeBlock(
      {
        ...fallback,
        id: String(fallback.id || "blk-1"),
        type: fallback.type || "paragraph",
        runs: [{ text: normalized }],
      },
      0,
    );
    localBlocks.value = [nextBlock];
    isEditingDocument.value = false;
    editingDocumentDraft.value = "";
    activeChangeId.value = "";
    return;
  }

  const paragraphs = normalized
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter((item) => !!item);

  const rebuilt = paragraphs.map((paragraph, index) => {
    const fallback = existing[index] || {};
    return normalizeBlock(
      {
        ...fallback,
        id: String(fallback.id || `blk-${index + 1}`),
        type: fallback.type || "paragraph",
        runs: [{ text: paragraph }],
      },
      index,
    );
  });

  localBlocks.value = rebuilt;
  isEditingDocument.value = false;
  editingDocumentDraft.value = "";
  activeChangeId.value = "";
};

const doApply = () => {
  if (!props.proposal || !localBlocks.value.length) return;
  let decision:
    | {
        title: string;
        body?: string | null;
        impact_scope?: string | null;
        promote_candidate?: boolean;
      }
    | null = null;
  if (decisionDraft.value.enabled) {
    const title = decisionDraft.value.title.trim();
    decisionTitleInvalid.value = !title;
    if (!title) return;
    decision = {
      title,
      body: decisionDraft.value.body.trim() || null,
      impact_scope: decisionDraft.value.impact_scope.trim() || null,
      promote_candidate: decisionDraft.value.promote_candidate,
    };
  }
  syncLocalText();
  if (rewriteScope.value === "document" || localBlocks.value.length > 1) {
    emit("apply", props.proposal.id, { finalBlocksAst: clone(localBlocks.value) }, decision);
    return;
  }
  emit("apply", props.proposal.id, { finalBlockAst: clone(localBlocks.value[0]) }, decision);
};

const doRegenerate = () => {
  if (!props.proposal) return;
  localBlocks.value = [];
  activeChangeId.value = "";
  isEditingDocument.value = false;
  editingDocumentDraft.value = "";
  const normalizedScope =
    String(props.proposal.proposed_patch_json?.rewrite_scope || "anchor")
      .trim()
      .toLowerCase() === "document"
      ? "document"
      : "anchor";
  const text = proposalRewriteText.value;
  if (!text) return;
  emit("regenerate", props.proposal.id, text, normalizedScope);
};
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card glass-panel">
      <header class="modal-head">
        <div class="title-wrap">
          <h3>{{ t("doc_review.revision_modal_title") }}</h3>
          <p>{{ t("doc_review.revision_modal_subtitle") }}</p>
        </div>
        <button class="close-btn" @click="emit('close')">×</button>
      </header>

      <template v-if="proposal">
        <p v-if="proposalMetaText" class="proposal-meta">{{ proposalMetaText }}</p>
        <div class="workspace-grid">
          <section class="document-pane">
            <div v-if="isRevisionWaiting" class="revision-waiting">
              <Loader2 class="waiting-spinner" />
              <strong>{{ proposalJobStatusText }}</strong>
              <div class="progress-wrap">
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: `${proposalProgress}%` }"></div>
                </div>
                <span class="progress-text">{{ proposalProgress }}%</span>
              </div>
              <p class="hint">{{ t("doc_review.revision_waiting_hint") }}</p>
            </div>
            <template v-else-if="revisionReady">
              <div class="document-edit-toolbar">
                <template v-if="!isEditingDocument">
                  <button class="btn-secondary small-btn" @click="startEditDocument">
                    {{ t("doc_review.revision_edit_document") }}
                  </button>
                </template>
                <template v-else>
                  <button class="btn-secondary small-btn" @click="cancelEditDocument">
                    {{ t("doc_review.revision_edit_document_cancel") }}
                  </button>
                  <button class="btn-primary small-btn" @click="saveEditDocument">
                    {{ t("doc_review.revision_edit_document_save") }}
                  </button>
                </template>
              </div>
              <template v-if="isEditingDocument">
                <div class="block-edit-surface">
                  <textarea
                    v-model="editingDocumentDraft"
                    class="block-editor custom-scrollbar"
                    :placeholder="t('doc_review.revision_edit_document_placeholder')"
                  />
                </div>
                <p class="block-editor-hint">
                  {{ t("doc_review.revision_edit_document_hint") }}
                </p>
              </template>
              <template v-else>
                <article
                  v-for="(block, blockIndex) in localBlocks"
                  :key="`block-${block.id || blockIndex}`"
                  class="doc-block"
                >
                  <header class="doc-block-header">
                    <p class="doc-block-meta">#{{ block.id || `blk-${blockIndex + 1}` }}</p>
                  </header>
                  <div class="block-render-surface">
                    <template v-if="(block.type || 'paragraph') === 'heading'">
                      <h3 class="doc-heading">
                        <span
                          v-for="(run, idx) in block.runs || []"
                          :key="`run-${block.id || blockIndex}-${idx}`"
                          class="doc-run"
                          :class="runClass(run)"
                          :style="runStyle(run)"
                          @click="run.revision?.change_id && setActiveChange(run.revision.change_id)"
                        >
                          {{ run.text }}
                        </span>
                      </h3>
                    </template>
                    <template v-else-if="(block.type || 'paragraph') === 'list_item'">
                      <p class="doc-list-item">
                        <span class="list-marker">{{ block.meta?.marker || "•" }}</span>
                        <span class="list-content">
                          <span
                            v-for="(run, idx) in block.runs || []"
                            :key="`run-${block.id || blockIndex}-${idx}`"
                            class="doc-run"
                            :class="runClass(run)"
                            :style="runStyle(run)"
                            @click="run.revision?.change_id && setActiveChange(run.revision.change_id)"
                          >
                            {{ run.text }}
                          </span>
                        </span>
                      </p>
                    </template>
                    <template v-else>
                      <p class="doc-paragraph">
                        <span
                          v-for="(run, idx) in block.runs || []"
                          :key="`run-${block.id || blockIndex}-${idx}`"
                          class="doc-run"
                          :class="runClass(run)"
                          :style="runStyle(run)"
                          @click="run.revision?.change_id && setActiveChange(run.revision.change_id)"
                        >
                          {{ run.text }}
                        </span>
                      </p>
                    </template>
                  </div>
                </article>
              </template>
            </template>
            <div v-else class="revision-waiting">
              <strong>{{ revisionEmptyTitle }}</strong>
              <p class="hint">{{ revisionEmptyHint }}</p>
            </div>
          </section>

          <aside class="changes-pane">
            <header class="changes-head">
              <strong>{{ pendingCountText }}</strong>
              <div class="batch-actions">
                <button
                  class="btn-secondary small-btn"
                  :disabled="!hasPendingChanges"
                  @click="acceptAll"
                >
                  {{ t("doc_review.revision_accept_all") }}
                </button>
                <button
                  class="btn-secondary small-btn danger"
                  :disabled="!hasPendingChanges"
                  @click="rejectAll"
                >
                  {{ t("doc_review.revision_reject_all") }}
                </button>
              </div>
            </header>

            <div class="changes-list custom-scrollbar">
              <div v-if="isRevisionWaiting" class="changes-empty">
                <Loader2 class="waiting-spinner mini" />
                {{ t("doc_review.revision_waiting_hint") }}
              </div>
              <div v-else-if="!pendingChanges.length" class="changes-empty">
                {{ t("doc_review.revision_no_pending") }}
              </div>
              <div
                v-for="change in pendingChanges"
                :key="change.change_id"
                class="change-item"
                :class="{
                  active: activeChangeId === change.change_id,
                  insert: change.op === 'insert',
                  delete: change.op === 'delete',
                }"
              >
                <p class="change-block">
                  {{ t("doc_review.revision_block_label", { block: change.block_id }) }}
                </p>
                <p class="change-text" @click="setActiveChange(change.change_id)">
                  {{ change.text }}
                </p>
                <div class="change-actions">
                  <button
                    class="btn-secondary small-btn"
                    @click="applyDecision(change.change_id, 'accept')"
                  >
                    {{ t("doc_review.revision_accept") }}
                  </button>
                  <button
                    class="btn-secondary small-btn danger"
                    @click="applyDecision(change.change_id, 'reject')"
                  >
                    {{ t("doc_review.revision_reject") }}
                  </button>
                </div>
              </div>
            </div>
          </aside>
        </div>

        <DecisionInlineFields
          v-model="decisionDraft"
          :title-invalid="decisionTitleInvalid"
        />

        <footer class="modal-actions">
          <button class="btn-secondary" @click="emit('close')">
            {{ t("doc_review.proposal_modal_close") }}
          </button>
          <button
            class="btn-secondary"
            :disabled="!canRegenerateNow"
            :title="props.canRewrite === false ? (props.rewriteDisabledReason || t('doc_review.ai_unavailable_label')) : ''"
            @click="doRegenerate"
          >
            {{ regenerateActionText }}
          </button>
          <button
            class="btn-primary"
            :disabled="!canApplyNow"
            :title="applyDisabledReason"
            @click="doApply"
          >
            {{ revisionPrimaryText }}
          </button>
        </footer>
      </template>

      <template v-else>
        <div class="empty-stage">
          <strong>{{ isJobBusy ? proposalJobStatusText : t("doc_review.revision_unavailable_title") }}</strong>
          <p v-if="proposalJob?.progress">{{ proposalJob.progress }}%</p>
          <p v-if="proposalJob?.error_message" class="error">
            {{ proposalJob.error_message }}
          </p>
          <p v-else class="hint">
            {{ isJobBusy ? t("doc_review.revision_waiting_hint") : t("doc_review.revision_unavailable_hint") }}
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

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 12px;
  min-height: 0;
}

.document-pane {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(248, 250, 252, 0.74);
  padding: 14px;
  overflow: auto;
  min-height: min(60vh, 620px);
}

.revision-waiting {
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  color: #0f172a;
}

.waiting-spinner {
  width: 24px;
  height: 24px;
  color: #0ea5e9;
  animation: spin 1s linear infinite;
}

.waiting-spinner.mini {
  width: 16px;
  height: 16px;
  margin-right: 6px;
  vertical-align: text-bottom;
}

.progress-wrap {
  width: min(340px, 92%);
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.25);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0ea5e9, #2563eb);
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 12px;
  color: #64748b;
  min-width: 40px;
  text-align: right;
}

.revision-waiting .hint {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.doc-block {
  padding: 8px 0;
}

.doc-block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 4px;
}

.doc-block-meta {
  margin: 0;
  font-size: 11px;
  color: #64748b;
}

.document-edit-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.block-render-surface,
.block-edit-surface {
  width: 100%;
  box-sizing: border-box;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(255, 255, 255, 0.94);
  padding: 10px;
}

.doc-heading,
.doc-paragraph {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.8;
  color: #0f172a;
  font-size: 14px;
}

.doc-heading {
  font-size: 1.18rem;
}

.doc-list-item {
  display: flex;
  align-items: flex-start;
  margin: 0;
  line-height: 1.8;
}

.list-marker {
  width: 1.8em;
  text-align: right;
  padding-right: 0.35em;
  color: #334155;
}

.list-content {
  flex: 1;
  white-space: pre-wrap;
}

.block-editor {
  width: 100%;
  min-height: clamp(280px, 46vh, 620px);
  height: clamp(280px, 46vh, 620px);
  box-sizing: border-box;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(255, 255, 255, 0.94);
  padding: 10px;
  line-height: 1.8;
  font-size: 14px;
  font-family: inherit;
  color: #0f172a;
  resize: vertical;
}

.block-editor:focus {
  outline: none;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}

.block-editor-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: #64748b;
}

.doc-run.bold {
  font-weight: 700;
}

.doc-run.italic {
  font-style: italic;
}

.doc-run.underline {
  text-decoration: underline;
}

.doc-run.strike {
  text-decoration: line-through;
}

.doc-run.superscript {
  vertical-align: super;
  font-size: 0.8em;
}

.doc-run.subscript {
  vertical-align: sub;
  font-size: 0.8em;
}

.doc-run.revision-delete {
  color: #dc2626;
  text-decoration: line-through;
  text-decoration-thickness: 2px;
  background: rgba(220, 38, 38, 0.08);
  border-radius: 4px;
}

.doc-run.revision-insert {
  color: #16a34a;
  text-decoration: underline;
  text-decoration-thickness: 2px;
  background: rgba(22, 163, 74, 0.08);
  border-radius: 4px;
}

.doc-run.is-active-change {
  box-shadow: inset 0 -2px 0 rgba(14, 165, 233, 0.5);
}

.changes-pane {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(255, 255, 255, 0.95);
  display: flex;
  flex-direction: column;
  min-height: min(60vh, 620px);
}

.changes-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.batch-actions {
  display: flex;
  gap: 6px;
}

.changes-list {
  flex: 1;
  overflow: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.changes-empty {
  color: #64748b;
  font-size: 13px;
  padding: 10px 8px;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.change-item {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  padding: 9px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.change-item.insert {
  border-color: rgba(22, 163, 74, 0.28);
  background: rgba(22, 163, 74, 0.06);
}

.change-item.delete {
  border-color: rgba(220, 38, 38, 0.28);
  background: rgba(220, 38, 38, 0.06);
}

.change-item.active {
  box-shadow: 0 0 0 1.5px rgba(14, 165, 233, 0.35);
}

.change-block {
  margin: 0;
  font-size: 11px;
  color: #475569;
}

.change-text {
  margin: 0;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.55;
  color: #0f172a;
}

.change-actions {
  display: flex;
  gap: 6px;
}

.small-btn {
  padding: 6px 10px;
  font-size: 12px;
}

.small-btn.danger {
  border-color: rgba(220, 38, 38, 0.36);
  color: #b91c1c;
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

@media (max-width: 1080px) {
  .workspace-grid {
    grid-template-columns: 1fr;
  }

  .document-pane,
  .changes-pane {
    min-height: 260px;
  }
}
</style>
