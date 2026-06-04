<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useSlots, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { ChevronDown, FileText, Clock } from "lucide-vue-next";
import api from "@/utils/api";
import { useAuthStore } from "@/stores/auth";
import { formatApiError } from "@/utils/error";
import {
  useAssetDiscussion,
  type AssetAiJob,
  type AssetResolutionProposal,
  type AssetSummary,
} from "@/composables/useAssetDiscussion";
import DocumentCanvas from "./DocumentCanvas.vue";
import InlineSelectionPopover from "./InlineSelectionPopover.vue";
import ProposalDraftModal from "./ProposalDraftModal.vue";
import ResolutionDiffModal from "./ResolutionDiffModal.vue";
import ThreadSidebar from "./ThreadSidebar.vue";
import VersionSwitcher from "./VersionSwitcher.vue";
import ConfirmActionModal from "@/components/ConfirmActionModal.vue";
import type { ResolutionDecisionPayload, ResolutionApplyPayload } from "@/composables/useAssetDiscussion";

const showAssetMenu = ref(false);
const { t } = useI18n();
const slots = useSlots();

const props = defineProps<{
  wsId: string;
  taskId?: string;
  compact?: boolean;
  initialAssetId?: string;
  readonly?: boolean;
}>();

const authStore = useAuthStore();
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
const bootstrapStatus = ref<{
  status: string;
  progress: number;
  message?: string | null;
  error_message?: string | null;
} | null>(null);
const bootstrapLoading = ref(false);
const bootstrapPollTimer = ref<number | null>(null);
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
  userId: computed(() => authStore.user?.id || null),
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
const noAssetHint = computed(() => {
  if (loadingAssets.value) return t("doc_review.assets_loading");
  if (loadAssetsError.value) return loadAssetsError.value;
  if (!selectedAssetId.value) return t("doc_review.no_doc_for_current_task");
  return "";
});
const readOnlyMode = computed(() => Boolean(props.readonly));
const effectiveCapabilities = computed(() => {
  const base = capabilities.value;
  if (!readOnlyMode.value) {
    return base;
  }
  return {
    ...base,
    can_comment: false,
    can_ai_reply: false,
    can_apply_resolution: false,
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
const baselineStatusText = computed(() => {
  const status = String(bootstrapStatus.value?.status || "").toUpperCase();
  if (!status) return t("doc_review.baseline_status_unknown");
  if (status === "PENDING") return t("chat.spec_bootstrap_status_pending");
  if (status === "RUNNING") return t("chat.spec_bootstrap_status_running");
  if (status === "READY") return t("chat.spec_bootstrap_status_ready");
  if (status === "FAILED") return t("chat.spec_bootstrap_status_failed");
  if (status === "STALE") return t("chat.spec_bootstrap_status_stale");
  return status;
});
const baselineBusy = computed(() => {
  const status = String(bootstrapStatus.value?.status || "").toUpperCase();
  return status === "PENDING" || status === "RUNNING";
});
const showBaselineStatus = computed(() => {
  if (!props.taskId) return false;
  if (bootstrapLoading.value) return true;
  const status = String(bootstrapStatus.value?.status || "").toUpperCase();
  if (!status) return false;
  return status !== "READY";
});
const bootstrapStatusCode = computed(() =>
  String(bootstrapStatus.value?.status || "").toUpperCase(),
);
const isRelocationPending = computed(() => !!pendingRelocation.value);
const relocationHintText = computed(() =>
  t("doc_review.anchor_relocation_pick_hint"),
);
const hasHeaderPrefixSlot = computed(() => Boolean(slots["header-prefix"]));
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

const clearBootstrapPoll = () => {
  if (bootstrapPollTimer.value !== null) {
    window.clearTimeout(bootstrapPollTimer.value);
    bootstrapPollTimer.value = null;
  }
};

const scheduleBootstrapPoll = () => {
  clearBootstrapPoll();
  if (!props.taskId) return;
  const status = String(bootstrapStatus.value?.status || "").toUpperCase();
  if (!["PENDING", "RUNNING", "STALE"].includes(status)) return;
  bootstrapPollTimer.value = window.setTimeout(() => {
    bootstrapPollTimer.value = null;
    void loadBootstrapStatus();
  }, 1600);
};

const loadBootstrapStatus = async () => {
  if (!props.wsId || !props.taskId) {
    bootstrapStatus.value = null;
    return;
  }
  bootstrapLoading.value = true;
  try {
    const res = await api.get(`/workspaces/${props.wsId}/tasks/${props.taskId}/spec-bootstrap`);
    bootstrapStatus.value = res.data || null;
  } catch (error: unknown) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 404) {
      bootstrapStatus.value = {
        status: "PENDING",
        progress: 0,
        message: t("chat.spec_bootstrap_not_initialized"),
      };
    } else {
      bootstrapStatus.value = {
        status: "FAILED",
        progress: 100,
        message: t("chat.spec_bootstrap_status_failed"),
      };
    }
  } finally {
    bootstrapLoading.value = false;
    scheduleBootstrapPoll();
  }
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
    void loadBootstrapStatus();
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
  await discussion.loadDocument(versionId);
  await discussion.loadThreads(versionId);
  if (props.taskId) {
    void loadBootstrapStatus();
  }
  selectedThreadId.value = "";
  pendingRelocation.value = null;
  if (proposalDraftModalVisible.value) {
    closeProposalDraftModal(true);
  }
  if (revisionModalVisible.value) {
    closeRevisionModal(true);
  }
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
    void loadBootstrapStatus();
  },
);

watch(
  () => bootstrapStatusCode.value,
  (status, previousStatus) => {
    if (!props.taskId || !selectedAssetId.value) return;
    if (status !== "READY" || previousStatus === "READY") return;
    void discussion.loadDocument(selectedVersionId.value || activeVersionId.value || undefined);
  },
);

onMounted(() => {
  void loadAssets();
  void loadBootstrapStatus();
});

onBeforeUnmount(() => {
  clearBootstrapPoll();
});
</script>

<template>
  <div class="doc-review-workbench compact">
    <header
      class="workbench-header stage-head glass-panel"
      :class="{ 'with-external-title': hasHeaderPrefixSlot }"
    >
      <div class="stage-main">
        <div v-if="hasHeaderPrefixSlot" class="header-prefix">
          <slot name="header-prefix" />
        </div>
        <div class="stage-brand">
          <div class="asset-selector" @click="showAssetMenu = !showAssetMenu">
            <h3>{{ selectedAsset?.name || t("doc_review.no_document_selected") }}</h3>
            <ChevronDown class="w-4 h-4 text-slate-500" />

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
                      <strong>{{ asset.name }}</strong>
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
          v-if="selectedAssetId"
          v-model="selectedVersionId"
          :versions="versions"
          :loading="loadingVersions"
          class="stage-version-switcher"
          @update:model-value="changeVersion"
        />
        <slot name="header-actions" />
      </div>
    </header>
    <div v-if="showBaselineStatus" class="baseline-status glass-panel" :class="{ busy: baselineBusy }">
      <div class="baseline-left">
        <strong>{{ t("doc_review.baseline_status_label") }}: {{ baselineStatusText }}</strong>
        <span v-if="bootstrapStatus?.message">{{ bootstrapStatus.message }}</span>
        <span v-else-if="bootstrapLoading">{{ t("chat.spec_bootstrap_loading") }}</span>
      </div>
      <div class="baseline-right">
        <span>{{ Number(bootstrapStatus?.progress || 0) }}%</span>
      </div>
    </div>

    <div class="workbench-body">
      <section class="document-stage">
        <div v-if="isRelocationPending" class="relocation-hint">
          {{ relocationHintText }}
        </div>
        <div class="canvas-shell custom-scrollbar">
        <DocumentCanvas
          :blocks="documentData?.blocks || []"
          :markers-by-block="markersByBlock"
          :selected-thread-id="selectedThreadId"
          :inline-review-enabled="inlineReviewEnabled"
          @open-thread="openThread"
          @select-range="handleSelectRange"
          @clear-selection="selectionPayload = null"
        />
      </div>

      <InlineSelectionPopover
        :selection="selectionPayload"
        :can-comment="effectiveCapabilities.can_comment"
        @close="selectionPayload = null"
        @create="createThreadFromSelection"
      />
    </section>

      <ThreadSidebar
        class="discussion-stage"
        :threads="threads"
        :selected-thread-id="selectedThreadId"
        :assistant-job-map="assistantJobMap"
        :proposal-job-map="proposalJobMap"
        :can-comment="effectiveCapabilities.can_comment"
        :can-ai-reply="effectiveCapabilities.can_ai_reply"
        :ai-available="effectiveCapabilities.ai_available"
        :ai-unavailable-reason="effectiveCapabilities.ai_unavailable_reason"
        :can-apply-resolution="effectiveCapabilities.can_apply_resolution"
        :online-users="onlineUsers"
        :ws-connected="wsConnected"
        @cancel-ai-job="cancelThreadAiJob"
        @select-thread="selectedThreadId = $event"
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
    :show="overwriteConfirmVisible"
    :title="t('doc_review.proposal_overwrite_title')"
    :message="t('doc_review.proposal_overwrite_message')"
    :cancel-text="t('doc_review.proposal_overwrite_keep_action')"
    :confirm-text="t('doc_review.proposal_overwrite_confirm_action')"
    tone="danger"
    @cancel="keepCurrentProposalDraft"
    @confirm="overwriteCurrentProposalDraft"
  />
</template>

<style scoped>
.doc-review-workbench {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  height: 100%;
  min-height: 0;
  width: 100%;
}

.workbench-body {
  display: flex;
  flex: 1;
  gap: 1.5rem;
  min-height: 0;
}

.baseline-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(14, 165, 233, 0.22);
  background: rgba(239, 246, 255, 0.82);
}

.baseline-status.busy {
  border-color: rgba(59, 130, 246, 0.3);
  background: rgba(219, 234, 254, 0.78);
}

.baseline-left {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.baseline-left strong {
  font-size: 13px;
  color: #0f172a;
}

.baseline-left span {
  font-size: 12px;
  color: #475569;
}

.baseline-right {
  font-size: 12px;
  color: #0369a1;
  font-weight: 600;
  min-width: 52px;
  text-align: right;
}

.relocation-hint {
  margin-bottom: 10px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  border: 1px dashed rgba(249, 115, 22, 0.42);
  background: rgba(255, 247, 237, 0.9);
  color: #9a3412;
  font-size: 12px;
}

@media (max-width: 1024px) {
  .workbench-body {
    flex-direction: column;
  }

  .stage-head {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .stage-actions {
    width: 100%;
    justify-content: flex-start;
    margin-left: 0;
  }
}

.document-stage {
  position: relative;
  flex: 1;
  min-width: 600px;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.stage-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius-xl);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
  z-index: 10;
}

.stage-main {
  min-width: min(100%, 300px);
  flex: 1 1 420px;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.stage-head.with-external-title .stage-main {
  gap: 0.6rem;
}

.header-prefix {
  min-width: 0;
  display: flex;
  align-items: center;
}

.stage-brand {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.asset-selector {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  margin: -0.25rem -0.5rem;
  border-radius: var(--radius-md);
  transition: all 0.2s;
}

.asset-selector:hover {
  background: rgba(14, 165, 233, 0.08);
}

.asset-selector .chevron-icon {
  transition: transform 0.2s;
}

.asset-selector:hover .chevron-icon {
  transform: translateY(1px);
}

.asset-selector h3 {
  margin: 0;
  font-family: var(--font-heading), "Poppins", sans-serif;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--color-text-title);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(100%, clamp(220px, 52vw, 860px));
}

.stage-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  flex: 1 1 340px;
  min-width: min(100%, 280px);
  max-width: 100%;
  margin-left: auto;
}

.stage-version-switcher {
  flex: 1 1 320px;
  min-width: 0;
  max-width: 100%;
}

.dropdown-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
}

.asset-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 0.75rem;
  width: 320px;
  max-height: 400px;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: var(--glass-blur);
  border-radius: var(--radius-lg);
  border: 1px solid rgba(14, 165, 233, 0.15);
  box-shadow: var(--shadow-xl);
  z-index: 50;
  overflow: hidden;
}

.dropdown-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--color-text-muted);
}

.asset-list {
  padding: 0.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.asset-item {
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  padding: 8px;
  transition: all 0.1s var(--transition-fast);
}

.asset-item:hover {
  background: rgba(255, 255, 255, 0.8);
  border-color: rgba(14, 165, 233, 0.1);
  transform: translateX(2px);
}

.asset-item.active {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(14, 165, 233, 0.25);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.asset-item-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.icon-container {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
}

.icon-container.blue {
  background: rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
}

.asset-item-info {
  min-width: 0;
  flex: 1;
}

.asset-item strong {
  display: block;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-text-title);
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.type-tag {
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--color-primary-600);
  background: rgba(14, 165, 233, 0.08);
  padding: 1px 6px;
  border-radius: 4px;
  text-transform: uppercase;
}

.date-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  color: var(--color-text-muted);
}

.asset-empty {
  padding: 1rem;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 0.875rem;
}

.asset-empty.error {
  color: #ef4444;
}

.hints {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  min-width: 0;
}

.hints p {
  margin: 0;
  font-size: 0.75rem;
  color: var(--color-text-muted);
  min-width: 0;
  overflow-wrap: anywhere;
  line-break: anywhere;
}

.no-asset-hint {
  color: #f59e0b !important;
}
.readonly-hint {
  color: #0ea5e9 !important;
  font-weight: 600;
}
.historical-readonly-hint {
  color: #f59e0b !important;
}

.canvas-shell {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 8px;
  background: transparent;
}

.discussion-stage {
  flex: 0 0 clamp(400px, 35%, 650px);
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.fade-in {
  animation: fadeIn 0.15s ease-out forwards;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
.h-4 {
  width: 1rem;
  height: 1rem;
}
.text-slate-500 {
  color: #64748b;
}
.ml-1 {
  margin-left: 0.25rem;
}
</style>
