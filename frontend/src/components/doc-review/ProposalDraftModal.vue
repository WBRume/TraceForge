<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";
import BaseSelect from "@/components/BaseSelect.vue";
import {
  ChatBubbleLeftRightIcon,
  CheckIcon,
  ChevronDownIcon,
  MagnifyingGlassIcon,
  SparklesIcon,
  XMarkIcon,
} from "@/components/icons";

type ProposalPatch = {
  proposal_text?: string;
  new_text?: string;
  display_new_text?: string;
  source_message_ids?: string[];
  source_thread_ids?: string[];
  rewrite_scope?: "anchor" | "document";
};

type Proposal = {
  id: string;
  status: "draft" | "applied" | "discarded";
  proposed_patch_json?: ProposalPatch;
};

type SourceMessage = {
  id: string;
  role: "user" | "ai" | "system";
  content: string;
  creator?: string;
  createdAt?: string;
};

type SourceOption = {
  id: string;
  quote: string;
  version: string;
  blockId?: string;
  creator?: string;
  messageCount?: number;
  charStart?: number | null;
  charEnd?: number | null;
  anchorStatus?: "valid" | "missing";
  messages?: SourceMessage[];
};

const props = defineProps<{
  visible: boolean;
  proposal: Proposal | null;
  submitting?: boolean;
  canRewrite?: boolean;
  rewriteDisabledReason?: string | null;
  selectingSources?: boolean;
  sourceOptions?: SourceOption[];
}>();

const emit = defineEmits<{
  close: [];
  "generate": [threadIds: string[]];
  rewrite: [
    proposalId: string,
    proposalText: string,
    rewriteScope: "anchor" | "document",
  ];
}>();

const { t } = useI18n();
const titleId = useId();
const modalRef = ref<HTMLElement | null>(null);
const checkedSources = ref<string[]>([]);
const searchQuery = ref("");

const selection = computed(() => (props.sourceOptions || [])
  .filter(source => checkedSources.value.includes(source.id)).map(source => source.id));

const filteredSources = computed(() => {
  const list = props.sourceOptions || [];
  const query = searchQuery.value.trim().toLowerCase();
  if (!query) return list;
  return list.filter(source =>
    source.quote.toLowerCase().includes(query) ||
    source.version.toLowerCase().includes(query) ||
    (source.blockId || "").toLowerCase().includes(query) ||
    (source.creator || "").toLowerCase().includes(query) ||
    (source.messages || []).some(message => message.content.toLowerCase().includes(query)),
  );
});

const allFilteredSelected = computed(
  () =>
    filteredSources.value.length > 0 &&
    filteredSources.value.every(source => checkedSources.value.includes(source.id)),
);

// 相同框选文本可能来自多个讨论：统计重复次数，提示用户按定位信息区分
const quoteOccurrences = computed(() => {
  const counts = new Map<string, number>();
  for (const source of props.sourceOptions || []) {
    const key = source.quote.trim();
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
});

const sameQuoteCount = (source: SourceOption) =>
  quoteOccurrences.value.get(source.quote.trim()) || 0;

const expandedSources = ref<string[]>([]);
const isSourceExpanded = (id: string) => expandedSources.value.includes(id);
const toggleSourceDetail = (id: string) => {
  expandedSources.value = isSourceExpanded(id)
    ? expandedSources.value.filter(item => item !== id)
    : [...expandedSources.value, id];
};

const sourceCharRange = (source: SourceOption) => {
  const start = typeof source.charStart === "number" ? source.charStart : null;
  const end = typeof source.charEnd === "number" ? source.charEnd : null;
  if (start === null || end === null) return "";
  return t("doc_review.proposal_source_char_range", { start, end });
};

const formatSourceTime = (value?: string) => {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
};

const sourceRoleLabel = (role: SourceMessage["role"]) => {
  if (role === "ai") return "AI";
  if (role === "system") return t("doc_review.role_system");
  return t("doc_review.role_member");
};

// 相同文本时，读屏也需要能区分讨论，因此把锚点/发起人/位置并入 aria-label
const sourceAriaLabel = (source: SourceOption) => {
  const details = [
    source.blockId ? `#${source.blockId}` : "",
    source.creator || "",
    sourceCharRange(source),
  ].filter(Boolean);
  const base = t("doc_review.proposal_select_thread", { quote: source.quote });
  return details.length ? `${base} · ${details.join(" · ")}` : base;
};

const toggleAll = () => {
  const filteredIds = filteredSources.value.map(source => source.id);
  if (allFilteredSelected.value) {
    const removing = new Set(filteredIds);
    checkedSources.value = checkedSources.value.filter(id => !removing.has(id));
    return;
  }
  checkedSources.value = [...new Set([...checkedSources.value, ...filteredIds])];
};

watch(() => props.selectingSources, selecting => {
  if (selecting) {
    checkedSources.value = [];
    searchQuery.value = "";
    expandedSources.value = [];
  }
});

const proposalDraft = ref("");
const rewriteScope = ref<"anchor" | "document">("anchor");
const isJoint = computed(() => !!props.proposal?.proposed_patch_json?.source_thread_ids?.length);
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
    rewriteScope.value = isJoint.value || scope === "document" ? "document" : "anchor";
  },
  { immediate: true, deep: true },
);

const canRewriteNow = computed(() =>
  props.canRewrite !== false &&
  props.proposal?.status === "draft" &&
  !!proposalDraft.value.trim() &&
  !props.submitting,
);

const proposalMetaText = computed(() => {
  const patch = props.proposal?.proposed_patch_json;
  if (!patch) return "";
  const sourceCount = Array.isArray(patch.source_message_ids)
    ? patch.source_message_ids.length
    : 0;
  return t("doc_review.proposal_editor_meta", { source: sourceCount });
});

const generateDisabledReason = computed(() => {
  if (props.canRewrite === false) {
    return props.rewriteDisabledReason || t("doc_review.ai_unavailable_label");
  }
  return "";
});

const doRewrite = () => {
  if (!props.proposal) return;
  const text = proposalDraft.value.trim();
  if (!text) return;
  emit("rewrite", props.proposal.id, text, isJoint.value ? "document" : rewriteScope.value);
};

const focusableElements = () => [
  ...(modalRef.value?.querySelectorAll<HTMLElement>(
    'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
  ) || []),
].filter(element => element.offsetParent !== null);

const onKeydown = (event: KeyboardEvent) => {
  if (!props.visible) return;
  if (event.key === "Escape") {
    // 上层仍有确认弹窗时，Escape 交给上层处理
    if (document.querySelectorAll(".modal-overlay").length > 1) return;
    event.preventDefault();
    emit("close");
    return;
  }
  if (event.key !== "Tab" || !modalRef.value) return;
  const items = focusableElements();
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && (document.activeElement === first || document.activeElement === modalRef.value)) {
    event.preventDefault();
    last.focus();
    return;
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
};

watch(
  () => props.visible,
  async visible => {
    if (!visible) {
      window.removeEventListener("keydown", onKeydown);
      searchQuery.value = "";
      return;
    }
    window.addEventListener("keydown", onKeydown);
    await nextTick();
    // 打开后先聚焦弹窗容器，保证 Esc / Tab 键盘操作立即可用
    modalRef.value?.focus({ preventScroll: true });
  },
  { immediate: true },
);

onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="emit('close')">
    <div
      ref="modalRef"
      class="modal-card"
      :class="{ 'is-picker': selectingSources }"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      tabindex="-1"
    >
      <header class="modal-head">
        <span class="head-icon" aria-hidden="true">
          <ChatBubbleLeftRightIcon v-if="selectingSources" />
          <SparklesIcon v-else />
        </span>
        <div class="title-wrap">
          <h3 :id="titleId">{{ t(selectingSources ? "doc_review.revision_generate" : "doc_review.proposal_modal_title") }}</h3>
          <p>{{ t(selectingSources ? "doc_review.proposal_select_resolved" : "doc_review.proposal_modal_subtitle") }}</p>
        </div>
        <button type="button" class="close-btn" :disabled="submitting" :aria-label="t('doc_review.proposal_modal_close')" @click="emit('close')">
          <XMarkIcon />
        </button>
      </header>

      <section v-if="selectingSources" class="proposal-picker">
        <div v-if="sourceOptions?.length" class="picker-toolbar">
          <label v-if="sourceOptions.length > 4" class="picker-search">
            <MagnifyingGlassIcon aria-hidden="true" />
            <input
              v-model="searchQuery"
              type="search"
              :placeholder="t('doc_review.proposal_search_placeholder')"
            />
          </label>
          <span v-else class="picker-total">
            {{ t("doc_review.proposal_resolved_count", { count: sourceOptions.length }) }}
          </span>
          <button type="button" class="link-btn" @click="toggleAll">
            {{ allFilteredSelected
              ? t("doc_review.proposal_clear_selection")
              : t("doc_review.proposal_select_all") }}
          </button>
        </div>

        <div v-if="!sourceOptions?.length" class="picker-empty">
          <span class="picker-empty-icon" aria-hidden="true">
            <ChatBubbleLeftRightIcon />
          </span>
          <strong>{{ t("doc_review.proposal_no_resolved_threads") }}</strong>
          <p>{{ t("doc_review.proposal_no_resolved_threads_hint") }}</p>
        </div>
        <div v-else class="picker-list">
          <div
            v-for="source in filteredSources"
            :key="source.id"
            class="picker-item"
            :class="{ selected: checkedSources.includes(source.id), expanded: isSourceExpanded(source.id) }"
          >
            <label class="picker-main">
              <input
                v-model="checkedSources"
                class="picker-input"
                type="checkbox"
                :value="source.id"
                :aria-label="sourceAriaLabel(source)"
              />
              <span class="picker-check" aria-hidden="true">
                <CheckIcon />
              </span>
              <span class="picker-content">
                <span class="picker-quote">{{ source.quote }}</span>
                <span class="picker-meta">
                  <span v-if="source.blockId" class="picker-block">#{{ source.blockId }}</span>
                  <span v-if="source.creator" class="picker-author">{{ source.creator }}</span>
                  <span v-if="source.messageCount">
                    {{ t("doc_review.proposal_source_message_count", { count: source.messageCount }) }}
                  </span>
                  <span v-if="sourceCharRange(source)" class="picker-range">{{ sourceCharRange(source) }}</span>
                  <span v-if="sameQuoteCount(source) > 1" class="picker-dup">
                    {{ t("doc_review.proposal_same_quote_count", { count: sameQuoteCount(source) }) }}
                  </span>
                  <span v-if="source.anchorStatus === 'missing'" class="picker-missing">
                    {{ t("doc_review.proposal_source_anchor_missing") }}
                  </span>
                </span>
              </span>
              <span v-if="source.version" class="picker-version">{{ source.version }}</span>
            </label>
            <button
              v-if="source.messages?.length"
              type="button"
              class="picker-toggle"
              :class="{ open: isSourceExpanded(source.id) }"
              :aria-expanded="isSourceExpanded(source.id)"
              :aria-label="t(isSourceExpanded(source.id) ? 'doc_review.proposal_hide_discussion' : 'doc_review.proposal_view_discussion')"
              @click.stop="toggleSourceDetail(source.id)"
            >
              <ChevronDownIcon aria-hidden="true" />
            </button>

            <div v-if="isSourceExpanded(source.id)" class="picker-thread">
              <div
                v-for="message in source.messages"
                :key="message.id"
                class="picker-message"
                :class="`role-${message.role}`"
              >
                <div class="picker-message-head">
                  <strong>{{ sourceRoleLabel(message.role) }}</strong>
                  <span v-if="message.creator">· {{ message.creator }}</span>
                  <time v-if="formatSourceTime(message.createdAt)">{{ formatSourceTime(message.createdAt) }}</time>
                </div>
                <p>{{ message.content }}</p>
              </div>
            </div>
          </div>

          <div v-if="!filteredSources.length" class="picker-no-match">
            <p>{{ t("doc_review.proposal_no_match") }}</p>
            <button type="button" class="link-btn" @click="searchQuery = ''">
              {{ t("doc_review.proposal_clear_search") }}
            </button>
          </div>
        </div>
      </section>

      <template v-else-if="proposal">
        <p v-if="proposalMetaText" class="proposal-meta">{{ proposalMetaText }}</p>
        <section class="proposal-editor-panel">
          <header class="proposal-editor-head">
            <strong>{{ t("doc_review.proposal_editor_title") }}</strong>
          </header>
          <div class="rewrite-scope-row">
            <span class="rewrite-scope-label">{{
              t("doc_review.proposal_rewrite_scope_label")
            }}</span>
            <strong v-if="isJoint" class="rewrite-scope-label">{{ t("doc_review.proposal_rewrite_scope_document") }}</strong>
            <BaseSelect
              v-else
              v-model="rewriteScope"
              :options="rewriteScopeOptions"
              size="sm"
              :disabled="submitting"
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
            :disabled="submitting || props.canRewrite === false"
          />
        </section>
      </template>

      <footer class="modal-actions">
        <div class="actions-status" aria-live="polite">
          <template v-if="selectingSources && selection.length">
            <span class="status-dot" aria-hidden="true" />
            {{ t("doc_review.proposal_selection_summary", { count: selection.length }) }}
          </template>
        </div>
        <div class="actions-buttons">
          <button class="btn-secondary" :disabled="submitting" @click="emit('close')">
            {{ t("doc_review.proposal_modal_close") }}
          </button>
          <button
            v-if="selectingSources"
            class="btn-primary"
            :disabled="!selection.length || canRewrite === false || submitting"
            :title="generateDisabledReason"
            @click="emit('generate', selection)"
          >
            <SparklesIcon aria-hidden="true" />
            {{ t(submitting ? "doc_review.proposal_generating" : "doc_review.revision_generate") }}
          </button>
          <button v-else-if="proposal" class="btn-primary" :disabled="!canRewriteNow" @click="doRewrite">
            {{ t(submitting ? "doc_review.proposal_generating" : "doc_review.revision_generate") }}
          </button>
        </div>
      </footer>
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
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(8px);
  animation: overlay-in 0.16s ease-out;
}

@keyframes overlay-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-card {
  width: min(1240px, 100%);
  max-height: min(92vh, 920px);
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem;
  border-radius: var(--radius-xl);
  background: #fff;
  box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.28);
  border: 1px solid rgba(226, 232, 240, 0.9);
  outline: none;
  animation: card-in 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes card-in {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .modal-overlay,
  .modal-card {
    animation: none;
  }
}

/* 选择来源时内容较少，使用更聚焦的宽度，避免大留白 */
.modal-card.is-picker {
  width: min(720px, 100%);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.head-icon {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.7rem;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.head-icon svg {
  width: 1.15rem;
  height: 1.15rem;
}

.title-wrap {
  flex: 1;
  min-width: 0;
}

.title-wrap h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text-title);
}

.title-wrap p {
  margin: 0.2rem 0 0;
  font-size: 0.78rem;
  line-height: 1.5;
  color: var(--color-text-muted);
}

.close-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.close-btn svg {
  width: 1.1rem;
  height: 1.1rem;
}

.close-btn:hover {
  background: #f1f5f9;
  color: var(--color-text-title);
}

.close-btn:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}

/* ---------- 来源多选 ---------- */

.proposal-picker {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 0;
}

.picker-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.picker-search {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.7rem;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-md);
  background: #f8fafc;
  color: var(--color-text-muted);
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}

.picker-search:focus-within {
  border-color: var(--color-primary-500);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.picker-search svg {
  flex-shrink: 0;
  width: 1rem;
  height: 1rem;
}

.picker-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 0.83rem;
  color: var(--color-text-body);
}

.picker-search input::placeholder {
  color: #94a3b8;
}

.picker-total {
  flex: 1;
  font-size: 0.8rem;
  color: var(--color-text-muted);
}

.link-btn {
  flex-shrink: 0;
  padding: 0.3rem 0.55rem;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-primary-600);
  font: inherit;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.link-btn:hover {
  background: var(--color-primary-50);
}

.link-btn:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.picker-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: min(48vh, 24rem);
  padding: 0.15rem;
  margin: -0.15rem;
  overflow-y: auto;
  scrollbar-width: thin;
}

.picker-list::-webkit-scrollbar {
  width: 8px;
}

.picker-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #cbd5e1;
}

.picker-list::-webkit-scrollbar-track {
  background: transparent;
}

.picker-item {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.7rem 0.8rem;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-lg);
  background: #fff;
  color: var(--color-text-body);
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}

.picker-item:hover {
  border-color: #bae6fd;
  background: #f8fcff;
}

.picker-item:focus-within {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.14);
}

.picker-item.selected {
  border-color: var(--color-primary-500);
  background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
}

.picker-item.selected:hover {
  background: linear-gradient(135deg, #e0f2fe, #bae6fd);
}

.picker-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  cursor: pointer;
}

/* 视觉隐藏但保持可聚焦的无障碍复选框 */
.picker-input {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

.picker-check {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.15rem;
  height: 1.15rem;
  margin-top: 0.1rem;
  border: 1.5px solid #cbd5e1;
  border-radius: 0.35rem;
  background: #fff;
  color: transparent;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.picker-check svg {
  width: 0.8rem;
  height: 0.8rem;
  stroke-width: 3;
}

.picker-item.selected .picker-check {
  border-color: var(--color-primary-500);
  background: var(--color-primary-500);
  color: #fff;
}

.picker-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.picker-quote {
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
  font-size: 0.84rem;
  font-weight: 500;
  line-height: 1.55;
  color: var(--color-text-body);
}

.picker-item.selected .picker-quote {
  color: var(--color-primary-900);
}

.picker-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.7rem;
  line-height: 1.5;
  color: var(--color-text-muted);
}

.picker-meta > span + span::before {
  content: "·";
  margin-right: 0.35rem;
  color: #cbd5e1;
}

.picker-meta .picker-dup::before,
.picker-meta .picker-missing::before {
  content: none;
  margin: 0;
}

.picker-block {
  font-family: "Consolas", "Courier New", monospace;
  color: #475569;
}

.picker-dup,
.picker-missing {
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-full);
  background: #fef3c7;
  color: #92400e;
  font-weight: 600;
}

.picker-missing {
  background: #fee2e2;
  color: #b91c1c;
}

.picker-version {
  flex-shrink: 0;
  align-self: flex-start;
  padding: 0.12rem 0.5rem;
  border-radius: var(--radius-full);
  background: #f1f5f9;
  color: var(--color-text-muted);
  font-size: 0.7rem;
  line-height: 1.5;
  white-space: nowrap;
}

.picker-item.selected .picker-version {
  background: rgba(255, 255, 255, 0.75);
  color: var(--color-primary-700);
}

.picker-toggle {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.picker-toggle svg {
  width: 1rem;
  height: 1rem;
  transition: transform 0.18s ease;
}

.picker-toggle.open svg {
  transform: rotate(180deg);
}

.picker-toggle:hover {
  background: rgba(148, 163, 184, 0.16);
  color: var(--color-text-title);
}

.picker-toggle:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.picker-thread {
  flex-basis: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  margin-top: 0.15rem;
  padding-top: 0.6rem;
  padding-left: 1.8rem;
  border-top: 1px dashed #dbe3ec;
  max-height: 16rem;
  overflow-y: auto;
  scrollbar-width: thin;
}

.picker-message {
  padding: 0.45rem 0.6rem;
  border-radius: var(--radius-md);
  background: rgba(248, 250, 252, 0.9);
  border-left: 2px solid #cbd5e1;
}

.picker-message.role-ai {
  background: rgba(240, 249, 255, 0.9);
  border-left-color: #7dd3fc;
}

.picker-message.role-system {
  background: #f8fafc;
  border-left-color: #94a3b8;
}

.picker-message-head {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
  font-size: 0.7rem;
  color: var(--color-text-muted);
}

.picker-message-head strong {
  color: var(--color-text-title);
  font-weight: 600;
}

.picker-message-head time {
  margin-left: auto;
  font-size: 0.66rem;
  white-space: nowrap;
}

.picker-message p {
  margin: 0.2rem 0 0;
  font-size: 0.76rem;
  line-height: 1.65;
  color: var(--color-text-body);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.picker-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  min-height: 12rem;
  padding: 1.5rem;
  border: 1px dashed #dbe3ec;
  border-radius: var(--radius-lg);
  background: #fbfdff;
  text-align: center;
}

.picker-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  margin-bottom: 0.25rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #94a3b8;
}

.picker-empty-icon svg {
  width: 1.35rem;
  height: 1.35rem;
}

.picker-empty strong {
  font-size: 0.88rem;
  color: var(--color-text-title);
}

.picker-empty p {
  margin: 0;
  max-width: 22rem;
  font-size: 0.78rem;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.picker-no-match {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 1.75rem 1rem;
  text-align: center;
}

.picker-no-match p {
  margin: 0;
  font-size: 0.82rem;
  color: var(--color-text-muted);
}

/* ---------- 提案编辑 / 生成等待 ---------- */

.proposal-meta {
  margin: 0;
  font-size: 0.75rem;
  color: var(--color-text-muted);
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

/* ---------- 底部操作区 ---------- */

.modal-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding-top: 0.25rem;
}

.actions-status {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: var(--color-text-muted);
}

.status-dot {
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 999px;
  background: var(--color-primary-500);
}

.actions-buttons {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
}

.actions-buttons :deep(svg) {
  width: 1rem;
  height: 1rem;
}
</style>
