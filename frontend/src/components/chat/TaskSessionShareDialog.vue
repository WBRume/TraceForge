<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Copy, Link2, Loader2, Share2, Trash2, X } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import type { CreatedShare, SessionShareItem } from '@/composables/useTaskSessionShares'

/**
 * 分享会话弹窗：模式（只读 / 邀请输入）、有效期、邀请说明、生成链接。
 * 链接列表与成员管理·链接邀请（SettingsMembersAddModal）同款：每条链接
 * 展示完整 URL，随时可复制、可撤销。
 */
const props = defineProps<{
  show: boolean
  taskId: string
  taskName: string
  shares: SessionShareItem[]
  loading: boolean
  creating: boolean
  revokingIds: Set<string>
  canShare: boolean
  /** 创建成功后由父级回填的最近一次结果（高亮新建行） */
  justCreated: CreatedShare | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'create', payload: { mode: 'READ' | 'INPUT'; expires_in_days: number; instruction_text?: string }): void
  (e: 'revoke', shareId: string): void
}>()

const { t } = useI18n()

const mode = ref<'READ' | 'INPUT'>('READ')
const expiresInDays = ref(7)
const instructionText = ref('')
const copiedToken = ref('')

const modeOptions = computed(() => [
  { value: 'READ', label: t('share.mode_read') },
  { value: 'INPUT', label: t('share.mode_input') },
])

const expiryOptions = computed(() => [
  { value: 1, label: t('share.expiry_days', { n: 1 }) },
  { value: 7, label: t('share.expiry_days', { n: 7 }) },
  { value: 30, label: t('share.expiry_days', { n: 30 }) },
])

watch(() => props.show, (open) => {
  if (open) {
    copiedToken.value = ''
    instructionText.value = ''
  }
})

const statusText = (share: SessionShareItem): string => t(`share.status_${share.status.toLowerCase()}`)

const formatTime = (value: string): string => new Date(value).toLocaleString()

const absoluteUrl = (shareUrl: string): string => `${window.location.origin}${shareUrl}`

/** 列表行展示的完整 URL（明文 token 由后端返回） */
const shareItemUrl = (item: SessionShareItem): string | null => (
  item.share_url ? absoluteUrl(item.share_url) : null
)

const handleCreate = () => {
  emit('create', {
    mode: mode.value,
    expires_in_days: expiresInDays.value,
    instruction_text: mode.value === 'INPUT' ? instructionText.value.trim() || undefined : undefined,
  })
}

const copyLink = async (url: string, key: string) => {
  try {
    await navigator.clipboard.writeText(url)
    copiedToken.value = key
    window.setTimeout(() => {
      if (copiedToken.value === key) copiedToken.value = ''
    }, 2000)
  } catch {
    /* 剪贴板不可用时静默 */
  }
}

const close = () => {
  if (props.creating) return
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <transition name="share-dialog-fade">
      <div v-if="show" class="share-dialog-backdrop" @pointerdown.self="close">
        <div class="share-dialog">
          <header class="share-dialog-header">
            <div class="share-dialog-title">
              <Share2 class="title-icon" />
              <span>{{ $t('share.dialog_title') }}</span>
            </div>
            <button type="button" class="share-dialog-close" :title="$t('common.close')" @click="close">
              <X class="close-icon" />
            </button>
          </header>

          <div class="share-dialog-body">
            <p class="share-task-name">{{ taskName }}</p>

            <template v-if="canShare">
              <!-- 创建表单（与成员管理·链接邀请的 link-create-card 同款） -->
              <section class="share-form">
                <div class="share-form-row">
                  <label class="share-form-label">{{ $t('share.mode_label') }}</label>
                  <BaseSelect
                    v-model="mode"
                    :options="modeOptions"
                    size="sm"
                    class="share-form-select"
                  />
                </div>
                <p class="share-form-hint">
                  {{ mode === 'READ' ? $t('share.mode_read_hint') : $t('share.mode_input_hint') }}
                </p>

                <div class="share-form-row">
                  <label class="share-form-label">{{ $t('share.expiry_label') }}</label>
                  <BaseSelect
                    v-model="expiresInDays"
                    :options="expiryOptions"
                    size="sm"
                    class="share-form-select"
                  />
                </div>

                <div v-if="mode === 'INPUT'" class="share-form-row share-form-row-col">
                  <label class="share-form-label">{{ $t('share.instruction_label') }}</label>
                  <textarea
                    v-model="instructionText"
                    class="share-instruction-input"
                    rows="3"
                    maxlength="2000"
                    :placeholder="$t('share.instruction_placeholder')"
                  ></textarea>
                </div>

                <div class="share-form-warning">
                  {{ $t('share.forward_warning') }}
                </div>

                <div class="share-form-foot">
                  <button
                    type="button"
                    class="share-create-btn"
                    :disabled="creating"
                    @click="handleCreate"
                  >
                    <Loader2 v-if="creating" class="btn-icon spin" />
                    <Link2 v-else class="btn-icon" />
                    {{ creating ? $t('share.creating_button') : $t('share.create_button') }}
                  </button>
                </div>
              </section>
            </template>

            <p v-else class="share-no-permission">{{ $t('share.no_permission_hint') }}</p>

            <!-- 链接列表：与成员管理·链接邀请同款（URL 回显 + 复制 + 撤销） -->
            <section class="share-list-section">
              <h4 class="share-list-title">
                {{ $t('share.existing_links_title') }}
                <span v-if="shares.length">（{{ shares.length }}）</span>
                <Loader2 v-if="loading" class="title-icon spin" />
              </h4>

              <div v-if="loading" class="share-list-loading">
                <Loader2 class="title-icon spin" />
              </div>
              <p v-else-if="shares.length === 0" class="share-list-empty">
                {{ $t('share.existing_links_empty') }}
              </p>
              <div v-else class="share-list">
                <div
                  v-for="item in shares"
                  :key="item.id"
                  class="share-list-item"
                  :class="{ 'is-just-created': justCreated && justCreated.id === item.id }"
                >
                  <div class="share-list-main">
                    <span class="share-list-mode" :class="item.mode.toLowerCase()">
                      {{ item.mode === 'READ' ? $t('share.mode_read') : $t('share.mode_input') }}
                    </span>
                    <span class="share-list-status" :class="`is-${item.status.toLowerCase()}`">{{ statusText(item) }}</span>
                    <span class="share-list-meta">{{ $t('share.list_expires', { date: formatTime(item.expires_at) }) }}</span>
                  </div>
                  <div v-if="item.instruction_text" class="share-list-instruction">“{{ item.instruction_text }}”</div>
                  <div
                    v-if="shareItemUrl(item)"
                    class="share-list-url"
                    :title="shareItemUrl(item)!"
                  >
                    {{ shareItemUrl(item) }}
                  </div>
                  <div class="share-list-foot">
                    <span v-if="item.session_generation" class="share-list-meta">
                      {{ $t('share.list_generation', { n: item.session_generation }) }}
                    </span>
                    <div class="share-list-acts">
                      <button
                        v-if="shareItemUrl(item)"
                        type="button"
                        class="share-copy-btn"
                        @click="copyLink(shareItemUrl(item)!, item.id)"
                      >
                        <Check v-if="copiedToken === item.id" class="btn-icon" />
                        <Copy v-else class="btn-icon" />
                        {{ copiedToken === item.id ? $t('share.copied') : $t('share.copy_link') }}
                      </button>
                      <button
                        v-if="item.status === 'ACTIVE'"
                        type="button"
                        class="share-revoke-btn"
                        :disabled="revokingIds.has(item.id)"
                        @click="emit('revoke', item.id)"
                      >
                        <Loader2 v-if="revokingIds.has(item.id)" class="btn-icon spin" />
                        <Trash2 v-else class="btn-icon" />
                        {{ $t('share.revoke_button') }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.share-dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}

/* 与成员管理 member-modal 同规格 */
.share-dialog {
  width: 100%;
  max-width: 620px;
  max-height: 86vh;
  overflow: auto;
  background: #ffffff;
  border-radius: 18px;
  box-shadow: 0 30px 60px -18px rgba(15, 23, 42, 0.45);
  display: flex;
  flex-direction: column;
}

.share-dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.15rem 1.35rem 0.85rem;
  border-bottom: 1px solid #f1f5f9;
}

.share-dialog-title {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}

.title-icon {
  width: 18px;
  height: 18px;
  color: var(--color-primary-600, #0284c7);
  flex-shrink: 0;
}

.share-dialog-close {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.05);
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.share-dialog-close:hover {
  background: rgba(15, 23, 42, 0.08);
  color: #0f172a;
}

.close-icon {
  width: 16px;
  height: 16px;
}

.share-dialog-body {
  padding: 1.1rem 1.35rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.share-task-name {
  margin: 0;
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 600;
}

/* ── 创建表单：link-create-card 同款 ── */
.share-form {
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: #f8fbff;
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.share-form-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.share-form-row-col {
  flex-direction: column;
  align-items: stretch;
  gap: 0.4rem;
}

.share-form-label {
  width: 72px;
  flex-shrink: 0;
  font-size: 0.76rem;
  font-weight: 700;
  color: #334155;
}

.share-form-select {
  flex: 1;
  max-width: 240px;
}

.share-form-hint {
  margin: 0;
  font-size: 0.74rem;
  color: #94a3b8;
  line-height: 1.4;
}

.share-instruction-input {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.5rem 0.7rem;
  font-size: 0.8rem;
  font-family: inherit;
  color: #0f172a;
  background: #ffffff;
  resize: vertical;
  outline: none;
}

.share-instruction-input:focus {
  border-color: var(--color-primary-500, #0ea5e9);
}

.share-form-warning {
  font-size: 0.72rem;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: 8px;
  padding: 0.45rem 0.7rem;
  line-height: 1.4;
}

.share-form-foot {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

/* 与 link-create-foot .btn-primary 同款 */
.share-create-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  padding: 0.45rem 0.95rem;
  border-radius: 10px;
  font-size: 0.8rem;
  font-weight: 600;
  background: var(--color-primary-500, #0ea5e9);
  color: #ffffff;
  border: 1px solid transparent;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.25);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.share-create-btn:hover:not(:disabled) {
  background: var(--color-primary-600, #0284c7);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(14, 165, 233, 0.35);
}

.share-create-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.share-no-permission {
  margin: 0;
  font-size: 0.8rem;
  color: #94a3b8;
}

/* ── 链接列表：link-list 同款 ── */
.share-list-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.share-list-title {
  margin: 0;
  font-size: 0.76rem;
  font-weight: 700;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.share-list-loading {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.share-list-empty {
  margin: 0;
  border: 1px dashed #dbeafe;
  border-radius: 12px;
  background: #f8fbff;
  color: #94a3b8;
  font-size: 0.8rem;
  padding: 1rem;
  text-align: center;
}

.share-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: 260px;
  overflow: auto;
}

.share-list-item {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 0.65rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  background: #ffffff;
}

.share-list-item.is-just-created {
  border-color: #86efac;
  box-shadow: 0 0 0 3px rgba(134, 239, 172, 0.18);
}

.share-list-main {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.share-list-mode {
  font-size: 0.7rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.12rem 0.5rem;
}

.share-list-mode.read {
  background: #e0f2fe;
  color: #0369a1;
}

.share-list-mode.input {
  background: #fef3c7;
  color: #92400e;
}

.share-list-status {
  font-size: 0.7rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.12rem 0.5rem;
}

.share-list-status.is-active {
  background: #dcfce7;
  color: #166534;
}

.share-list-status.is-expired {
  background: #fef3c7;
  color: #92400e;
}

.share-list-status.is-revoked,
.share-list-status.is-session_invalid {
  background: #fff1f2;
  color: #be123c;
}

.share-list-meta {
  font-size: 0.72rem;
  color: #94a3b8;
}

.share-list-instruction {
  font-size: 0.74rem;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* link-item-url 同款 */
.share-list-url {
  font-family: 'Consolas', ui-monospace, monospace;
  font-size: 0.74rem;
  color: #0369a1;
  background: #f8fbff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.35rem 0.55rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.share-list-foot {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.share-list-acts {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

/* permission-toggle-btn 同款（胶囊复制） */
.share-copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.28rem;
  padding: 0.34rem 0.68rem;
  font-size: 0.74rem;
  line-height: 1.2;
  border-radius: 9px;
  border: 1px solid #dbeafe;
  background: #f8fbff;
  color: #0369a1;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s ease;
}

.share-copy-btn:hover {
  background: #f8fafc;
  border-color: #7dd3fc;
}

/* btn-compact-danger 同款（紧凑红色撤销） */
.share-revoke-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.28rem;
  padding: 0.34rem 0.68rem;
  font-size: 0.74rem;
  line-height: 1.2;
  border-radius: 9px;
  border: 1px solid #fecaca;
  background: #fff1f2;
  color: #be123c;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s ease;
}

.share-revoke-btn:hover:not(:disabled) {
  background: #ffe4e6;
  border-color: #fda4af;
}

.share-revoke-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.share-dialog-fade-enter-active,
.share-dialog-fade-leave-active {
  transition: opacity 0.18s ease;
}

.share-dialog-fade-enter-from,
.share-dialog-fade-leave-to {
  opacity: 0;
}

.spin {
  animation: share-spin 1s linear infinite;
}

@keyframes share-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
