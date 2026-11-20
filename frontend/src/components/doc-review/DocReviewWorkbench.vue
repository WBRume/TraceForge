<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, shallowRef, useSlots, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { ChevronDown, FileText, Clock } from '@/components/icons';
import api from "@/utils/api";
import { formatApiError } from "@/utils/error";
import { useAssetDiscussion, type AssetSummary } from "@/composables/useAssetDiscussion";
import DocumentCanvas from "./DocumentCanvas.vue";
import InlineSelectionPopover from "./InlineSelectionPopover.vue";
import PdfCanvas from "./PdfCanvas.vue";
import ProposalDraftModal from "./ProposalDraftModal.vue";
import ReviewAnnotationPopover from "./ReviewAnnotationPopover.vue";
import ResolutionDiffModal from "./ResolutionDiffModal.vue";
import TextReviewCanvas from "./TextReviewCanvas.vue";
import ThreadSidebar from "./ThreadSidebar.vue";
import SpecBaselineStatus from "./SpecBaselineStatus.vue";
import VersionSwitcher from "./VersionSwitcher.vue";
import { useDocumentDraft } from "./useDocumentDraft";
import { useResolutionReview } from "./useResolutionReview";
import type { ReviewAnnotationTarget } from "./reviewAnnotationRanges";
import ConfirmActionModal from "@/components/ConfirmActionModal.vue";
import type { TaskSpecBootstrapProgress } from "@/composables/chat/types";

const showAssetMenu = ref(false);
const { t } = useI18n();
const slots = useSlots();

const props = defineProps<{
  wsId: string;
  taskId?: string;
  compact?: boolean;
  initialAssetId?: string;
  readonly?: boolean;
  revisionJobId?: string;
  /** Spec 基线状态由宿主注入：会话内复用 vm.specBootstrap（WS 推送），独立页接 useTaskSpecBootstrapFeed */
  bootstrapStatus?: TaskSpecBootstrapProgress | null;
}>();

const emit = defineEmits<{ revisionJobOpened: [jobId: string] }>();

const loadingAssets = ref(false);
const loadAssetsError = ref("");
const assets = ref<AssetSummary[]>([]);
const selectedAssetId = ref("");
const selectedVersionId = ref("");
const annotationTarget = shallowRef<ReviewAnnotationTarget | null>(null);
const selectionPayload = ref<{
  block_id: string;
  selected_text: string;
  char_start?: number;
  char_end?: number;
  anchor: { top: number; left: number };
} | null>(null);

const bootstrapTriggering = ref(false);
const showBootstrapConfirm = ref(false);

const confirmBootstrapBuild = async () => {
  if (bootstrapTriggering.value) return;
  showBootstrapConfirm.value = false;
  await triggerBootstrap();
};
const ASSET_PAGE_SIZE = 100;

const discussion = useAssetDiscussion({
  wsId: computed(() => props.wsId),
  assetId: selectedAssetId,
});
const {
  documentData,
  versions,
  threads,
  selectedThreadId,
  markersByBlock,
  activeVersionId,
  capabilities,
  loadingVersions,
  onlineUsers,
  wsConnected,
  assistantJobMap,
  cancelAiJob,
  updateThreadCloseHint,
} = discussion;

const selectedAsset = computed(
  () => assets.value.find((item) => item.id === selectedAssetId.value) || null,
);
const draftUrl = computed(() => selectedAssetId.value
  ? `/workspaces/${encodeURIComponent(props.wsId)}/assets/${encodeURIComponent(selectedAssetId.value)}/draft`
  : "");
const draftEditor = useDocumentDraft({
  url: draftUrl, document: documentData, activeVersionId,
  onPublished: (version) => discussion.refresh(version.id),
});
const {
  draft, editing, busy: draftBusy, editingBlockId, source: draftText, stale: draftStale,
  dirty: draftDirty, canPublish, confirm: draftConfirm,
} = draftEditor;
const formalText = computed(() => documentData.value?.source_text ?? null);
const isMarkdown = computed(() =>
  [".md", ".markdown"].includes(String(documentData.value?.active_version?.original_ext || "").toLowerCase()),
);
const DocxReviewCanvas = defineAsyncComponent(() => import("./DocxReviewCanvas.vue"));
const docxSource = computed(() => {
  const version = documentData.value?.active_version;
  const ext = version?.original_ext || selectedAsset.value?.source_ext;
  if (ext?.toLowerCase() !== ".docx") return null;
  return {
    wsId: props.wsId, assetId: selectedAssetId.value, name: selectedAsset.value?.name || "",
    versionId: editing.value ? draft.value?.base_version_id : version?.id,
    draftRevision: editing.value ? draft.value?.revision : undefined,
  };
});
const visibleBlocks = computed(() => (editing.value && draft.value?.blocks) || documentData.value?.blocks || []);
const isPdfAsset = computed(() => {
  const versionExt = String(documentData.value?.active_version?.original_ext || "").toLowerCase();
  const assetExt = String(selectedAsset.value?.source_ext || "").toLowerCase();
  return versionExt === ".pdf" || assetExt === ".pdf";
});
const noAssetHint = computed(() => {
  if (loadingAssets.value) return t("doc_review.assets_loading");
  if (loadAssetsError.value) return loadAssetsError.value;
  if (!selectedAssetId.value) return t("doc_review.no_doc_for_current_task");
  return "";
});
const readOnlyMode = computed(() => Boolean(props.readonly));
const effectiveCapabilities = computed(() => {
  const base = capabilities.value;
  if (!readOnlyMode.value && !editing.value) {
    return base;
  }
  return {
    ...base,
    can_comment: false,
    can_ai_reply: false,
    can_apply_resolution: false,
    can_manual_edit: false,
  };
});
const aiUnavailableReason = computed(
  () => String(effectiveCapabilities.value.ai_unavailable_reason || "").trim() || "",
);
const aiAvailableNow = computed(
  () => effectiveCapabilities.value.can_ai_reply && effectiveCapabilities.value.ai_available,
);
const aiUnavailableReasonText = computed(() => {
  if (!aiUnavailableReason.value) return t("doc_review.ai_unavailable_label");
  return t(`doc_review.${aiUnavailableReason.value}`);
});
const draftStatusText = computed(() => {
  if (draftStale.value) return t("doc_review.draft_stale_short");
  if (draftDirty.value || editingBlockId.value) return t("doc_review.draft_unsaved");
  return t(draft.value?.revision ? "doc_review.draft_saved" : "doc_review.draft_mode");
});
const bootstrapStatusCode = computed(() =>
  String(props.bootstrapStatus?.status || "").toUpperCase(),
);
const canTriggerBootstrap = computed(
  () =>
    !readOnlyMode.value &&
    ["PENDING", "FAILED", "STALE"].includes(bootstrapStatusCode.value),
);

const triggerBootstrap = async () => {
  if (!props.wsId || !props.taskId || bootstrapTriggering.value) return;
  bootstrapTriggering.value = true;
  try {
    await api.post(`/workspaces/${props.wsId}/tasks/${props.taskId}/spec-bootstrap/run`);
    ElMessage.success(t("chat.spec_bootstrap_build_started"));
  } catch (error: unknown) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 409) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      ElMessage.info(
        typeof detail === "string" && detail ? detail : t("chat.spec_bootstrap_build_started"),
      );
    } else {
      ElMessage.error(formatApiError(error, t("chat.spec_bootstrap_build_failed"), t));
    }
  } finally {
    bootstrapTriggering.value = false;
  }
};
const revisions = useResolutionReview({
  workspaceId: computed(() => props.wsId),
  assetId: selectedAssetId,
  versionId: computed(() => selectedVersionId.value || activeVersionId.value),
  canGenerate: aiAvailableNow,
  canApply: computed(() => effectiveCapabilities.value.can_apply_resolution),
  unavailableReason: aiUnavailableReasonText,
  requestedJobId: () => discussion.initialized.value && !loadingAssets.value && selectedAsset.value?.task_id === props.taskId
    && documentData.value?.asset.id === selectedAssetId.value && selectedVersionId.value === activeVersionId.value
    ? props.revisionJobId : undefined,
  onJobOpened: (jobId) => emit("revisionJobOpened", jobId),
  discussion,
});
const {
  showPicker, legacyProposal, comparison, dialogJob: revisionJob, pendingJobs: pendingRevisions,
  overwriteRequest, relocation: pendingRelocation, submitting: requestingComparison,
  applying: applyingRevision, cancelling: cancellingRevision, resultError: revisionResultError,
  blockedReason: revisionBlockedReason,
} = revisions;
const isRelocationPending = computed(() => !!pendingRelocation.value);
const relocationHintText = computed(() =>
  t("doc_review.anchor_relocation_pick_hint"),
);
const hasHeaderPrefixSlot = computed(() => Boolean(slots["header-prefix"]));
const pdfVersionId = computed(() => selectedVersionId.value || activeVersionId.value || null);
const inlineReviewEnabled = computed(
  () =>
    effectiveCapabilities.value.inline_review_enabled &&
    effectiveCapabilities.value.can_comment,
);
const historicalVersionReadonly = computed(
  () =>
    !readOnlyMode.value &&
    !effectiveCapabilities.value.can_comment &&
    String(effectiveCapabilities.value.ai_unavailable_reason || "") === "historical_version_readonly",
);
const canOpenDraft = computed(() => !readOnlyMode.value && !!documentData.value?.active_version
  && capabilities.value.can_manual_edit && (!!docxSource.value || formalText.value !== null));

const startBlockEdit = (blockId: string) => {
  if (!editing.value || !canOpenDraft.value || draftBusy.value || editingBlockId.value) return;
  editingBlockId.value = blockId;
};

watch(editing, () => {
  selectionPayload.value = null;
  pendingRelocation.value = null;
  showAssetMenu.value = false;
});

const versionNumbers = computed(() => Object.fromEntries(versions.value.map(item => [item.id, item.version_no])));
const proposalSourceOptions = computed(() => threads.value.filter(thread => thread.status === "resolved").map(thread => {
  const number = versionNumbers.value[thread.version_id];
  const messages = thread.messages || [];
  return {
    id: thread.id,
    quote: thread.selected_text || thread.block_id,
    version: number ? t("doc_review.annotation_original_version", { version: number }) : "",
    blockId: thread.block_id === "source-text" ? "" : thread.block_id,
    creator: thread.creator_display_name || "",
    messageCount: messages.length,
    charStart: thread.char_start ?? null,
    charEnd: thread.char_end ?? null,
    anchorStatus: thread.anchor_status || "valid",
    messages: messages.map(message => ({
      id: message.id,
      role: message.role,
      content: message.content,
      creator: message.creator_display_name || "",
      createdAt: message.created_at,
    })),
  };
}));

const fetchAssets = async (params: Record<string, any>) => {
  const res = await api.get(`/workspaces/${props.wsId}/assets`, { params });
  return (res.data?.items || []) as AssetSummary[];
};

const fetchTaskSpecAsset = async (taskId: string) => {
  const res = await api.get(
    `/workspaces/${props.wsId}/tasks/${taskId}/spec-asset`,
  );
  return res.data as AssetSummary;
};

const fetchAssetById = async (assetId: string) => {
  const res = await api.get(`/workspaces/${props.wsId}/assets/${assetId}`);
  return res.data as AssetSummary;
};

let assetLoadGeneration = 0;
const loadAssets = async () => {
  if (!props.wsId) return;
  const generation = ++assetLoadGeneration;
  const current = () => generation === assetLoadGeneration;
  loadingAssets.value = true;
  loadAssetsError.value = "";
  try {
    let scopedAssets: AssetSummary[] = [];
    if (props.taskId) {
      try {
        const taskSpecAsset = await fetchTaskSpecAsset(props.taskId);
        if (taskSpecAsset?.id) {
          scopedAssets = [taskSpecAsset];
        }
      } catch {
        scopedAssets = [];
      }
    } else {
      scopedAssets = await fetchAssets({
        page_size: ASSET_PAGE_SIZE,
        asset_type: "SPEC",
      });
    }

    // When task-scoped lookup misses, only fallback to explicit initial asset id.
    if (scopedAssets.length === 0 && !props.taskId) {
      scopedAssets = await fetchAssets({
        page_size: ASSET_PAGE_SIZE,
        asset_type: "SPEC",
      });
    }

    // Fallback: if we have an initial asset id from upload response, fetch directly.
    if (scopedAssets.length === 0 && props.initialAssetId) {
      try {
        const direct = await fetchAssetById(props.initialAssetId);
        if (direct?.id) scopedAssets = [direct];
      } catch {
        // Ignore direct lookup failure and keep empty state.
      }
    }

    if (!current()) return;
    assets.value = scopedAssets;

    const preferredId = props.initialAssetId || selectedAssetId.value;
    if (preferredId && assets.value.some((item) => item.id === preferredId)) {
      selectedAssetId.value = preferredId;
      return;
    }

    const firstSpec = assets.value.find((item) => item.asset_type === "SPEC");
    selectedAssetId.value = firstSpec?.id || assets.value[0]?.id || "";
  } catch (err: any) {
    if (!current()) return;
    loadAssetsError.value = err?.response?.data?.detail || t("doc_review.assets_load_failed");
    assets.value = [];
    selectedAssetId.value = "";
  } finally {
    if (current()) loadingAssets.value = false;
  }
};

const selectAsset = (assetId: string) => {
  selectedAssetId.value = assetId;
  selectionPayload.value = null;
  selectedThreadId.value = "";
  showAssetMenu.value = false;
};

const handleSelectRange = async (payload: {
  block_id: string;
  selected_text: string;
  char_start?: number;
  char_end?: number;
  anchor: { top: number; left: number };
}) => {
  if (pendingRelocation.value) {
    await revisions.relocate(payload);
    return;
  }
  if (!effectiveCapabilities.value.can_comment) return;
  selectionPayload.value = payload;
};

const createThreadFromSelection = async (payload: {
  block_id: string;
  selected_text: string;
  char_start?: number;
  char_end?: number;
  body: string;
}) => {
  if (!effectiveCapabilities.value.can_comment) return;
  const thread = await discussion.createThread({
    ...payload,
    version_id: selectedVersionId.value || undefined,
  });
  if (thread) {
    selectedThreadId.value = thread.id;
  }
  selectionPayload.value = null;
};

const openThread = (threadId: string) => {
  selectedThreadId.value = threadId;
  selectionPayload.value = null;
  annotationTarget.value = null;
};

const openAnchoredThreads = (target: ReviewAnnotationTarget) => {
  if (target.threadIds.length === 1 && !target.trigger) {
    openThread(target.threadIds[0]!);
    return;
  }
  selectionPayload.value = null;
  annotationTarget.value = target.trigger && target.trigger === annotationTarget.value?.trigger ? null : target;
};

const sendThreadMessage = async (threadId: string, content: string) => {
  if (!effectiveCapabilities.value.can_comment) return;
  await discussion.sendThreadMessage(threadId, content);
};

const askThreadAi = async (threadId: string, prompt?: string) => {
  if (!aiAvailableNow.value) {
    ElMessage.warning(aiUnavailableReasonText.value);
    return;
  }
  try {
    await discussion.askAi(threadId, prompt);
  } catch (error: unknown) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 409) {
      ElMessage.warning(t("doc_review.ai_job_bootstrap_not_ready"));
      return;
    }
    ElMessage.error(formatApiError(error, t("doc_review.ai_job_submit_failed"), t));
  }
};

const cancelThreadAiJob = async (jobId: string) => {
  if (!jobId) return;
  try {
    await cancelAiJob(jobId);
    ElMessage.success(t("doc_review.ai_cancelled_manual"));
  } catch (error: unknown) {
    ElMessage.error(formatApiError(error, t("doc_review.ai_cancel_failed"), t));
  }
};

const updateThreadState = async (
  threadId: string,
  status: "open" | "resolved" | "closed",
) => {
  if (!effectiveCapabilities.value.can_apply_resolution) return;
  await discussion.updateThreadState(threadId, status);
};

const handleThreadCloseHintAction = async (
  threadId: string,
  action: "mark_no_close_needed" | "reset_pending",
) => {
  await updateThreadCloseHint(
    threadId,
    action,
    selectedVersionId.value || activeVersionId.value || undefined,
  );
};

const changeVersion = async (versionId: string) => {
  selectedVersionId.value = versionId;
  annotationTarget.value = null;
  const document = await discussion.loadDocument(versionId);
  if (!document || selectedVersionId.value !== versionId) return;
  await discussion.loadThreads(versionId);
  if (selectedVersionId.value !== versionId) return;
  selectedThreadId.value = "";
  pendingRelocation.value = null;
};

const showOriginal = async (versionId: string, threadId: string) => {
  if (editing.value) return;
  await changeVersion(versionId);
  if (selectedVersionId.value === versionId) openThread(threadId);
};

watch([selectedAssetId, activeVersionId, editing], () => { annotationTarget.value = null; });

watch(
  () => activeVersionId.value,
  (versionId) => {
    if (!versionId) return;
    if (!selectedVersionId.value || selectedVersionId.value !== versionId) {
      selectedVersionId.value = versionId;
    }
  },
  { immediate: true },
);

watch(
  () => [props.wsId, props.taskId, props.initialAssetId] as const,
  () => {
    revisions.reset();
    void loadAssets();
  },
);

watch(
  () => bootstrapStatusCode.value,
  (status, previousStatus) => {
    if (!props.taskId || !selectedAssetId.value) return;
    if (status !== "READY" || previousStatus === "READY") return;
    void discussion.refresh(selectedVersionId.value || activeVersionId.value || undefined)
      .catch((error) => ElMessage.error(formatApiError(error, t("doc_review.document_load_failed"), t)));
  },
);

onMounted(() => {
  void loadAssets();
});
</script>

<template>
  <div class="doc-review-workbench compact">
    <header class="workbench-header stage-head glass-panel">
      <div class="stage-main">
        <div v-if="hasHeaderPrefixSlot" class="header-prefix">
          <slot name="header-prefix" />
        </div>
        <div class="stage-brand">
          <div class="asset-selector">
            <h3>
              <button
                type="button"
                class="asset-selector-toggle"
                :title="selectedAsset?.name"
                :disabled="editing || draftBusy"
                :aria-expanded="showAssetMenu"
                @click="showAssetMenu = !showAssetMenu"
              >
                <span>{{ selectedAsset?.name || t("doc_review.no_document_selected") }}</span>
                <ChevronDown v-if="!editing" class="w-4 h-4 text-slate-500" aria-hidden="true" />
              </button>
            </h3>
            <span
              v-if="editing"
              class="draft-status"
              :class="{ stale: draftStale }"
              :title="draftStale ? t('doc_review.draft_stale') : undefined"
              role="status"
            >{{ draftStatusText }}</span>

            <div
              v-if="showAssetMenu"
              class="dropdown-overlay"
              @click.stop="showAssetMenu = false"
            ></div>
            <div
              v-if="showAssetMenu"
              class="asset-dropdown glass-panel fade-in"
            >
              <div class="dropdown-header">
                <span>{{ t("doc_review.document_assets_count", { count: assets.length }) }}</span>
              </div>
              <div class="asset-list custom-scrollbar">
                <p v-if="loadAssetsError" class="asset-empty error">
                  {{ loadAssetsError }}
                </p>
                <button
                  v-for="asset in assets"
                  :key="asset.id"
                  class="asset-item"
                  :class="{ active: asset.id === selectedAssetId }"
                  @click.stop="selectAsset(asset.id)"
                >
                  <div class="asset-item-main">
                    <div class="icon-container blue">
                      <FileText :size="14" :stroke-width="2.5" />
                    </div>
                    <div class="asset-item-info">
                      <strong :title="asset.name">{{ asset.name }}</strong>
                      <div class="asset-item-meta">
                        <span class="type-tag">{{ asset.asset_type }}</span>
                        <span class="date-tag">
                          <Clock :size="10" />
                          {{ new Date(asset.created_at).toLocaleDateString() }}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
                <p
                  v-if="!loadingAssets && assets.length === 0"
                  class="asset-empty"
                >
                  {{ t("doc_review.no_document_assets") }}
                </p>
              </div>
            </div>
          </div>
          <div class="hints">
            <SpecBaselineStatus
              v-if="props.taskId && props.bootstrapStatus && !isPdfAsset"
              :snapshot="props.bootstrapStatus"
              :can-build="canTriggerBootstrap"
              :building="bootstrapTriggering"
              @build="showBootstrapConfirm = true"
            />
            <p v-if="selectedAsset">
              {{ t("doc_review.asset_id_prefix") }}: {{ selectedAsset.id }}
            </p>
            <p v-else-if="noAssetHint" class="no-asset-hint">
              {{ noAssetHint }}
            </p>
            <p v-if="readOnlyMode" class="readonly-hint">{{ t("doc_review.readonly_mode") }}</p>
            <p v-else-if="historicalVersionReadonly" class="readonly-hint historical-readonly-hint">
              {{ t("doc_review.historical_version_readonly") }}
            </p>
          </div>
        </div>
      </div>
      <div class="stage-actions">
        <VersionSwitcher
          v-if="selectedAssetId && !editing"
          v-model="selectedVersionId"
          :versions="versions"
          :loading="loadingVersions"
          class="stage-version-switcher"
          @update:model-value="changeVersion"
        />
        <button v-if="canOpenDraft && !editing" class="btn-primary" :disabled="draftBusy" @click="draftEditor.begin">
          {{ t("doc_review.draft_edit") }}
        </button>
        <template v-if="editing">
          <button class="btn-secondary" :disabled="draftBusy" @click="draftEditor.leave">{{ t("doc_review.draft_back") }}</button>
          <button class="btn-secondary" :disabled="draftBusy" @click="draftConfirm = 'discard'">{{ t("doc_review.draft_discard") }}</button>
          <button v-if="draftText !== null" class="btn-secondary" :disabled="!draftDirty || draftBusy || !canOpenDraft" @click="draftEditor.saveSource">
            {{ t("doc_review.draft_save") }}
          </button>
          <button class="btn-primary" :disabled="!canPublish || draftBusy || !canOpenDraft" @click="draftConfirm = 'publish'">
            {{ t("doc_review.draft_publish") }}
          </button>
        </template>
        <slot name="header-actions" />
      </div>
    </header>

    <div class="workbench-body">
      <section class="document-stage">
        <div v-if="isRelocationPending" class="relocation-hint">
          {{ relocationHintText }}
        </div>
        <div class="canvas-shell custom-scrollbar">
          <PdfCanvas
            v-if="isPdfAsset"
            class="pdf-stage"
            :ws-id="props.wsId"
            :asset-id="selectedAssetId || ''"
            :version-id="pdfVersionId"
          />
          <textarea
            v-else-if="editing && draftText !== null"
            class="draft-source-editor"
            :aria-label="t(isMarkdown ? 'doc_review.draft_markdown_source' : 'doc_review.draft_plain_source')"
            :value="draftText"
            :disabled="draftBusy || !canOpenDraft"
            spellcheck="false"
            wrap="off"
            @input="draftEditor.updateSource"
          />
          <TextReviewCanvas
            v-else-if="formalText !== null"
            :source="formalText"
            :markdown="isMarkdown"
            :markers-by-block="markersByBlock"
            :threads="threads"
            :selected-thread-id="selectedThreadId"
            :inline-review-enabled="inlineReviewEnabled"
            @open-threads="openAnchoredThreads"
            @select-range="handleSelectRange"
            @clear-selection="selectionPayload = null"
          />
          <component
            v-else
            :is="docxSource ? DocxReviewCanvas : DocumentCanvas"
            v-bind="docxSource ? { ...docxSource, threads } : {}"
            :blocks="visibleBlocks"
            :markers-by-block="editing ? {} : markersByBlock"
            :selected-thread-id="selectedThreadId"
            :inline-review-enabled="inlineReviewEnabled"
            :can-manual-edit="editing && canOpenDraft && !draftBusy && !editingBlockId"
            :saving="draftBusy"
            :editing-block-id="editingBlockId"
            @open-threads="openAnchoredThreads"
            @select-range="handleSelectRange"
            @clear-selection="selectionPayload = null"
            @start-edit="startBlockEdit"
            @save-block-edit="draftEditor.saveBlock"
            @cancel-block-edit="editingBlockId = ''"
          />
        </div>

        <InlineSelectionPopover
          v-if="!isPdfAsset"
          :selection="selectionPayload"
          :can-comment="effectiveCapabilities.can_comment"
          @close="selectionPayload = null"
          @create="createThreadFromSelection"
        />
        <ReviewAnnotationPopover
          :target="annotationTarget"
          :threads="threads"
          :selected-thread-id="selectedThreadId"
          @close="annotationTarget = null"
          @open-thread="openThread"
        />
      </section>

      <ThreadSidebar
        v-if="!isPdfAsset"
        class="discussion-stage"
        :threads="threads"
        :selected-thread-id="selectedThreadId"
        :assistant-job-map="assistantJobMap"
        :pending-revisions="pendingRevisions"
        :version-numbers="versionNumbers"
        :requesting-proposal="requestingComparison"
        :readonly="readOnlyMode || historicalVersionReadonly || editing"
        :draft-editing="editing"
        :can-comment="effectiveCapabilities.can_comment"
        :can-ai-reply="effectiveCapabilities.can_ai_reply"
        :ai-available="effectiveCapabilities.ai_available"
        :ai-unavailable-reason="effectiveCapabilities.ai_unavailable_reason"
        :can-apply-resolution="effectiveCapabilities.can_apply_resolution"
        :online-users="onlineUsers"
        :ws-connected="wsConnected"
        @cancel-ai-job="cancelThreadAiJob"
        @select-thread="openThread"
        @show-original="showOriginal"
        @send-message="sendThreadMessage"
        @ask-ai="askThreadAi"
        @generate-proposal="revisions.selectSources"
        @resume-proposal="revisions.openJob"
        @open-proposal="revisions.openProposal"
        @update-state="updateThreadState"
        @close-hint-action="handleThreadCloseHintAction"
      />
    </div>
  </div>

  <ProposalDraftModal
    :visible="showPicker || !!legacyProposal"
    :proposal="legacyProposal"
    :selecting-sources="showPicker"
    :source-options="proposalSourceOptions"
    :submitting="requestingComparison"
    :can-rewrite="aiAvailableNow && (showPicker || !revisionBlockedReason)"
    :rewrite-disabled-reason="(showPicker ? '' : revisionBlockedReason) || aiUnavailableReasonText"
    @close="revisions.closeSources"
    @generate="revisions.generate"
    @rewrite="revisions.rewrite"
  />

  <ResolutionDiffModal
    :visible="!!revisionJob || !!comparison"
    :proposal="comparison"
    :ws-id="wsId"
    :asset-id="selectedAssetId"
    :asset-name="selectedAsset?.name"
    :markdown="isMarkdown"
    :job="revisionJob"
    :result-error="revisionResultError"
    :can-apply="effectiveCapabilities.can_apply_resolution && !revisionBlockedReason"
    :can-rewrite="aiAvailableNow && !revisionBlockedReason"
    :rewrite-disabled-reason="revisionBlockedReason || aiUnavailableReasonText"
    :applying="applyingRevision"
    :submitting="requestingComparison"
    :cancelling="cancellingRevision"
    @close="revisions.closeRevision"
    @minimize="revisions.minimize"
    @retry-result="revisions.loadResult"
    @regenerate="revisions.regenerate"
    @apply="revisions.apply"
  />

  <ConfirmActionModal
    v-if="draftConfirm"
    :show="true"
    :title="t(`doc_review.draft_${draftConfirm}_title`)"
    :message="t(`doc_review.draft_${draftConfirm}_message`)"
    :cancel-text="t('common.cancel')"
    :confirm-text="t(draftConfirm === 'leave' ? 'doc_review.draft_back' : `doc_review.draft_${draftConfirm}`)"
    :tone="draftConfirm === 'publish' ? 'primary' : 'danger'"
    :loading="draftBusy"
    @cancel="draftConfirm = null"
    @confirm="draftEditor.confirmAction"
  />

  <ConfirmActionModal
    :show="!!overwriteRequest"
    :title="t('doc_review.proposal_overwrite_title')"
    :message="t('doc_review.proposal_overwrite_message')"
    :cancel-text="t('doc_review.proposal_overwrite_keep_action')"
    :confirm-text="t('doc_review.proposal_overwrite_confirm_action')"
    tone="danger"
    @cancel="revisions.keepDraft"
    @confirm="revisions.overwriteDraft"
  />

  <ConfirmActionModal
    :show="showBootstrapConfirm"
    :title="t('chat.spec_bootstrap_build_confirm_title')"
    :message="t('chat.spec_bootstrap_build_confirm_message')"
    :cancel-text="t('common.cancel')"
    :confirm-text="t('chat.spec_bootstrap_action_build')"
    tone="primary"
    :loading="bootstrapTriggering"
    @cancel="showBootstrapConfirm = false"
    @confirm="confirmBootstrapBuild"
  />
</template>

<style scoped src="./docReviewWorkbench.css"></style>
