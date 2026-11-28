<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const items = computed(() =>
  [0, 1, 2, 3].map((idx) => ({
    kicker: t(`portal.showcase_bottom.items.${idx}.kicker`),
    value: t(`portal.showcase_bottom.items.${idx}.value`)
  }))
)
</script>

<template>
  <div class="platform-strip">
    <div class="strip-grid">
      <div v-for="(item, idx) in items" :key="idx" class="strip-cell">
        <span class="strip-kicker">{{ item.kicker }}</span>
        <span class="strip-value">{{ item.value }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.platform-strip {
  max-width: 1220px;
  margin: 0 auto;
  border-top: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
}

.strip-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.strip-cell {
  padding: 1.35rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  border-right: 1px solid #f1f5f9;
  transition: background-color 0.2s ease;
}

.strip-cell:last-child {
  border-right: none;
}

.strip-cell:hover {
  background: rgba(248, 250, 252, 0.75);
}

.strip-kicker {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #64748b;
  text-transform: uppercase;
}

.strip-value {
  font-family: var(--font-mono, monospace);
  font-size: 0.82rem;
  font-weight: 600;
  color: #0f172a;
}

@media (max-width: 960px) {
  .strip-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .strip-cell {
    border-bottom: 1px solid #f1f5f9;
  }

  .strip-cell:nth-child(2n) {
    border-right: none;
  }

  .strip-cell:nth-last-child(-n+2) {
    border-bottom: none;
  }
}

@media (max-width: 540px) {
  .strip-grid {
    grid-template-columns: 1fr;
  }

  .strip-cell {
    border-right: none;
    border-bottom: 1px solid #f1f5f9;
  }

  .strip-cell:last-child {
    border-bottom: none;
  }
}
</style>
