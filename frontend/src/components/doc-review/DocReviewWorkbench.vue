<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, useSlots, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { ChevronDown, FileText, Clock } from '@/components/icons';
import api from "@/utils/api";
import { formatApiError } from "@/utils/error";
import {
  useAssetDiscussion,
  type AssetAiJob,
  type AssetResolutionProposal,
  type AssetSummary,
} from "@/composables/useAssetDiscussion";
import DocumentCanvas from "./DocumentCanvas.vue";
import InlineSelectionPopover from "./InlineSelectionPopover.vue";
import PdfCanvas from "./PdfCanvas.vue";
import ProposalDraftModal from "./ProposalDraftModal.vue";
import ResolutionDiffModal from "./ResolutionDiffModal.vue";
import TextReviewCanvas from "./TextReviewCanvas.vue";
import ThreadSidebar from "./ThreadSidebar.vue";
import SpecBaselineStatus from "./SpecBaselineStatus.vue";
import VersionSwitcher from "./VersionSwitcher.vue";
import { useDocumentDraft } from "./useDocumentDraft";
import ConfirmActionModal from "@/components/ConfirmActionModal.vue";
import type { ResolutionDecisionPayload, ResolutionApplyPayload } from "@/composables/useAssetDiscussion";
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
  /** Spec 基线状态由宿主注入：会话内复用 vm.specBootstrap（WS 推送），独立页接 useTaskSpecBootstrapFeed */
  bootstrapStatus?: TaskSpecBootstrapProgress | null;
}>();

const loadingAssets = ref(false);
const loadAssetsError = ref("");
const assets = ref<AssetSummary[]>([]);
const selectedAssetId = ref("");
const selectedVersionId = ref("");
const selectionPayload = ref<{
  block_id: string;
  selected_text: string;
  char_start?: number;
  char_end?: number;
  anchor: { top: number; left: number };
} | null>(null);

const proposalDraftModalVisible = ref(false);
const revisionModalVisible = ref(false);
const modalProposalId = ref("");
const proposalThreadId = ref("");
const applyingProposal = ref(false);
const proposalDraftSnapshot = ref<AssetResolutionProposal | null>(null);
const revisionSnapshot = ref<AssetResolutionProposal | null>(null);
const forceRevisionSnapshot = ref(false);
const overwriteConfirmVisible = ref(false);
const overwriteTargetThreadId = ref("");
const overwriteTargetDraftId = ref("");
const bootstrapTriggering = ref(false);
const showBootstrapConfirm = ref(false);

const confirmBootstrapBuild = async () => {
  if (bootstrapTriggering.value) return;
  showBootstrapConfirm.value = false;
  await triggerBootstrap();
};
const pendingRelocation = ref<{
  threadId: string;
  proposalId: string;
  proposalText: string;
  rewriteScope: "anchor" | "document";
} | null>(null);
const ASSET_PAGE_SIZE = 100;
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

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
  proposalJobMap,
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

const proposalThread = computed(
  () => threads.value.find((item) => item.id === proposalThreadId.value) || null,
);
const proposalJob = computed<AssetAiJob | null>(() => {
  if (!proposalThreadId.value) return null;
  return proposalJobMap.value[proposalThreadId.value] || null;
});
const isProposalGenerating = computed(() => {
  const status = proposalJob.value?.status;
  return status === "PENDING" || status === "RUNNING" || status === "WAITING_HITL";
});
const findActiveModalProposal = () => {
  if (modalProposalId.value) {
    for (const thread of threads.value) {
      const proposal = thread.proposals.find((item) => item.id === modalProposalId.value);
      if (proposal) return proposal;
    }
    return null;
  }
  return proposalThread.value?.proposals?.[0] || null;
};
const proposalForDraftModal = computed<AssetResolutionProposal | null>(() => {
  if (!proposalDraftModalVisible.value) return null;
  if (isProposalGenerating.value && !modalProposalId.value && !proposalDraftSnapshot.value) {
    return null;
  }
  return findActiveModalProposal() || proposalDraftSnapshot.value || null;
});
const proposalForRevisionModal = computed<AssetResolutionProposal | null>(() => {
  if (!revisionModalVisible.value) return null;
  if (forceRevisionSnapshot.value && revisionSnapshot.value) {
    return revisionSnapshot.value;
  }
  return findActiveModalProposal() || revisionSnapshot.value || null;
});

const hasMergedRevisionDraft = (proposal: AssetResolutionProposal | null) => {
  if (!proposal?.proposed_patch_json || typeof proposal.proposed_patch_json !== "object") {
    return false;
  }
  const patch = proposal.proposed_patch_json as Record<string, any>;
  if (Array.isArray(patch.merged_blocks_ast) && patch.merged_blocks_ast.length > 0) {
    return true;
  }
  return !!patch.merged_block_ast && typeof patch.merged_block_ast === "object";
};

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

const loadAssets = async () => {
  if (!props.wsId) return;
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

    assets.value = scopedAssets;

    const preferredId = props.initialAssetId || selectedAssetId.value;
    if (preferredId && assets.value.some((item) => item.id === preferredId)) {
      selectedAssetId.value = preferredId;
      return;
    }

    const firstSpec = assets.value.find((item) => item.asset_type === "SPEC");
    selectedAssetId.value = firstSpec?.id || assets.value[0]?.id || "";
  } catch (err: any) {
    loadAssetsError.value = err?.response?.data?.detail || t("doc_review.assets_load_failed");
    assets.value = [];
    selectedAssetId.value = "";
  } finally {
    loadingAssets.value = false;
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
    const relocation = pendingRelocation.value;
    pendingRelocation.value = null;
    proposalThreadId.value = relocation.threadId;
    modalProposalId.value = relocation.proposalId;
    forceRevisionSnapshot.value = true;
    proposalDraftModalVisible.value = false;
    revisionModalVisible.value = true;
    try {
      await discussion.rewriteResolutionProposal(
        relocation.threadId,
        relocation.proposalId,
        relocation.proposalText,
        relocation.rewriteScope,
        selectedVersionId.value || activeVersionId.value || undefined,
        {
          block_id: payload.block_id,
          selected_text: payload.selected_text,
          char_start: payload.char_start ?? null,
          char_end: payload.char_end ?? null,
        },
      );
      ElMessage.success(t("doc_review.anchor_relocation_applied"));
    } catch (error: unknown) {
      ElMessage.error(formatApiError(error, t("doc_review.proposal_rewrite_failed"), t));
      forceRevisionSnapshot.value = false;
      revisionModalVisible.value = false;
      proposalDraftModalVisible.value = true;
    }
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

const findProposalThread = (proposalId: string) =>
  threads.value.find((item) =>
    item.proposals.some((proposal) => proposal.id === proposalId),
  );

const clearModalContext = () => {
  modalProposalId.value = "";
  proposalThreadId.value = "";
};

const closeProposalDraftModal = (force = false) => {
  if (!force && applyingProposal.value) return;
  proposalDraftModalVisible.value = false;
  proposalDraftSnapshot.value = null;
  if (!revisionModalVisible.value) {
    forceRevisionSnapshot.value = false;
    revisionSnapshot.value = null;
    clearModalContext();
  }
};

const closeRevisionModal = (force = false) => {
  if (!force && applyingProposal.value) return;
  revisionModalVisible.value = false;
  forceRevisionSnapshot.value = false;
  revisionSnapshot.value = null;
  if (!proposalDraftModalVisible.value) {
    proposalDraftSnapshot.value = null;
    clearModalContext();
  }
};

const openProposalById = (proposalId: string) => {
  const thread = findProposalThread(proposalId);
  if (!thread) return;
  const proposal = thread.proposals.find((item) => item.id === proposalId) || null;
  forceRevisionSnapshot.value = false;
  proposalThreadId.value = thread.id;
  modalProposalId.value = proposalId;
  proposalDraftSnapshot.value = proposal;
  revisionSnapshot.value = proposal;
  if (hasMergedRevisionDraft(proposal)) {
    proposalDraftModalVisible.value = false;
    revisionModalVisible.value = true;
    return;
  }
  revisionModalVisible.value = false;
  proposalDraftModalVisible.value = true;
};

const clearOverwriteConfirmState = () => {
  overwriteConfirmVisible.value = false;
  overwriteTargetThreadId.value = "";
  overwriteTargetDraftId.value = "";
};

const openOverwriteConfirm = (threadId: string, draftId: string) => {
  overwriteTargetThreadId.value = threadId;
  overwriteTargetDraftId.value = draftId;
  overwriteConfirmVisible.value = true;
};

const runCreateResolutionProposal = async (
  threadId: string,
  existingDraft: AssetResolutionProposal | null,
  overwriteExistingDraft: boolean,
) => {
  proposalThreadId.value = threadId;
  modalProposalId.value = existingDraft?.id || "";
  proposalDraftSnapshot.value = existingDraft || null;
  revisionSnapshot.value = null;
  revisionModalVisible.value = false;
  proposalDraftModalVisible.value = true;
  try {
    await discussion.createResolutionProposal(
      threadId,
      overwriteExistingDraft,
      selectedVersionId.value || activeVersionId.value || undefined,
    );
  } catch (error: unknown) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 409) {
      const detail = (error as { response?: { data?: { detail?: any } } })?.response?.data?.detail;
      const existingDraftId =
        detail && typeof detail === "object"
          ? String((detail as Record<string, any>).existing_draft_id || "").trim()
          : "";
      if (existingDraftId) {
        ElMessage.warning(t("doc_review.proposal_draft_exists_opened"));
        openProposalById(existingDraftId);
        return;
      }
      ElMessage.warning(t("doc_review.ai_job_bootstrap_not_ready"));
      closeProposalDraftModal(true);
      return;
    }
    ElMessage.error(formatApiError(error, t("doc_review.proposal_create_failed"), t));
    closeProposalDraftModal(true);
  }
};

const openProposalModalForThread = async (threadId: string) => {
  if (!effectiveCapabilities.value.can_comment) return;
  if (!aiAvailableNow.value) {
    ElMessage.warning(aiUnavailableReasonText.value);
    return;
  }
  const thread = threads.value.find((item) => item.id === threadId) || null;
  const existingDraft = thread?.proposals.find((item) => item.status === "draft") || null;
  if (existingDraft) {
    openOverwriteConfirm(threadId, existingDraft.id);
    return;
  }
  await runCreateResolutionProposal(threadId, null, false);
};

const keepCurrentProposalDraft = () => {
  const targetDraftId = overwriteTargetDraftId.value;
  clearOverwriteConfirmState();
  if (targetDraftId) {
    openProposalById(targetDraftId);
  }
};

const overwriteCurrentProposalDraft = async () => {
  const targetThreadId = overwriteTargetThreadId.value;
  const targetDraftId = overwriteTargetDraftId.value;
  clearOverwriteConfirmState();
  if (!targetThreadId) return;
  const thread = threads.value.find((item) => item.id === targetThreadId) || null;
  const existingDraft =
    thread?.proposals.find((item) => item.id === targetDraftId) ||
    thread?.proposals.find((item) => item.status === "draft") ||
    null;
  await runCreateResolutionProposal(targetThreadId, existingDraft, true);
};

const applyProposal = async (
  threadId: string,
  proposalId: string,
  payload: ResolutionApplyPayload,
  decision?: ResolutionDecisionPayload | null,
) => {
  if (!effectiveCapabilities.value.can_apply_resolution) return;
  applyingProposal.value = true;
  try {
    await discussion.applyResolutionProposal(threadId, proposalId, payload, undefined, decision);
    closeRevisionModal(true);
  } catch (error: unknown) {
    ElMessage.error(formatApiError(error, t("doc_review.proposal_apply_failed"), t));
  } finally {
    applyingProposal.value = false;
  }
};

const applyProposalFromModal = async (
  proposalId: string,
  payload: ResolutionApplyPayload,
  decision?: ResolutionDecisionPayload | null,
) => {
  const thread = findProposalThread(proposalId);
  if (!thread) return;
  await applyProposal(thread.id, proposalId, payload, decision);
};

const regenerateRevisionFromModal = async (
  proposalId: string,
  proposalText: string,
  rewriteScope: "anchor" | "document",
) => {
  const normalized = String(proposalText || "").trim();
  if (!normalized) {
    ElMessage.warning(t("doc_review.proposal_rewrite_missing_text"));
    return;
  }
  await rewriteProposalFromDraft(proposalId, normalized, rewriteScope);
};

const rewriteProposalFromDraft = async (
  proposalId: string,
  proposalText: string,
  rewriteScope: "anchor" | "document",
) => {
  const thread = findProposalThread(proposalId);
  if (!thread) return;
  if (!aiAvailableNow.value) {
    ElMessage.warning(aiUnavailableReasonText.value);
    return;
  }
  proposalThreadId.value = thread.id;
  modalProposalId.value = proposalId;
  const snapshot = thread.proposals.find((item) => item.id === proposalId) || null;
  proposalDraftSnapshot.value = snapshot || proposalDraftSnapshot.value;
  const baseSnapshot = snapshot || proposalDraftSnapshot.value || revisionSnapshot.value;
  if (baseSnapshot) {
    const nextSnapshot = clone(baseSnapshot);
    const patch: Record<string, any> = {
      ...((nextSnapshot.proposed_patch_json || {}) as Record<string, any>),
      rewrite_status: "running",
    };
    delete patch.merged_block_ast;
    delete patch.merged_blocks_ast;
    delete patch.final_block_ast;
    delete patch.final_blocks_ast;
    delete patch.new_block_ast;
    delete patch.new_blocks_ast;
    nextSnapshot.proposed_patch_json = patch;
    revisionSnapshot.value = nextSnapshot;
  } else {
    revisionSnapshot.value = null;
  }
  if (rewriteScope === "anchor") {
    if (String(thread.anchor_status || "valid") === "missing") {
      pendingRelocation.value = {
        threadId: thread.id,
        proposalId,
        proposalText,
        rewriteScope,
      };
      proposalDraftModalVisible.value = false;
      revisionModalVisible.value = false;
      selectionPayload.value = null;
      ElMessage.warning(t("doc_review.anchor_relocation_required"));
      return;
    }
  }
  forceRevisionSnapshot.value = true;
  proposalDraftModalVisible.value = false;
  revisionModalVisible.value = true;
  try {
    await discussion.rewriteResolutionProposal(
      thread.id,
      proposalId,
      proposalText,
      rewriteScope,
      selectedVersionId.value || activeVersionId.value || undefined,
    );
  } catch (error: unknown) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 409) {
      ElMessage.warning(t("doc_review.ai_job_bootstrap_not_ready"));
      forceRevisionSnapshot.value = false;
      revisionModalVisible.value = false;
      proposalDraftModalVisible.value = true;
      return;
    }
    ElMessage.error(formatApiError(error, t("doc_review.proposal_rewrite_failed"), t));
    forceRevisionSnapshot.value = false;
    revisionModalVisible.value = false;
    proposalDraftModalVisible.value = true;
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
  const document = await discussion.loadDocument(versionId);
  if (!document || selectedVersionId.value !== versionId) return;
  await discussion.loadThreads(versionId);
  if (selectedVersionId.value !== versionId) return;
  selectedThreadId.value = "";
  pendingRelocation.value = null;
  if (proposalDraftModalVisible.value) {
    closeProposalDraftModal(true);
  }
  if (revisionModalVisible.value) {
    closeRevisionModal(true);
  }
};

const showOriginal = async (versionId: string, threadId: string) => {
  if (editing.value) return;
  await changeVersion(versionId);
  if (selectedVersionId.value === versionId) openThread(threadId);
};

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
  () => findActiveModalProposal(),
  (proposal) => {
    if (!proposal) return;
    if (proposalDraftModalVisible.value) {
      proposalDraftSnapshot.value = proposal;
    }
    if (revisionModalVisible.value && !forceRevisionSnapshot.value) {
      revisionSnapshot.value = proposal;
    }
  },
);

watch(
  () => [
    revisionModalVisible.value,
    proposalJob.value?.status || "",
    String(findActiveModalProposal()?.proposed_patch_json?.rewrite_status || "")
      .trim()
      .toLowerCase(),
  ] as const,
  ([visible, jobStatus, rewriteStatus]) => {
    if (!visible) {
      forceRevisionSnapshot.value = false;
      return;
    }
    if (!forceRevisionSnapshot.value) return;
    if (
      jobStatus === "FAILED" ||
      jobStatus === "CANCELLED" ||
      rewriteStatus === "ready"
    ) {
      forceRevisionSnapshot.value = false;
    }
  },
);

watch(
  () => [props.wsId, props.taskId, props.initialAssetId] as const,
  () => {
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
            :selected-thread-id="selectedThreadId"
            :inline-review-enabled="inlineReviewEnabled"
            @open-thread="openThread"
            @select-range="handleSelectRange"
            @clear-selection="selectionPayload = null"
          />
          <component
            v-else
            :is="docxSource ? DocxReviewCanvas : DocumentCanvas"
            v-bind="docxSource || {}"
            :blocks="visibleBlocks"
            :markers-by-block="editing ? {} : markersByBlock"
            :selected-thread-id="selectedThreadId"
            :inline-review-enabled="inlineReviewEnabled"
            :can-manual-edit="editing && canOpenDraft && !draftBusy && !editingBlockId"
            :saving="draftBusy"
            :editing-block-id="editingBlockId"
            @open-thread="openThread"
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
      </section>

      <ThreadSidebar
        v-if="!isPdfAsset"
        class="discussion-stage"
        :threads="threads"
        :selected-thread-id="selectedThreadId"
        :assistant-job-map="assistantJobMap"
        :proposal-job-map="proposalJobMap"
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
        @select-thread="selectedThreadId = $event"
        @show-original="showOriginal"
        @send-message="sendThreadMessage"
        @ask-ai="askThreadAi"
        @generate-proposal="openProposalModalForThread"
        @open-proposal="openProposalById"
        @update-state="updateThreadState"
        @close-hint-action="handleThreadCloseHintAction"
      />
    </div>
  </div>

  <ProposalDraftModal
    :visible="proposalDraftModalVisible"
    :proposal="proposalForDraftModal"
    :proposal-job="proposalJob"
    :can-rewrite="aiAvailableNow"
    :rewrite-disabled-reason="aiUnavailableReasonText"
    @close="closeProposalDraftModal"
    @rewrite="rewriteProposalFromDraft"
  />

  <ResolutionDiffModal
    :visible="revisionModalVisible"
    :proposal="proposalForRevisionModal"
    :proposal-job="proposalJob"
    :can-apply="effectiveCapabilities.can_apply_resolution"
    :can-rewrite="aiAvailableNow"
    :rewrite-disabled-reason="aiUnavailableReasonText"
    :applying="applyingProposal"
    @close="closeRevisionModal"
    @regenerate="regenerateRevisionFromModal"
    @apply="applyProposalFromModal"
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
    :show="overwriteConfirmVisible"
    :title="t('doc_review.proposal_overwrite_title')"
    :message="t('doc_review.proposal_overwrite_message')"
    :cancel-text="t('doc_review.proposal_overwrite_keep_action')"
    :confirm-text="t('doc_review.proposal_overwrite_confirm_action')"
    tone="danger"
    @cancel="keepCurrentProposalDraft"
    @confirm="overwriteCurrentProposalDraft"
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
