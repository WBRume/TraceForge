<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import TaskAssetEmptyState from './TaskAssetEmptyState.vue'
import { useTaskDetailAssets } from '@/composables/useTaskDetailAssets'
import type { HumanReviewLight } from '@/types/workspaceAssets'

const props = defineProps<{
  reviews: HumanReviewLight[]
  workspaceId: string
  taskId: string
}>()

const emit = defineEmits<{
  mutated: []
}>()

const { t } = useI18n()
const taskAssets = useTaskDetailAssets()

const selectedReviewId = ref('')

const form = reactive({
  outcome: 'ACCEPT_WITH_MODIFICATION',
  status: 'OPEN',
  title: '',
  body: '',
  change_reason: '',
})

const commentForm = reactive({
  body: '',
  comment_type: 'review_comment',
  change_reason: '',
})

async function submitReview() {
  const result = await taskAssets.createHumanReview(props.workspaceId, props.taskId, { ...form })
  if (!result) return
  emit('mutated')
  Object.assign(form, { outcome: 'ACCEPT_WITH_MODIFICATION', status: 'OPEN', title: '', body: '', change_reason: '' })
  ElMessage.success(t('workspace_assets.task_detail.workbench.saved'))
}

async function submitComment() {
  if (!selectedReviewId.value) return
  const result = await taskAssets.createHumanReviewComment(props.workspaceId, props.taskId, selectedReviewId.value, { ...commentForm })
  if (!result) return
  emit('mutated')
  Object.assign(commentForm, { body: '', comment_type: 'review_comment', change_reason: '' })
  ElMessage.success(t('workspace_assets.task_detail.workbench.saved'))
}
</script>

<template>
  <section class="panel-shell">
    <header class="panel-head">
      <div>
        <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.human_review.eyebrow') }}</span>
        <h2>{{ t('workspace_assets.task_detail.workbench.human_review.title') }}</h2>
        <p>{{ t('workspace_assets.task_detail.workbench.human_review.description') }}</p>
      </div>
      <el-alert
        class="boundary-alert"
        type="info"
        :closable="false"
        :title="t('workspace_assets.task_detail.workbench.human_review.boundary')"
      />
    </header>

    <el-form label-position="top" class="write-form" @submit.prevent="submitReview">
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.outcome')">
            <el-select v-model="form.outcome">
              <el-option label="Accept" value="ACCEPT" />
              <el-option label="Accept with Modification" value="ACCEPT_WITH_MODIFICATION" />
              <el-option label="Reject" value="REJECT" />
              <el-option label="Need Evidence" value="NEED_EVIDENCE" />
              <el-option label="Need Clarification" value="NEED_CLARIFICATION" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.status')">
            <el-select v-model="form.status">
              <el-option label="Open" value="OPEN" />
              <el-option label="Resolved" value="RESOLVED" />
              <el-option label="Closed" value="CLOSED" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.reason')">
            <el-input v-model="form.change_reason" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.title')">
        <el-input v-model="form.title" />
      </el-form-item>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.review_body')">
        <el-input v-model="form.body" type="textarea" :rows="4" />
      </el-form-item>
      <el-button type="primary" :loading="taskAssets.saving.value" @click="submitReview">
        {{ t('workspace_assets.task_detail.workbench.human_review.submit') }}
      </el-button>
    </el-form>

    <TaskAssetEmptyState
      v-if="!reviews.length"
      :title="t('workspace_assets.task_detail.workbench.human_review.empty_title')"
      :message="t('workspace_assets.task_detail.workbench.human_review.empty')"
    />

    <div v-else class="record-list">
      <article v-for="review in reviews" :key="review.id" class="record-card">
        <div class="record-card-head">
          <strong>{{ review.title || review.outcome || review.id }}</strong>
          <el-tag effect="plain">{{ review.status }}</el-tag>
        </div>
        <p v-if="review.body">{{ review.body }}</p>
        <small>{{ t('workspace_assets.task_detail.workbench.fields.outcome') }}: {{ review.outcome || '-' }}</small>
        <div v-if="review.comment_count > 0" class="comment-hint">
          <small>{{ review.comment_count }} {{ review.comment_count === 1 ? 'comment' : 'comments' }}</small>
        </div>
      </article>
    </div>

    <el-form v-if="reviews.length" label-position="top" class="write-form compact" @submit.prevent="submitComment">
      <el-row :gutter="12">
        <el-col :span="10">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.review')">
            <el-select v-model="selectedReviewId">
              <el-option
                v-for="review in reviews"
                :key="review.id"
                :label="review.title || review.outcome || review.id"
                :value="review.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="14">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.comment')">
            <el-input v-model="commentForm.body" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-button :disabled="!selectedReviewId || !commentForm.body" :loading="taskAssets.saving.value" @click="submitComment">
        {{ t('workspace_assets.task_detail.workbench.human_review.add_comment') }}
      </el-button>
    </el-form>
  </section>
</template>

<style scoped>
.panel-shell,
.record-list,
.write-form {
  display: grid;
  gap: 14px;
}

.panel-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
  gap: 16px;
  align-items: start;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.eyebrow {
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.panel-head h2 {
  margin: 5px 0 0;
  color: #0f172a;
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.panel-head p {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 0.95rem;
  line-height: 1.6;
}

.write-form {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.write-form.compact {
  background: #fff;
}

.record-card {
  display: grid;
  gap: 7px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.record-card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.record-card p,
.record-card small {
  margin: 0;
  color: #64748b;
  font-size: 0.82rem;
  line-height: 1.48;
}

.comment-hint {
  padding: 4px 0;
}

.comment-hint small {
  color: #94a3b8;
  font-size: 0.75rem;
}

@media (max-width: 920px) {
  .panel-head {
    grid-template-columns: 1fr;
  }
}
</style>
