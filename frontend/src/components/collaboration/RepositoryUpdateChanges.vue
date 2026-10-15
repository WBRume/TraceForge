<script setup lang="ts">
import { computed, proxyRefs, ref, watch } from 'vue'
import { Sparkles, AlertCircle, Check, ArrowRight, ArrowLeft, GitBranch, GitCommitHorizontal, RefreshCw, Loader2 } from '@/components/icons'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import RepositoryUpdateReview from './RepositoryUpdateReview.vue'
import type { RepositoryUpdates } from '@/composables/collaboration/useRepositoryUpdates'
import type { UpdateState } from '@/services/repositoryUpdates'

const props = defineProps<{ model: RepositoryUpdates }>()
const emit = defineEmits<{ close: []; applied: []; back: [] }>()
const m = computed(() => proxyRefs(props.model))
const draftCount = computed(() => Object.keys(m.value.drafts).length)
const showAdapt = ref(false), confirmApply = ref(false)
const defaultInstruction = '保留原任务目标，将已有成果适配到新的远端代码，解决全部冲突并运行相关验证。'
const instruction = ref(defaultInstruction)
const labels: Record<UpdateState, string> = {
  PREPARING:'正在检查远端版本', READY:'整合结果待审查', CONFLICTS:'有冲突需要处理', ADAPTING:'Agent 正在适配新版本', ADAPT_FAILED:'适配未完成',
  APPLYING:'更新中断，等待恢复核对', APPLIED:'任务代码已更新', FAILED:'检查未完成', RECOVERY_REQUIRED:'需要恢复更新前代码',
}
const canUpdate = computed(() => Boolean(m.value.summary && m.value.summary.can_update !== false))
const hasRemoteUpdates = computed(() => m.value.plan?.repositories.some(repo => repo.baseline !== repo.target))
const canPrepare = computed(() => canUpdate.value && !draftCount.value && !m.value.busy && !m.value.plan?.storage_missing && !['PREPARING','APPLYING','RECOVERY_REQUIRED','ADAPTING'].includes(m.value.plan?.state || ''))
const checking = computed(() => m.value.busy === 'prepare' || m.value.plan?.state === 'PREPARING')
const upToDate = computed(() => m.value.plan?.state === 'READY' && !hasRemoteUpdates.value)
const editable = computed(() => Boolean(canUpdate.value && m.value.plan && ['READY','CONFLICTS'].includes(m.value.plan.state) && !m.value.plan.storage_missing))
const canDiscard = computed(() => canUpdate.value && !m.value.busy && !['APPLYING','RECOVERY_REQUIRED','ADAPTING'].includes(m.value.plan?.state || ''))
const canAdapt = computed(() => !draftCount.value && canUpdate.value && hasRemoteUpdates.value && (editable.value || m.value.plan?.state === 'ADAPT_FAILED'))
async function apply() { if (!draftCount.value && await m.value.command('apply')) confirmApply.value = false }
async function discard() { if (await m.value.command('discard')) emit('close') }
async function resolve(choice: string, text?: string, version?: number) {
  const active = m.value.active
  if (active && await m.value.command('resolve', { repository_id:active.repo.id, path:active.path, choice, text, version:version ?? m.value.plan?.version })) delete m.value.drafts[active.key]
}
function rememberDraft(key: string, value: { text: string; version: number } | null) { if (value) m.value.drafts[key] = value; else delete m.value.drafts[key] }
async function adapt() {
  if (!canAdapt.value || m.value.busy) return
  if (await m.value.command('adapt', { instruction:instruction.value.trim() || defaultInstruction, auto_apply:true })) showAdapt.value = false
}
watch(() => m.value.plan, (plan, previous) => {
  if (plan?.state === 'APPLIED' && previous?.id === plan.id && previous.state !== 'APPLIED') emit('applied')
})
</script>

<template>
  <section class="update-changes" aria-label="更新任务基线">
    <header class="workflow-heading">
      <button type="button" class="back-link" @click="emit('back')"><ArrowLeft :size="14" />返回变更差异</button>
      <div class="workflow-title"><h3>更新任务基线</h3><p>整合远端分支的新提交，保留任务成果。</p></div>
      <button v-if="canUpdate" type="button" class="check-remote" :disabled="!canPrepare" @click="m.command('prepare')"><Loader2 v-if="checking" :size="14" class="spin" /><RefreshCw v-else :size="14" />{{ checking ? '检查中…' : '检查远端更新' }}</button>
      <p v-if="m.error || m.plan?.error" class="update-error" role="alert">{{ m.error || m.plan?.error }}</p>
    </header>
    <div v-if="!m.plan" class="baseline-start">
      <div v-for="repo in m.summary?.repositories || []" :key="repo.id" class="baseline-repository">
        <GitBranch :size="16" /><strong>{{ repo.name }}</strong><span class="branch-name">{{ repo.branch }}</span>
        <span class="baseline-commit"><GitCommitHorizontal :size="13" />当前基线 <code :title="repo.baseline">{{ repo.baseline.slice(0, 8) }}</code></span>
      </div>
      <p>{{ checking ? '正在读取各仓库的远端版本…' : '检查各仓库分支是否有新提交，再审查需要整合的代码。' }}</p>
    </div>
    <template v-else>
    <header class="review-toolbar">
      <span class="review-status" :class="{ warning:m.conflicts }"><AlertCircle v-if="m.conflicts" :size="14" /><Check v-else :size="14" />{{ upToDate ? '已与远端版本对齐' : labels[m.plan.state] }}</span>
      <span class="file-count">{{ m.files.length }} 个文件<span v-if="m.conflicts"> · {{ m.conflicts }} 个冲突</span></span>
      <button v-if="canAdapt" type="button" class="agent-action" :disabled="!!m.busy" aria-haspopup="dialog" @click="showAdapt = true"><Sparkles :size="14" />让 Agent 重新适配</button>
    </header>
    <div v-if="m.plan.state === 'ADAPTING'" class="pending-state" role="status">
      <Sparkles :size="26" /><strong>Agent 正在适配新的远端版本</strong><p>{{ m.plan.auto_apply ? '解决冲突后会自动应用到任务代码，无需再次确认。可在任务会话中查看处理过程。' : '可在任务会话中查看处理过程，完成后在此审查代码差异。' }}</p>
      <button v-if="canUpdate" type="button" :disabled="!!m.busy" @click="m.command('cancel-adaptation')">停止适配</button>
    </div>
    <details v-if="m.plan.agent_summary" class="agent-summary"><summary>Agent 适配说明与验证结果</summary><pre>{{ m.plan.agent_summary }}</pre></details>
    <RepositoryUpdateReview v-if="m.files.length && m.plan.state !== 'ADAPTING'" :plan="m.plan" :selected="m.selected" :detail="m.detail" :busy="!!m.busy" :loading="m.fileLoading" :editable="editable" :drafts="m.drafts" @draft="rememberDraft" @select="m.selected = $event" @resolve="resolve" />
    <div v-else-if="m.plan.state === 'READY'" class="pending-state"><Check :size="26" /><strong>文件内容无需调整</strong><p>{{ upToDate ? '当前任务已使用本次检查的远端基线。' : '可将任务基线更新到本次远端版本。' }}</p></div>
    <footer v-if="canUpdate" class="update-footer">
      <button type="button" class="quiet" :disabled="!canDiscard" @click="discard">{{ m.plan.state === 'APPLIED' ? '关闭更新结果' : '放弃预览' }}</button>
      <small>{{ m.plan.state === 'ADAPTING' && m.plan.auto_apply ? '适配成功后自动应用' : draftCount ? `${draftCount} 个文件的编辑尚未确认` : m.conflicts ? `还有 ${m.conflicts} 个冲突待处理` : m.plan.state === 'APPLIED' ? '已应用到全部任务仓库' : upToDate ? '当前基线已与远端对齐' : '确认后，将整合结果应用到全部任务仓库' }}</small>
      <button v-if="['APPLYING','RECOVERY_REQUIRED'].includes(m.plan.state)" class="primary" type="button" :disabled="!!m.busy" @click="m.command('recover')">恢复更新前代码</button>
      <button v-else-if="!['APPLIED','ADAPTING'].includes(m.plan.state) && hasRemoteUpdates" class="primary" type="button" :disabled="!!m.busy || draftCount > 0 || m.plan.state !== 'READY' || m.plan.storage_missing || m.conflicts > 0" @click="confirmApply = true">{{ m.busy === 'apply' ? '正在应用…' : '应用到任务代码' }}<ArrowRight :size="14" /></button>
    </footer>
    </template>
    <ConfirmActionModal :show="confirmApply" tone="primary" title="应用已审查的代码？" message="将全部仓库更新到本次预览的远端提交，并保留确认后的任务成果。原任务代码会保留恢复快照；当前会话及历史需求继续保留，更新前的消息不再支持撤销代码。" confirm-text="确认应用" cancel-text="继续审查" :loading="m.busy === 'apply'" @cancel="confirmApply = false" @confirm="apply" />
    <ConfirmActionModal :show="showAdapt && !!canAdapt" tone="primary" title="让 Agent 适配并自动应用？" message="Agent 将沿用当前会话的需求和讨论，适配远端新版本。解决冲突并验证后，系统会自动将结果应用到全部任务仓库，无需再次确认。" description="原任务代码会保留恢复快照，会话历史继续保留。处理过程和结果可在任务会话中查看；应用后，更新前的消息不再支持撤销代码。" confirm-text="开始适配并自动应用" cancel-text="取消" :loading="m.busy === 'adapt'" @cancel="showAdapt = false" @confirm="adapt">
      <template #icon><Sparkles :size="24" /></template>
      <template #content><div class="adapt-form"><label for="adapt-instruction">适配要求</label><textarea id="adapt-instruction" v-model="instruction" rows="3" :placeholder="defaultInstruction" :disabled="!!m.busy" /><p v-if="m.error" class="update-error" role="alert">{{ m.error }}</p></div></template>
    </ConfirmActionModal>
  </section>
</template>

<style scoped>
.workflow-heading { display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:12px 16px; border-bottom:1px solid #e2e8f0; }
.workflow-heading .back-link { border:0; padding:0; min-height:24px; color:#64748b; flex-basis:100%; justify-content:flex-start; width:fit-content; }
.workflow-title { flex:1; min-width:0; } .workflow-title h3 { margin:0; color:#0f172a; font-size:14px; } .workflow-title p { margin:4px 0 0; color:#64748b; font-size:11px; }
.workflow-heading .check-remote { color:#0284c7; border-color:#bae6fd; background:#f0f9ff; }
.baseline-start { padding:8px 20px; } .baseline-repository { display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:16px 0; border-bottom:1px solid #e2e8f0; font-size:12px; color:#475569; }
.branch-name { padding:2px 6px; border:1px solid #e2e8f0; border-radius:4px; font-size:11px; }
.baseline-commit { display:flex; align-items:center; gap:6px; margin-left:auto; color:#64748b; font-size:11px; } .baseline-commit code { color:#0284c7; }
.baseline-start p { margin:20px 0; color:#64748b; font-size:12px; }
.spin { animation:spin 1s linear infinite; } @keyframes spin { to { transform:rotate(360deg); } }
.update-changes { display:flex; flex-direction:column; flex:1; min-height:0; min-width:0; overflow:auto; }
.review-toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding:8px 16px; border-bottom:1px solid #e2e8f0; font-size:12px; }
.review-status { display:inline-flex; align-items:center; gap:6px; color:#0284c7; } .review-status.warning { color:#b45309; }
.file-count, small { color:#64748b; font-size:11px; }
button { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:30px; padding:5px 10px; background:#fff; border:1px solid #cbd5e1; border-radius:6px; color:#334155; font-size:11px; cursor:pointer; }
button:hover:not(:disabled) { background:#f8fafc; } button:disabled { opacity:.45; cursor:default; } button:focus-visible { outline:2px solid #38bdf8; outline-offset:2px; }
button.primary { color:#fff; border-color:#0284c7; background:#0284c7; } button.primary:hover:not(:disabled) { background:#0369a1; }
button.quiet { border-color:transparent; } .agent-action { margin-left:auto; color:#7c3aed; border-color:#ddd6fe; }
.update-error { flex-basis:100%; color:#b91c1c; margin:0; overflow-wrap:anywhere; }
.update-footer { display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:10px 16px; border-top:1px solid #e2e8f0; background:#f8fafc; }
.update-footer small { flex:1; text-align:right; margin-right:4px; }
.adapt-form label { display:block; font-size:12px; color:#475569; }
.adapt-form textarea { width:100%; box-sizing:border-box; margin:6px 0; padding:8px; border:1px solid #cbd5e1; border-radius:6px; font:inherit; font-size:12px; line-height:1.6; resize:vertical; }
.pending-state { display:flex; flex:1; align-items:center; justify-content:center; flex-direction:column; gap:10px; padding:30px; color:#64748b; font-size:12px; } .pending-state p { margin:0; }
.agent-summary { padding:8px 16px; font-size:12px; } .agent-summary pre { max-height:180px; overflow:auto; white-space:pre-wrap; }
</style>
