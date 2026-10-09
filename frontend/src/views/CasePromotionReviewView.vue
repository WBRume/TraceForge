<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, RefreshCw, AlertCircle, CheckCircle2 } from '@/components/icons'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import type { PromotionDraft, PromotionJob } from '@/types/playbookPromotion'
import CasePromotionReview from '@/components/case-center/CasePromotionReview.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { useProvisioningStore } from '@/stores/provisioning'

const route = useRoute()
const router = useRouter()
const floating = useProvisioningStore()

const wsId = computed(() => String(route.params.wsId || ''))
const jobId = ref(String(route.params.jobId || ''))

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const job = shallowRef<PromotionJob | null>(null)
const reviewDraft = ref<PromotionDraft | null>(null)

let loadVersion = 0
let draftIdentity = ''
let regenerationKey = ''
const discardConfirmOpen = ref(false)
const mergeConfirmOpen = ref(false)

const isConfirmed = computed(() => job.value?.result?.review_state === 'CONFIRMED')
const isDiscarded = computed(() => job.value?.result?.review_state === 'DISCARDED')

const loadJob = async () => {
  if (!wsId.value || !jobId.value) return
  error.value = ''
  const version = ++loadVersion
  try {
    const endpoint = `/workspaces/${wsId.value}/cases/playbook-promotions`
    const { data } = await api.get(endpoint, { params: { job_id: jobId.value } })
    let current: PromotionJob | undefined =
      data.items?.find((item: PromotionJob) => item.job_id === jobId.value) || data.items?.[0]

    if (version !== loadVersion) return
    const visited = new Set<string>()
    while (current?.result?.replacement_job_id && !visited.has(current.job_id)) {
      visited.add(current.job_id)
      const resp = await api.get(endpoint, { params: { job_id: current.result.replacement_job_id } })
      if (version !== loadVersion) return
      const nextJob = resp.data.items?.[0]
      if (nextJob) {
        current = nextJob
        jobId.value = nextJob.job_id
      } else {
        break
      }
    }

    if (current) {
      job.value = current
      const reviewState = current.result?.review_state
      if (reviewState === 'CONFIRMED' || reviewState === 'DISCARDED') {
        floating.dismiss(current.job_id)
      } else {
        floating.ingestPromotionJob(current)
      }
      const identity = `${current.job_id}:${current.result?.draft_revision || ''}`
      if (current.result?.draft && identity !== draftIdentity) {
        draftIdentity = identity
        reviewDraft.value = JSON.parse(JSON.stringify(current.result.draft))
      }
      // Execution belongs to the shared background queue, not this review route.
      if (!['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED'].includes(current.status)) {
        floating.expand()
        goBack()
      }
    } else {
      error.value = '未找到对应的诊断规程晋升任务'
    }
  } catch (e: any) {
    if (version === loadVersion) error.value = e.response?.data?.detail?.message || '加载晋升规程草案失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

const goBack = () => {
  if (route.path.startsWith('/knowledge')) {
    router.push({ name: 'knowledgeCasesWorkspace', params: { wsId: wsId.value } })
  } else {
    router.push({ name: 'workspaceCases', params: { wsId: wsId.value } })
  }
}

const handleConfirm = async () => {
  if (!job.value || !reviewDraft.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const current = job.value
    const sanitizedDraft = {
      ...reviewDraft.value,
      playbooks: reviewDraft.value.playbooks.map((p) => ({
        ...p,
        title: p.title.trim(),
        summary: p.summary.trim(),
        symptoms: p.symptoms.map((s) => s.trim()).filter(Boolean),
        steps: p.steps.map((s) => s.trim()).filter(Boolean),
      })),
    }

    const { data } = await api.post(
      `/workspaces/${wsId.value}/cases/playbook-promotions/${current.job_id}/confirm`,
      {
        draft_revision: current.result?.draft_revision,
        draft: sanitizedDraft,
      },
    )

    job.value = data
    floating.dismiss(current.job_id)
    ElMessage.success('诊断规程已成功入库！')

    // 跳转回案例中心或规程库
    goBack()
  } catch (e: any) {
    const code = e.response?.data?.detail?.code
    if (code === 'PROMOTION_DRAFT_CHANGED') {
      error.value = '草案已在其他页面处理，请重新刷新'
      await loadJob()
    } else if (code === 'CASE_NOT_APPROVED') {
      error.value = '关联案例状态发生变更，无法入库'
    } else {
      error.value = e.response?.data?.detail?.message || '确认入库失败，请稍后重试'
    }
  } finally {
    busy.value = false
  }
}

const handleDiscard = () => {
  discardConfirmOpen.value = true
}

const doDiscard = async () => {
  if (!job.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const current = job.value
    const { data } = await api.post(
      `/workspaces/${wsId.value}/cases/playbook-promotions/${current.job_id}/discard`,
      {
        draft_revision: current.result?.draft_revision,
      },
    )
    job.value = data
    floating.dismiss(current.job_id)
    discardConfirmOpen.value = false
    ElMessage.info('已放弃该诊断规程草案')
    goBack()
  } catch (e: any) {
    error.value = e.response?.data?.detail?.message || '放弃操作失败'
  } finally {
    busy.value = false
  }
}

const handleMerge = () => {
  mergeConfirmOpen.value = true
}

const doMerge = async () => {
  if (!job.value || busy.value) return
  busy.value = true
  error.value = ''
  if (!regenerationKey) regenerationKey = crypto.randomUUID()
  try {
    const current = job.value
    const { data } = await api.post(
      `/workspaces/${wsId.value}/cases/playbook-promotions/${current.job_id}/regenerate`,
      {
        draft_revision: current.result?.draft_revision,
        idempotency_key: regenerationKey,
      },
    )
    floating.dismiss(current.job_id)
    mergeConfirmOpen.value = false
    regenerationKey = ''
    job.value = data
    jobId.value = data.job_id
    floating.ingestPromotionJob(data)
    reviewDraft.value = null
    goBack()
    ElMessage.success('重新提炼任务已加入后台队列')
  } catch (e: any) {
    error.value = e.response?.data?.detail?.message || '发起重新提炼失败'
  } finally {
    busy.value = false
  }
}

const onUpdate = (event: Event) => {
  const detail = (event as CustomEvent).detail
  if (detail?.workspace_id === wsId.value) {
    void loadJob()
  }
}

const onResync = () => { void loadJob() }
watch(() => route.params.jobId, (id) => {
  jobId.value = String(id || '')
  job.value = null
  reviewDraft.value = null
  loading.value = true
  void loadJob()
})
onMounted(() => {
  window.addEventListener('playbook-promotion-updated', onUpdate)
  window.addEventListener('playbook-promotion-resync', onResync)
  void loadJob()
})

onUnmounted(() => {
  loadVersion++
  window.removeEventListener('playbook-promotion-updated', onUpdate)
  window.removeEventListener('playbook-promotion-resync', onResync)
})
</script>

<template>
  <div class="promotion-review-view">
    <!-- 顶部独立路由全景导航与操作栏 -->
    <header class="view-top-bar">
      <div class="bar-left">
        <button type="button" class="back-link-btn" @click="goBack">
          <ArrowLeft :size="16" />
          <span>返回案例中心</span>
        </button>
        <div class="divider-v" />
        <div class="title-meta">
          <h1 class="page-title">案例晋升诊断规程确认</h1>
        </div>
      </div>

      <div class="bar-right">
        <button
          type="button"
          class="btn-refresh"
          :disabled="loading || busy"
          title="刷新任务状态"
          @click="loadJob"
        >
          <RefreshCw :size="15" :class="{ spinning: loading }" />
          <span>刷新</span>
        </button>
      </div>
    </header>

    <!-- 页面主体容器 -->
    <main class="view-container">
      <!-- 加载中态 -->
      <section v-if="loading" class="state-card loading-state">
        <div class="loading-spinner">
          <RefreshCw :size="32" class="spinning" />
        </div>
        <h3>正在加载规程草案...</h3>
        <p>正在拉取提炼任务及相关案例规格，请稍候</p>
      </section>

      <!-- 任务已完成入库态 (CONFIRMED) -->
      <section v-else-if="isConfirmed" class="state-card success-state">
        <div class="success-icon-badge">
          <CheckCircle2 :size="40" />
        </div>
        <h3>诊断规程已确认入库</h3>
        <p>所提炼的规程已成功纳入诊断规程知识库，可供团队复用及自动推荐匹配。</p>
        <div class="state-actions">
          <button type="button" class="btn-primary" @click="goBack">返回案例中心</button>
        </div>
      </section>

      <!-- 任务已废弃态 (DISCARDED) -->
      <section v-else-if="isDiscarded" class="state-card discarded-state">
        <div class="info-icon-badge">
          <AlertCircle :size="36" />
        </div>
        <h3>本次规程草案已放弃</h3>
        <p>该草案已被放弃处理，未写入诊断规程库。</p>
        <div class="state-actions">
          <button type="button" class="btn-secondary" @click="goBack">返回案例中心</button>
        </div>
      </section>

      <!-- 待确认草案审核态 (PENDING Review) -->
      <div v-else-if="reviewDraft" class="review-wrapper">
        <CasePromotionReview
          v-model="reviewDraft"
          :cases="job?.cases || []"
          :busy="busy"
          :error="error"
          @confirm="handleConfirm"
          @discard="handleDiscard"
          @merge="handleMerge"
        />
      </div>

      <!-- 异常或未找到 -->
      <section v-else class="state-card error-state">
        <AlertCircle :size="36" class="error-icon" />
        <h3>无法展示规程草案</h3>
        <p>{{ error || '草案可能已过期或任务已删除' }}</p>
        <div class="state-actions">
          <button type="button" class="btn-secondary" @click="goBack">返回案例中心</button>
          <button type="button" class="btn-primary" @click="loadJob">重试</button>
        </div>
      </section>
    </main>

    <!-- 放弃草案确认弹窗（统一采用 ConfirmActionModal 全局规范） -->
    <ConfirmActionModal
      :show="discardConfirmOpen"
      title="放弃诊断规程草案"
      message="确定要放弃本次提炼的诊断规程草案吗？"
      description="放弃后将丢弃当前生成的全部诊断规程与编辑内容，且无法恢复。"
      cancel-text="取消"
      confirm-text="确定放弃"
      tone="danger"
      :loading="busy"
      @cancel="discardConfirmOpen = false"
      @confirm="doDiscard"
    />

    <!-- 合并重新提炼确认弹窗（统一采用 ConfirmActionModal 全局规范） -->
    <ConfirmActionModal
      :show="mergeConfirmOpen"
      title="全部合并并重新提炼"
      message="确定要将所有案例合并并重新提炼规程吗？"
      description="AI 将把当前所选的全部案例合并为一套统一的方法论重新归纳提炼。"
      cancel-text="取消"
      confirm-text="开始重新提炼"
      tone="primary"
      :loading="busy"
      @cancel="mergeConfirmOpen = false"
      @confirm="doMerge"
    />
  </div>
</template>

<style scoped>
.promotion-review-view {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: #f8fafc;
}

/* 顶部独立全景导航栏 */
.view-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
  z-index: 20;
}

.bar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-link-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.back-link-btn:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.divider-v {
  width: 1px;
  height: 20px;
  background: #cbd5e1;
}

.title-meta {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.sub-text {
  font-size: 13px;
  color: #64748b;
}

.btn-refresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  font-size: 13px;
  font-weight: 500;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-refresh:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #94a3b8;
}

/* 主体容器 */
.view-container {
  flex: 1;
  max-width: 1380px;
  width: 100%;
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
}

.review-wrapper {
  width: 100%;
}

/* 状态展示卡片 */
.state-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 48px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 12px;
  max-width: 600px;
  margin: 40px auto;
}

.state-card h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.state-card p {
  margin: 0;
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
}

.sparkles-halo {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
}

.success-icon-badge {
  color: #16a34a;
}

.error-icon {
  color: #dc2626;
}

.progress-box {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.progress-track {
  flex: 1;
  height: 8px;
  background: #e2e8f0;
  border-radius: 9999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 9999px;
  transition: width 0.3s ease;
}

.progress-num {
  font-size: 13px;
  font-weight: 600;
  color: #3b82f6;
  min-width: 36px;
}

.progress-tip {
  font-size: 12px !important;
  color: #94a3b8 !important;
}

.state-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
