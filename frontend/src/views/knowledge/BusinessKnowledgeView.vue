<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Briefcase } from 'lucide-vue-next'
import KnowledgePlaceholderCard from '@/components/knowledge/KnowledgePlaceholderCard.vue'

const { t } = useI18n()
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ t('knowledge.business.title') }}</h2>
        <p class="mgmt-subtitle">{{ t('knowledge.business.subtitle') }}</p>
      </div>
    </div>

    <KnowledgePlaceholderCard
      :icon="Briefcase"
      :title="t('knowledge.business.placeholder_title')"
      :description="t('knowledge.business.placeholder_desc')"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
