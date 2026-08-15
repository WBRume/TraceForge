<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ category: string }>()
const { t } = useI18n()

const label = computed(() => t(`case_center.category.${props.category}`))
const cls = computed(() => `case-cat-${String(props.category).toLowerCase()}`)
</script>

<template>
  <span class="case-cat-tag" :class="cls">{{ label }}</span>
</template>

<style scoped>
.case-cat-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}

.case-cat-public { color: #155e75; background: #ecfeff; border: 1px solid #a5f3fc; }
.case-cat-product { color: #6b21a8; background: #faf5ff; border: 1px solid #e9d5ff; }
.case-cat-site { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.case-cat-temporary { color: #57534e; background: #fafaf9; border: 1px solid #e7e5e4; }
</style>
