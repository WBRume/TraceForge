<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Wrench } from 'lucide-vue-next'
import KnowledgePlaceholderCard from '@/components/knowledge/KnowledgePlaceholderCard.vue'

const { t } = useI18n()
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ t('knowledge.maintenance.title') }}</h2>
        <p class="mgmt-subtitle">{{ t('knowledge.maintenance.subtitle') }}</p>
      </div>
    </div>

    <KnowledgePlaceholderCard
      :icon="Wrench"
      :title="t('knowledge.maintenance.placeholder_title')"
      :description="t('knowledge.maintenance.placeholder_desc')"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
