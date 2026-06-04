<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

type FormattedBlock =
  | { id: string; type: 'heading'; text: string; level: 2 | 3 | 4 }
  | { id: string; type: 'paragraph'; text: string }
  | { id: string; type: 'list'; ordered: boolean; items: string[] }

const props = defineProps<{
  body?: string | null
  emptyText?: string
}>()

const { t } = useI18n()

function parseRequirementBody(body: string): FormattedBlock[] {
  const blocks: FormattedBlock[] = []
  const paragraph: string[] = []
  let activeList: { ordered: boolean; items: string[] } | null = null
  let blockIndex = 0

  const nextId = (prefix: string) => `${prefix}-${blockIndex += 1}`
  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push({
      id: nextId('paragraph'),
      type: 'paragraph',
      text: paragraph.join(' '),
    })
    paragraph.splice(0)
  }
  const flushList = () => {
    if (!activeList) return
    blocks.push({
      id: nextId(activeList.ordered ? 'ordered' : 'unordered'),
      type: 'list',
      ordered: activeList.ordered,
      items: activeList.items,
    })
    activeList = null
  }

  for (const rawLine of body.replace(/\r\n/g, '\n').split('\n')) {
    const line = rawLine.trim()
    if (!line) {
      flushParagraph()
      flushList()
      continue
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      flushParagraph()
      flushList()
      blocks.push({
        id: nextId('heading'),
        type: 'heading',
        text: heading[2].trim(),
        level: Math.min(heading[1].length + 1, 4) as 2 | 3 | 4,
      })
      continue
    }

    const unorderedItem = line.match(/^[-*•]\s+(.+)$/)
    const orderedItem = line.match(/^\d+[.)、]\s*(.+)$/)
    const listItem = unorderedItem?.[1] || orderedItem?.[1]
    if (listItem) {
      flushParagraph()
      const ordered = Boolean(orderedItem)
      if (!activeList || activeList.ordered !== ordered) {
        flushList()
        activeList = { ordered, items: [] }
      }
      activeList.items.push(listItem.trim())
      continue
    }

    flushList()
    paragraph.push(line)
  }

  flushParagraph()
  flushList()
  return blocks
}

const blocks = computed(() => {
  const body = props.body?.trim()
  return body ? parseRequirementBody(body) : []
})
</script>

<template>
  <div v-if="blocks.length" class="specification-block">
    <template v-for="block in blocks" :key="block.id">
      <component
        :is="`h${block.level}`"
        v-if="block.type === 'heading'"
        class="spec-heading"
      >
        {{ block.text }}
      </component>
      <p v-else-if="block.type === 'paragraph'" class="spec-paragraph">
        {{ block.text }}
      </p>
      <ol v-else-if="block.ordered" class="spec-list is-ordered">
        <li v-for="item in block.items" :key="item">{{ item }}</li>
      </ol>
      <ul v-else class="spec-list">
        <li v-for="item in block.items" :key="item">{{ item }}</li>
      </ul>
    </template>
  </div>
  <el-empty
    v-else
    :description="props.emptyText || t('workspace_assets.requirements.detail.no_body')"
  />
</template>

<style scoped>
.specification-block {
  display: grid;
  gap: 16px;
  color: #334155;
  line-height: 1.8;
}

.spec-heading {
  margin: 12px 0 4px;
  color: #0f172a;
  font-weight: 700;
  letter-spacing: -0.01em;
  font-family: 'Poppins', sans-serif;
}

h2.spec-heading {
  font-size: 1.25rem;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 8px;
}

h3.spec-heading {
  font-size: 1.1rem;
}

h4.spec-heading {
  font-size: 1rem;
  color: #475569;
}

.spec-paragraph {
  margin: 0;
  white-space: pre-wrap;
  font-size: 0.95rem;
}

.spec-list {
  display: grid;
  gap: 10px;
  margin: 4px 0;
  padding-left: 24px;
}

.spec-list li {
  padding-left: 6px;
  font-size: 0.95rem;
}
</style>
