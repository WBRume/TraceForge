<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ArrowLeft } from "lucide-vue-next";
import ThreadTimeline from "./ThreadTimeline.vue";

type ThreadProposal = {
  id: string;
  status: "draft" | "applied" | "discarded";
  diff_text?: string | null;
  created_at: string;
};

type ThreadMessage = {
  id: string;
  role: "user" | "ai" | "system";
  content: string;
  creator_display_name?: string | null;
  created_at: string;
};

type Thread = {
  id: string;
  block_id: string;
  selected_text?: string | null;
  status: "open" | "resolved" | "closed";
  close_hint_state?: "none" | "pending" | "no_close_needed";
  close_hint_reason?: string | null;
  created_at: string;
  updated_at?: string | null;
  messages: ThreadMessage[];
  proposals: ThreadProposal[];
};

type ThreadAiJob = {
  id: string;
  thread_id?: string | null;
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
};

const props = defineProps<{
  threads: Thread[];
  selectedThreadId: string;
  assistantJobMap: Record<string, ThreadAiJob>;
  proposalJobMap: Record<string, ThreadAiJob>;
  canComment: boolean;
  canAiReply: boolean;
  aiAvailable?: boolean;
  aiUnavailableReason?: string | null;
  canApplyResolution: boolean;
  onlineUsers: string[];
  wsConnected: boolean;
}>();

const emit = defineEmits<{
  "select-thread": [threadId: string];
  "send-message": [threadId: string, content: string];
  "ask-ai": [threadId: string, prompt?: string];
  "cancel-ai-job": [jobId: string];
  "generate-proposal": [threadId: string];
  "open-proposal": [proposalId: string];
  "update-state": [threadId: string, status: "open" | "resolved" | "closed"];
  "close-hint-action": [
    threadId: string,
    action: "mark_no_close_needed" | "reset_pending",
  ];
}>();

const { t } = useI18n();

const messageDraft = ref("");
const aiPrompt = ref("");
const resolveConfirmVisible = ref(false);

type OpenAccent = {
  bg: string;
  underline: string;
  selectedBg: string;
  badgeA: string;
  badgeB: string;
  blockBg: string;
  blockBorder: string;
};

const OPEN_ACCENT_PALETTE = [
  {
    bg: "rgba(245, 158, 11, 0.32)",
    underline: "rgba(194, 65, 12, 0.58)",
    selectedBg: "rgba(251, 146, 60, 0.46)",
    badgeA: "#fb923c",
    badgeB: "#f97316",
    blockBg: "rgba(249, 115, 22, 0.13)",
    blockBorder: "rgba(194, 65, 12, 0.2)",
  },
  {
    bg: "rgba(236, 72, 153, 0.27)",
    underline: "rgba(157, 23, 77, 0.56)",
    selectedBg: "rgba(244, 114, 182, 0.4)",
    badgeA: "#f472b6",
    badgeB: "#ec4899",
    blockBg: "rgba(236, 72, 153, 0.12)",
    blockBorder: "rgba(157, 23, 77, 0.22)",
  },
  {
    bg: "rgba(59, 130, 246, 0.25)",
    underline: "rgba(30, 64, 175, 0.54)",
    selectedBg: "rgba(96, 165, 250, 0.37)",
    badgeA: "#60a5fa",
    badgeB: "#2563eb",
    blockBg: "rgba(37, 99, 235, 0.12)",
    blockBorder: "rgba(30, 64, 175, 0.22)",
  },
  {
    bg: "rgba(34, 197, 94, 0.24)",
    underline: "rgba(21, 128, 61, 0.53)",
    selectedBg: "rgba(74, 222, 128, 0.37)",
    badgeA: "#4ade80",
    badgeB: "#22c55e",
    blockBg: "rgba(34, 197, 94, 0.12)",
    blockBorder: "rgba(21, 128, 61, 0.21)",
  },
  {
    bg: "rgba(168, 85, 247, 0.24)",
    underline: "rgba(107, 33, 168, 0.52)",
    selectedBg: "rgba(192, 132, 252, 0.36)",
    badgeA: "#c084fc",
    badgeB: "#a855f7",
    blockBg: "rgba(168, 85, 247, 0.12)",
    blockBorder: "rgba(107, 33, 168, 0.22)",
  },
  {
    bg: "rgba(239, 68, 68, 0.25)",
    underline: "rgba(153, 27, 27, 0.54)",
    selectedBg: "rgba(248, 113, 113, 0.37)",
    badgeA: "#f87171",
    badgeB: "#ef4444",
    blockBg: "rgba(239, 68, 68, 0.12)",
    blockBorder: "rgba(153, 27, 27, 0.22)",
  },
  {
    bg: "rgba(6, 182, 212, 0.24)",
    underline: "rgba(14, 116, 144, 0.53)",
    selectedBg: "rgba(34, 211, 238, 0.36)",
    badgeA: "#22d3ee",
    badgeB: "#06b6d4",
    blockBg: "rgba(6, 182, 212, 0.12)",
    blockBorder: "rgba(14, 116, 144, 0.22)",
  },
  {
    bg: "rgba(132, 204, 22, 0.24)",
    underline: "rgba(77, 124, 15, 0.52)",
    selectedBg: "rgba(163, 230, 53, 0.36)",
    badgeA: "#a3e635",
    badgeB: "#84cc16",
    blockBg: "rgba(132, 204, 22, 0.12)",
    blockBorder: "rgba(77, 124, 15, 0.22)",
  },
  {
    bg: "rgba(20, 184, 166, 0.24)",
    underline: "rgba(15, 118, 110, 0.54)",
    selectedBg: "rgba(45, 212, 191, 0.36)",
    badgeA: "#2dd4bf",
    badgeB: "#14b8a6",
    blockBg: "rgba(20, 184, 166, 0.12)",
    blockBorder: "rgba(15, 118, 110, 0.22)",
  },
  {
    bg: "rgba(244, 63, 94, 0.24)",
    underline: "rgba(159, 18, 57, 0.54)",
    selectedBg: "rgba(251, 113, 133, 0.36)",
    badgeA: "#fb7185",
    badgeB: "#f43f5e",
    blockBg: "rgba(244, 63, 94, 0.12)",
    blockBorder: "rgba(159, 18, 57, 0.22)",
  },
  {
    bg: "rgba(251, 146, 60, 0.25)",
    underline: "rgba(154, 52, 18, 0.54)",
    selectedBg: "rgba(253, 186, 116, 0.37)",
    badgeA: "#fdba74",
    badgeB: "#fb923c",
    blockBg: "rgba(251, 146, 60, 0.12)",
    blockBorder: "rgba(154, 52, 18, 0.22)",
  },
  {
    bg: "rgba(129, 140, 248, 0.24)",
    underline: "rgba(67, 56, 202, 0.54)",
    selectedBg: "rgba(165, 180, 252, 0.36)",
    badgeA: "#a5b4fc",
    badgeB: "#818cf8",
    blockBg: "rgba(129, 140, 248, 0.12)",
    blockBorder: "rgba(67, 56, 202, 0.22)",
  },
] as const satisfies ReadonlyArray<OpenAccent>;

const accentByOrder = (index: number): OpenAccent => {
  const direct = OPEN_ACCENT_PALETTE[index];
  if (direct) return direct;
  const hue = Math.round((index * 137.508) % 360);
  return {
    bg: `hsla(${hue}, 84%, 56%, 0.24)`,
    underline: `hsla(${hue}, 72%, 34%, 0.54)`,
    selectedBg: `hsla(${hue}, 88%, 62%, 0.36)`,
    badgeA: `hsl(${hue}, 88%, 62%)`,
    badgeB: `hsl(${(hue + 24) % 360}, 82%, 50%)`,
    blockBg: `hsla(${hue}, 86%, 58%, 0.12)`,
    blockBorder: `hsla(${hue}, 72%, 36%, 0.22)`,
  };
};

const openThreadAccentMap = computed<Record<string, OpenAccent>>(() => {
  const openThreadIds = Array.from(
    new Set(
      props.threads
        .filter((thread) => thread.status === "open")
        .map((thread) => thread.id),
    ),
  ).sort();
  const map: Record<string, OpenAccent> = {};
  openThreadIds.forEach((threadId, index) => {
    map[threadId] = accentByOrder(index);
  });
  return map;
});

const openAccentByThread = (threadId: string): OpenAccent =>
  openThreadAccentMap.value[threadId] || accentByOrder(0);

const threadCardStyle = (
  thread: Thread,
): Record<string, string> | undefined => {
  if (thread.status !== "open") return undefined;
  const accent = openAccentByThread(thread.id);
  return {
    "--thread-open-bg": accent.blockBg,
    "--thread-open-border": accent.blockBorder,
    "--thread-open-glow": accent.blockBorder,
  };
};

const threadPillStyle = (
  thread: Thread,
): Record<string, string> | undefined => {
  if (thread.status !== "open") return undefined;
  const accent = openAccentByThread(thread.id);
  return {
    "--thread-pill-color": accent.badgeB,
    "--thread-pill-shadow": `0 4px 12px ${accent.blockBorder}`,
  };
};

const selectedThread = computed(
  () =>
    props.threads.find((item) => item.id === props.selectedThreadId) || null,
);

const hasAppliedProposal = (thread: Thread | null | undefined): boolean =>
  Boolean(thread?.proposals?.some((proposal) => proposal.status === "applied"));

const shouldShowAnchorCloseHint = (thread: Thread | null | undefined): boolean => {
  if (!thread) return false;
  if (thread.status !== "open") return false;
  if (hasAppliedProposal(thread)) return false;
  return (
    thread.close_hint_reason === "anchor_missing" &&
    thread.close_hint_state !== "none"
  );
};

const sortedThreads = computed<Thread[]>(() => {
  const rank = (thread: Thread) => {
    if (shouldShowAnchorCloseHint(thread) && thread.close_hint_state === "pending") return 0;
    if (thread.status === "open") return 1;
    if (thread.status === "resolved") return 2;
    return 3;
  };
  return [...props.threads].sort((a, b) => {
    const rankDiff = rank(a) - rank(b);
    if (rankDiff !== 0) return rankDiff;
    const aTime = new Date(a.updated_at || a.created_at).getTime();
    const bTime = new Date(b.updated_at || b.created_at).getTime();
    return bTime - aTime;
  });
});
const selectedThreadJob = computed<ThreadAiJob | null>(() => {
  if (!selectedThread.value) return null;
  return props.assistantJobMap[selectedThread.value.id] || null;
});
const selectedProposalJob = computed<ThreadAiJob | null>(() => {
  if (!selectedThread.value) return null;
  return props.proposalJobMap[selectedThread.value.id] || null;
});
const isProposalGenerating = computed(
  () => {
    const status = selectedProposalJob.value?.status;
    return (
      status === "PENDING" ||
      status === "RUNNING" ||
      status === "WAITING_HITL"
    );
  },
);
const isSelectedThreadOpen = computed(() => selectedThread.value?.status === "open");
const canUseAiFeatures = computed(
  () =>
    Boolean(
      props.canAiReply &&
        (props.aiAvailable !== false) &&
        isSelectedThreadOpen.value,
    ),
);

watch(
  () => props.selectedThreadId,
  () => {
    messageDraft.value = "";
    aiPrompt.value = "";
    resolveConfirmVisible.value = false;
  },
);

const sendMessage = () => {
  if (!selectedThread.value) return;
  if (!isSelectedThreadOpen.value) return;
  const content = messageDraft.value.trim();
  if (!content) return;
  emit("send-message", selectedThread.value.id, content);
  messageDraft.value = "";
};

const askAi = () => {
  if (!selectedThread.value) return;
  if (!canUseAiFeatures.value) return;
  emit("ask-ai", selectedThread.value.id, aiPrompt.value.trim() || undefined);
  aiPrompt.value = "";
};

const cancelAssistantJob = () => {
  if (!selectedThreadJob.value?.id) return;
  emit("cancel-ai-job", selectedThreadJob.value.id);
};

const generateProposal = () => {
  if (!selectedThread.value) return;
  if (!canUseAiFeatures.value) return;
  emit("generate-proposal", selectedThread.value.id);
};

const cancelProposalJob = () => {
  if (!selectedProposalJob.value?.id) return;
  emit("cancel-ai-job", selectedProposalJob.value.id);
};

const statusLabel = (status: string) =>
  status === "resolved"
    ? t("doc_review.thread_status_resolved")
    : status === "closed"
      ? t("doc_review.thread_status_closed")
      : t("doc_review.thread_status_open");

const proposalStatusLabel = (status: ThreadProposal["status"]) => {
  if (status === "applied") {
    return t("doc_review.proposal_status_applied");
  }
  if (status === "discarded") {
    return t("doc_review.proposal_status_discarded");
  }
  return t("doc_review.proposal_status_draft");
};

const isAiBusy = computed(() => {
  const status = selectedThreadJob.value?.status;
  return (
    status === "PENDING" || status === "RUNNING" || status === "WAITING_HITL"
  );
});
const canCancelAssistantJob = computed(
  () =>
    Boolean(
      props.canComment &&
      selectedThreadJob.value?.id &&
      isAiBusy.value,
    ),
);
const canCancelProposalJob = computed(
  () =>
    Boolean(
      props.canComment &&
      selectedProposalJob.value?.id &&
      isProposalGenerating.value,
    ),
);
const aiStatusText = computed(() => {
  const status = selectedThreadJob.value?.status;
  if (status === "PENDING") return t("doc_review.ai_status_pending");
  if (status === "RUNNING") return t("doc_review.ai_status_running");
  if (status === "WAITING_HITL") return t("doc_review.ai_status_waiting_hitl");
  if (status === "FAILED") return t("doc_review.ai_status_failed");
  if (status === "CANCELLED") return t("doc_review.ai_status_cancelled");
  if (status === "SUCCESS") return t("doc_review.ai_status_success");
  return "";
});

const hasProposalOnSelectedThread = computed(
  () => (selectedThread.value?.proposals.length || 0) > 0,
);

const resolveConfirmMessage = computed(() =>
  hasProposalOnSelectedThread.value
    ? t("doc_review.resolve_confirm_with_proposal")
    : t("doc_review.resolve_confirm_without_proposal"),
);

const aiActionText = computed(() =>
  isAiBusy.value
    ? `${aiStatusText.value}...`
    : !props.aiAvailable
      ? t("doc_review.ai_unavailable_label")
      : t("doc_review.ai_reply_action"),
);
const messageCountText = computed(() =>
  t("doc_review.member_message_count", {
    count: selectedThread.value?.messages.length || 0,
  }),
);
const proposalCountText = computed(() =>
  t("doc_review.proposal_count", {
    count: selectedThread.value?.proposals.length || 0,
  }),
);
const proposalPanelMeta = computed(() => {
  const status = selectedProposalJob.value?.status;
  if (!status) return proposalCountText.value;
  if (status === "PENDING") return t("doc_review.ai_status_pending");
  if (status === "RUNNING") return t("doc_review.ai_status_running");
  if (status === "WAITING_HITL") return t("doc_review.ai_status_waiting_hitl");
  if (status === "FAILED") return t("doc_review.ai_status_failed");
  if (status === "CANCELLED") return t("doc_review.ai_status_cancelled");
  if (status === "SUCCESS") return t("doc_review.ai_status_success");
  return proposalCountText.value;
});
const aiPanelMeta = computed(() =>
  selectedThreadJob.value?.status
    ? aiStatusText.value
    : t("doc_review.ai_status_idle"),
);
const aiUnavailableText = computed(() => {
  const reason = String(props.aiUnavailableReason || "").trim();
  if (!reason) return t("doc_review.ai_unavailable_label");
  return t(`doc_review.${reason}`);
});

const toggleThreadState = () => {
  if (!selectedThread.value) return;
  if (selectedThread.value.status === "open") {
    resolveConfirmVisible.value = true;
    return;
  }
  emit("update-state", selectedThread.value.id, "open");
};

const cancelResolveConfirm = () => {
  resolveConfirmVisible.value = false;
};

const confirmResolveThread = () => {
  if (!selectedThread.value || selectedThread.value.status !== "open") return;
  emit("update-state", selectedThread.value.id, "resolved");
  resolveConfirmVisible.value = false;
};

const closeThread = () => {
  if (!selectedThread.value || selectedThread.value.status === "closed") return;
  emit("update-state", selectedThread.value.id, "closed");
};

const markNoCloseNeeded = () => {
  if (!selectedThread.value) return;
  emit("close-hint-action", selectedThread.value.id, "mark_no_close_needed");
};

const resetCloseHintPending = () => {
  if (!selectedThread.value) return;
  emit("close-hint-action", selectedThread.value.id, "reset_pending");
};
</script>

<template>
  <aside class="thread-sidebar">
    <div v-show="!selectedThread" class="view-panel list-view">
      <header class="sidebar-head">
        <div>
          <h3>{{ t("doc_review.annotation_discussions") }}</h3>
          <p>{{ t("doc_review.thread_count", { count: threads.length }) }}</p>
        </div>
        <div class="presence">
          <span class="dot" :class="{ online: wsConnected }"></span>
          <span
            >{{ wsConnected ? t("doc_review.sync_live") : t("doc_review.sync_offline") }} ·
            {{ onlineUsers.length }}</span
          >
        </div>
      </header>

      <div class="thread-list custom-scrollbar">
        <button
          v-for="thread in sortedThreads"
          :key="thread.id"
          class="thread-item"
          :class="[
            { active: thread.id === selectedThreadId },
            `state-${thread.status}`,
          ]"
          :style="threadCardStyle(thread)"
          @click="emit('select-thread', thread.id)"
        >
          <div class="thread-item-head">
            <strong>#{{ thread.block_id }}</strong>
            <span
              class="status-pill"
              :class="`state-${thread.status}`"
              :style="threadPillStyle(thread)"
            >
              {{ statusLabel(thread.status) }}
            </span>
          </div>
          <p>{{ thread.selected_text || t("doc_review.no_selected_text") }}</p>
          <p
            v-if="shouldShowAnchorCloseHint(thread)"
            class="thread-hint"
          >
            {{
              thread.close_hint_state === "no_close_needed"
                ? t("doc_review.anchor_missing_no_close_needed")
                : t("doc_review.anchor_missing_title")
            }}
          </p>
          <small>{{ new Date(thread.created_at).toLocaleString() }}</small>
        </button>
      </div>
    </div>

    <div
      v-if="selectedThread"
      class="view-panel detail-view glass-panel slide-enter"
    >
      <header class="detail-head">
        <div class="detail-head-left">
          <button class="nav-back-button" @click="emit('select-thread', '')">
            <ArrowLeft class="w-4 h-4" />
            {{ t("doc_review.back_to_list") }}
          </button>
          <span class="block-anchor"
            >{{ t("doc_review.anchor_prefix") }}: {{ selectedThread.block_id }}</span
          >
        </div>
        <div class="detail-actions">
          <button
            v-if="canApplyResolution"
            class="nav-action-btn"
            @click="toggleThreadState"
          >
            {{
              selectedThread.status === "open"
                ? t("doc_review.mark_resolved")
                : t("doc_review.reopen_thread")
            }}
          </button>
          <button
            v-if="canApplyResolution && selectedThread.status !== 'closed'"
            class="nav-action-btn danger"
            @click="closeThread"
          >
            {{ t("doc_review.close_thread") }}
          </button>
        </div>
      </header>

      <div class="detail-scrollable custom-scrollbar">
        <section
          v-if="shouldShowAnchorCloseHint(selectedThread)"
          class="section-panel anchor-hint-panel"
          :class="{
            pending: selectedThread.close_hint_state === 'pending',
            acknowledged: selectedThread.close_hint_state === 'no_close_needed',
          }"
        >
          <header class="section-head">
            <h4 class="section-title">{{ t("doc_review.anchor_missing_title") }}</h4>
            <span class="section-meta">
              {{
                selectedThread.close_hint_state === "no_close_needed"
                  ? t("doc_review.anchor_missing_no_close_needed")
                  : t("doc_review.anchor_missing_pending")
              }}
            </span>
          </header>
          <p class="anchor-hint-text">
            {{
              selectedThread.close_hint_state === "no_close_needed"
                ? t("doc_review.anchor_missing_keep_open_hint")
                : t("doc_review.anchor_missing_action_hint")
            }}
          </p>
          <div class="anchor-hint-actions">
            <button
              v-if="selectedThread.close_hint_state !== 'no_close_needed'"
              class="btn-secondary small-btn"
              @click="markNoCloseNeeded"
            >
              {{ t("doc_review.anchor_mark_no_close_needed") }}
            </button>
            <button
              v-else
              class="btn-secondary small-btn"
              @click="resetCloseHintPending"
            >
              {{ t("doc_review.anchor_reset_pending") }}
            </button>
            <button
              v-if="canApplyResolution && selectedThread.status === 'open'"
              class="btn-secondary small-btn danger"
              @click="closeThread"
            >
              {{ t("doc_review.close_thread") }}
            </button>
          </div>
        </section>

        <section class="section-panel member-panel">
          <header class="section-head">
            <h4 class="section-title">
              {{ t("doc_review.member_conversation_title") }}
            </h4>
            <span class="section-meta">{{ messageCountText }}</span>
          </header>
          <ThreadTimeline :messages="selectedThread.messages" />

          <div class="composer">
            <textarea
              v-model="messageDraft"
              class="composer-textarea"
              :disabled="!canComment || !isSelectedThreadOpen"
              :placeholder="t('doc_review.reply_placeholder')"
            />
            <button
              class="btn-primary"
              :disabled="!canComment || !isSelectedThreadOpen || !messageDraft.trim()"
              @click="sendMessage"
            >
              {{ t("doc_review.send_reply") }}
            </button>
          </div>
        </section>

        <section class="section-panel ai-panel">
          <header class="section-head">
            <h4 class="section-title">{{ t("doc_review.ai_assistant") }}</h4>
            <span class="section-meta">{{ aiPanelMeta }}</span>
          </header>
          <div v-if="selectedThreadJob" class="ai-job-state">
            <strong>{{ aiStatusText }}</strong>
            <span v-if="selectedThreadJob.progress > 0"
              >{{ selectedThreadJob.progress }}%</span
            >
          </div>
          <p v-if="selectedThreadJob?.error_message" class="ai-job-error">
            {{ selectedThreadJob.error_message }}
          </p>
          <p v-if="!aiAvailable || !isSelectedThreadOpen" class="ai-job-hint">
            {{
              !isSelectedThreadOpen
                ? t("doc_review.thread_not_open_for_ai")
                : aiUnavailableText
            }}
          </p>
          <input
            v-model="aiPrompt"
            class="ai-input"
            :disabled="!canUseAiFeatures || isAiBusy"
            :placeholder="t('doc_review.ai_prompt_placeholder')"
          />
          <div class="ai-actions-row">
            <button
              class="btn-secondary ai-submit"
              :disabled="!canUseAiFeatures || isAiBusy"
              @click="askAi"
            >
              {{ aiActionText }}
            </button>
            <button
              v-if="canCancelAssistantJob"
              class="btn-secondary ai-submit ai-cancel-button"
              @click="cancelAssistantJob"
            >
              {{ t("doc_review.ai_cancel_action") }}
            </button>
          </div>
        </section>

        <section class="section-panel proposal-panel">
          <header class="section-head">
            <h4 class="section-title">
              {{ t("doc_review.proposal_section_title") }}
            </h4>
            <span class="section-meta">{{ proposalPanelMeta }}</span>
          </header>
          <p v-if="selectedProposalJob?.error_message" class="ai-job-error">
            {{ selectedProposalJob.error_message }}
          </p>
          <div class="ai-actions-row">
            <button
              class="btn-primary ai-submit"
              :disabled="!canUseAiFeatures || isProposalGenerating"
              @click="generateProposal"
            >
              {{
                isProposalGenerating
                  ? t("doc_review.proposal_generating")
                  : t("doc_review.proposal_generate")
              }}
            </button>
            <button
              v-if="canCancelProposalJob"
              class="btn-secondary ai-submit ai-cancel-button"
              @click="cancelProposalJob"
            >
              {{ t("doc_review.ai_cancel_action") }}
            </button>
          </div>

          <div v-if="selectedThread.proposals.length" class="proposal-list">
            <div
              v-for="proposal in selectedThread.proposals"
              :key="proposal.id"
              class="proposal-item"
            >
              <div>
                <strong>{{ proposalStatusLabel(proposal.status) }}</strong>
                <small>{{
                  new Date(proposal.created_at).toLocaleString()
                }}</small>
              </div>
              <div class="proposal-actions">
                <button
                  class="btn-secondary small-btn"
                  @click="emit('open-proposal', proposal.id)"
                >
                  {{ t("doc_review.proposal_open") }}
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>

    <div
      v-if="resolveConfirmVisible"
      class="confirm-overlay"
      :class="{ warning: !hasProposalOnSelectedThread }"
      @click.self="cancelResolveConfirm"
    >
      <div class="confirm-card glass-panel" :class="{ warning: !hasProposalOnSelectedThread }">
        <h4>{{ t("doc_review.resolve_confirm_title") }}</h4>
        <p>{{ resolveConfirmMessage }}</p>
        <div class="confirm-actions">
          <button class="btn-secondary" @click="cancelResolveConfirm">
            {{ t("common.cancel") }}
          </button>
          <button class="btn-primary" @click="confirmResolveThread">
            {{ t("doc_review.resolve_confirm_action") }}
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.thread-sidebar {
  position: relative;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.view-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.list-view {
  gap: 16px;
}

.detail-view {
  gap: 12px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: var(--radius-xl);
  border: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: var(--shadow-xl);
  backdrop-filter: blur(24px);
  padding: 1rem 0;
}

.detail-scrollable {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  padding: 0 1rem;
}

.slide-enter {
  animation: slideIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes slideIn {
  0% {
    opacity: 0;
    transform: translateX(20px) scale(0.98);
  }
  100% {
    opacity: 1;
    transform: translateX(0) scale(1);
  }
}

.sidebar-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
}

.sidebar-head h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-text-title);
  font-family: var(--font-heading);
}

.sidebar-head p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

.presence {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-text-muted);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #94a3b8;
}

.dot.online {
  background: #10b981;
}

.thread-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  padding: 8px 12px 24px 12px;
  margin: -8px -12px 0 -12px;
}

.thread-item {
  position: relative;
  z-index: 1;
  border: 1px solid rgba(255, 255, 255, 0.6);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  border-radius: var(--radius-lg);
  text-align: left;
  padding: 1rem;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: var(--shadow-sm);
}

.thread-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px -6px rgba(0, 0, 0, 0.12);
  cursor: pointer;
  z-index: 2;
}

.thread-item.state-open {
  border-color: var(--thread-open-border, rgba(194, 65, 12, 0.2));
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
  box-shadow: 0 10px 24px -8px var(--thread-open-border, rgba(194, 65, 12, 0.3));
}

.thread-item.state-open:hover {
  box-shadow: 
    0 16px 32px -6px var(--thread-open-border, rgba(194, 65, 12, 0.4)),
    0 4px 12px -2px var(--thread-open-border, rgba(194, 65, 12, 0.3));
}

.thread-item.state-closed {
  border-color: rgba(148, 163, 184, 0.32);
  background: rgba(248, 250, 252, 0.78);
}

.thread-item.active {
  border-color: rgba(14, 165, 233, 0.5);
  box-shadow:
    0 0 0 1.5px rgba(14, 165, 233, 0.3),
    0 12px 28px -6px rgba(14, 165, 233, 0.4);
  transform: translateY(-2px);
  z-index: 3;
}

.thread-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.thread-item p {
  margin: 10px 0;
  font-size: 13px;
  color: var(--color-text-body);
  line-height: 1.5;
}

.thread-hint {
  margin: 0 0 8px;
  padding: 4px 8px;
  border-radius: 8px;
  background: rgba(249, 115, 22, 0.12);
  color: #9a3412;
  font-size: 12px;
  font-weight: 600;
}

.thread-item small {
  color: var(--color-text-muted);
  font-size: 12px;
}

.status-pill {
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 11px;
  font-weight: 600;
}

.status-pill.state-open {
  background: rgba(255, 255, 255, 0.95);
  box-shadow: var(--thread-pill-shadow, 0 4px 12px rgba(194, 65, 12, 0.24));
  color: var(--thread-pill-color, #f97316);
  border: 1px solid var(--thread-pill-color, #f97316);
}

.status-pill.state-resolved {
  background: rgba(16, 185, 129, 0.16);
  color: #047857;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.24);
}

.status-pill.state-closed {
  background: rgba(100, 116, 139, 0.16);
  color: #475569;
  box-shadow: 0 4px 12px rgba(100, 116, 139, 0.2);
}

/* Detail View Layout */
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 1rem 0.5rem;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

.detail-head-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-back-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(241, 245, 249, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 999px;
  padding: 4px 12px 4px 8px;
  font-size: 13px;
  font-weight: 500;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s;
}

.nav-back-button:hover {
  background: #f8fafc;
  color: #0f172a;
  transform: translateX(-2px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.block-anchor {
  font-size: 13px;
  color: var(--color-text-muted);
  font-family: var(--font-mono, monospace);
  background: rgba(0, 0, 0, 0.04);
  padding: 2px 8px;
  border-radius: 4px;
}

.nav-action-btn {
  background: transparent;
  border: 1px solid rgba(14, 165, 233, 0.3);
  color: #0284c7;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.nav-action-btn:hover {
  background: rgba(14, 165, 233, 0.05);
  border-color: rgba(14, 165, 233, 0.6);
}

.nav-action-btn.danger {
  border-color: rgba(239, 68, 68, 0.35);
  color: #dc2626;
}

.nav-action-btn.danger:hover {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.58);
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
.h-4 {
  width: 1rem;
  height: 1rem;
}

.composer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.anchor-hint-panel {
  border: 1px solid rgba(14, 165, 233, 0.26);
  background: rgba(239, 246, 255, 0.82);
}

.anchor-hint-panel.pending {
  border-color: rgba(249, 115, 22, 0.42);
  background: rgba(255, 247, 237, 0.85);
}

.anchor-hint-panel.acknowledged {
  border-color: rgba(14, 116, 144, 0.35);
  background: rgba(236, 254, 255, 0.82);
}

.anchor-hint-text {
  margin: 0;
  font-size: 12px;
  color: #334155;
  line-height: 1.5;
}

.anchor-hint-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.ai-job-hint {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}

.composer-textarea {
  width: 100%;
  min-height: 80px;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(148, 163, 184, 0.3);
  padding: 10px;
  font: inherit;
  font-size: 13px;
  resize: vertical;
  background: rgba(255, 255, 255, 0.9);
  transition: border-color 0.2s;
}

.composer-textarea:focus {
  outline: none;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}

.composer-textarea:disabled,
.ai-input:disabled {
  background: rgba(226, 232, 240, 0.58);
  border-color: rgba(148, 163, 184, 0.45);
  color: #94a3b8;
  cursor: not-allowed;
}

.section-panel {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 1rem;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-left: 4px solid transparent;
  background: rgba(248, 250, 252, 0.7);
  box-shadow:
    inset 0 2px 4px rgba(255, 255, 255, 0.5),
    var(--shadow-sm);
  backdrop-filter: blur(8px);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.section-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: var(--color-text-title);
}

.section-meta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  border: 1px solid transparent;
}

.member-panel {
  border-color: rgba(14, 165, 233, 0.28);
  border-left-color: rgba(3, 105, 161, 0.65);
  background: linear-gradient(
    180deg,
    rgba(240, 249, 255, 0.76) 0%,
    rgba(248, 250, 252, 0.78) 100%
  );
}

.member-panel .section-title {
  color: #0369a1;
}

.member-panel .section-meta {
  color: #0c4a6e;
  background: rgba(14, 165, 233, 0.16);
  border-color: rgba(14, 165, 233, 0.3);
}

.member-panel :deep(.timeline) {
  max-height: 280px;
  margin: 0;
  padding: 10px;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(14, 165, 233, 0.16);
  background: rgba(255, 255, 255, 0.78);
}

.ai-panel {
  border-color: rgba(8, 145, 178, 0.26);
  border-left-color: rgba(14, 116, 144, 0.65);
  background: linear-gradient(
    180deg,
    rgba(236, 254, 255, 0.72) 0%,
    rgba(248, 250, 252, 0.78) 100%
  );
}

.ai-panel .section-title {
  color: #0e7490;
}

.ai-panel .section-meta {
  color: #155e75;
  background: rgba(6, 182, 212, 0.15);
  border-color: rgba(8, 145, 178, 0.28);
}

.proposal-panel {
  border-color: rgba(217, 119, 6, 0.28);
  border-left-color: rgba(180, 83, 9, 0.64);
  background: linear-gradient(
    180deg,
    rgba(255, 247, 237, 0.74) 0%,
    rgba(248, 250, 252, 0.78) 100%
  );
}

.proposal-panel .section-title {
  color: #b45309;
}

.proposal-panel .section-meta {
  color: #9a3412;
  background: rgba(245, 158, 11, 0.16);
  border-color: rgba(217, 119, 6, 0.32);
}

.ai-input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: var(--radius-lg);
  padding: 10px;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.9);
  transition: border-color 0.2s;
}

.ai-input:focus {
  outline: none;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}

.ai-submit {
  align-self: flex-end;
}

.ai-actions-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai-actions-row .ai-submit {
  flex: 1;
}

.ai-actions-row .ai-cancel-button {
  color: #dc2626;
}

.ai-actions-row .ai-cancel-button:hover {
  color: #b91c1c;
}

.composer .btn-primary:disabled,
.ai-actions-row .btn-primary:disabled,
.ai-actions-row .btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  text-shadow: none;
  box-shadow: none;
}

.composer .btn-primary:disabled {
  background: rgba(148, 163, 184, 0.86);
  color: rgba(255, 255, 255, 0.9);
}

.ai-actions-row .btn-secondary:disabled {
  background: rgba(241, 245, 249, 0.9);
  border-color: rgba(148, 163, 184, 0.38);
  color: #94a3b8;
}

.composer .btn-primary:disabled:hover,
.ai-actions-row .btn-primary:disabled:hover,
.ai-actions-row .btn-secondary:disabled:hover {
  transform: none;
  box-shadow: none;
  background-image: none;
}

.ai-job-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--color-text-muted);
}

.ai-job-state strong {
  color: #0284c7;
  font-weight: 600;
}

.ai-job-error {
  margin: 0;
  font-size: 13px;
  color: #b91c1c;
  background: rgba(254, 226, 226, 0.5);
  padding: 6px 10px;
  border-radius: 6px;
}

.proposal-list {
  display: grid;
  gap: 8px;
}

.proposal-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  border: 1px solid rgba(14, 165, 233, 0.2);
  border-radius: var(--radius-md);
  background: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.95) 0%,
    rgba(240, 249, 255, 0.6) 100%
  );
  padding: 0.75rem;
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(12px);
  transition: border-color 0.2s;
}

.proposal-item:hover {
  border-color: rgba(14, 165, 233, 0.5);
}

.proposal-item strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.proposal-item small {
  color: var(--color-text-muted);
  font-size: 11px;
}

.proposal-actions {
  display: inline-flex;
  gap: 8px;
}

.small-btn {
  padding: 4px 10px;
  font-size: 12px;
}

.confirm-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.3);
  backdrop-filter: blur(4px);
}

.confirm-overlay.warning {
  background: rgba(15, 23, 42, 0.3);
}

.confirm-card {
  width: min(420px, 100%);
  border-radius: var(--radius-xl);
  border: 1px solid rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.2);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.confirm-card.warning {
  border: 1px solid rgba(245, 158, 11, 0.62);
  background: rgba(255, 255, 255, 0.96);
  box-shadow:
    0 22px 54px rgba(120, 53, 15, 0.24),
    0 0 0 1px rgba(251, 191, 36, 0.32);
}

.confirm-card h4 {
  margin: 0;
  font-size: 15px;
  color: var(--color-text-title);
}

.confirm-card.warning h4 {
  color: #b45309;
}

.confirm-card p {
  margin: 0;
  color: var(--color-text-body);
  font-size: 13px;
  line-height: 1.6;
}

.confirm-card.warning p {
  color: #9a3412;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.confirm-card.warning .btn-primary {
  border-color: #d97706;
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  box-shadow: 0 10px 20px -10px rgba(217, 119, 6, 0.72);
}

.confirm-card.warning .btn-primary:hover {
  box-shadow: 0 12px 24px -10px rgba(180, 83, 9, 0.84);
}
</style>
