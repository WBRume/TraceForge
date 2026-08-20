<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Layers } from 'lucide-vue-next'
import KnowledgePlaceholderCard from '@/components/knowledge/KnowledgePlaceholderCard.vue'

const { t } = useI18n()
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ t('knowledge.framework.title') }}</h2>
        <p class="mgmt-subtitle">{{ t('knowledge.framework.subtitle') }}</p>
      </div>
    </div>

    <KnowledgePlaceholderCard
      :icon="Layers"
      :title="t('knowledge.framework.placeholder_title')"
      :description="t('knowledge.framework.placeholder_desc')"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
