<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AssetAiJob, AssetResolutionProposal, AssetThread } from '@/composables/asset-discussion/types'

const props = defineProps<{
  threads: AssetThread[]
  jobs: Record<string, AssetAiJob>
  versionNumbers: Record<string, number>
  contextVersionId?: string
  canGenerate: boolean
  showGenerate: boolean
  disabledReason?: string
}>()
const emit = defineEmits<{
  generate: []
  open: [proposalId: string]
  resume: [job: AssetAiJob]
}>()
const { t } = useI18n()
const proposals = computed(() => props.threads.flatMap(thread => thread.proposals)
  .sort((a, b) => Date.parse(b.updated_at || b.created_at) - Date.parse(a.updated_at || a.created_at)))
const pending = computed(() => Object.values(props.jobs).filter(job =>
  job.context_json?.job_kind === 'RESOLUTION_PROPOSAL'
  && Array.isArray(job.context_json?.source_thread_ids)
  && job.context_json?.context_version_id === props.contextVersionId
  && ['PENDING', 'RUNNING', 'WAITING_HITL'].includes(job.status),
))
const sources = (proposal: AssetResolutionProposal) => {
  const ids = proposal.proposed_patch_json?.source_thread_ids
  return Array.isArray(ids) ? ids.length : 1
}
const versionLabel = (id: string) => {
  const number = props.versionNumbers[id]
  return number ? `v${number}` : ''
}
</script>

<template>
  <section v-if="showGenerate || proposals.length || pending.length" class="conclusions">
    <div class="conclusion-head">
      <h4>{{ t('doc_review.proposal_section_title') }}</h4>
      <button
        v-if="showGenerate"
        type="button"
        class="btn-primary conclusion-generate"
        :disabled="!canGenerate"
        :title="disabledReason || undefined"
        @click="emit('generate')"
      >{{ t('doc_review.proposal_generate') }}</button>
    </div>
    <button v-for="job in pending" :key="job.id" type="button" class="btn-secondary" @click="emit('resume', job)">
      {{ t('doc_review.proposal_generating') }}
    </button>
    <details v-if="proposals.length">
      <summary>{{ t('doc_review.proposal_count', { count: proposals.length }) }}</summary>
      <ul class="proposal-list">
        <li v-for="proposal in proposals" :key="proposal.id">
          <span>
            <strong>{{ t(`doc_review.proposal_status_${proposal.status}`) }}</strong>
            <small>
              {{ versionLabel(proposal.base_version_id) }}
              · {{ t('doc_review.proposal_selected_threads', { count: sources(proposal) }) }}
              · {{ new Date(proposal.created_at).toLocaleString() }}
            </small>
          </span>
          <button type="button" class="btn-secondary" @click="emit('open', proposal.id)">
            {{ t('doc_review.proposal_open') }}
          </button>
        </li>
      </ul>
    </details>
  </section>
</template>

<style scoped>
.conclusions {
  padding: .7rem .8rem;
  border: 1px solid #dbe6ef;
  border-radius: var(--radius-lg);
  background: rgba(255, 255, 255, .8);
}
.conclusion-head, .proposal-list li { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.conclusion-head h4 { margin: 0; font-size: .9rem; font-weight: 650; color: var(--color-text-title); }
.conclusion-generate, .proposal-list button { padding: .3rem .6rem; white-space: nowrap; font-size: .75rem; }
.conclusions summary, .proposal-list small {
  display: block;
  margin: .35rem 0;
  color: var(--color-text-muted);
  font-size: .75rem;
}
.conclusions summary { display: list-item; cursor: pointer; }
.proposal-list { display: grid; gap: .5rem; max-height: 12rem; overflow-y: auto; padding: .35rem 0; margin: 0; }
.proposal-list strong { font-size: .8rem; }
</style>
