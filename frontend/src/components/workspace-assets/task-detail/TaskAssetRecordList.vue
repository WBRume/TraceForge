<script setup lang="ts">
export type TaskAssetRecordField = {
  label: string
  value: string
}

export type TaskAssetRecordItem = {
  id: string
  title: string
  meta?: string
  detail?: string
  fields?: TaskAssetRecordField[]
}

defineProps<{
  records: TaskAssetRecordItem[]
}>()
</script>

<template>
  <section class="task-asset-records">
    <article v-for="record in records" :key="record.id" class="task-asset-record">
      <strong>{{ record.title }}</strong>
      <small v-if="record.meta">{{ record.meta }}</small>
      <p v-if="record.detail">{{ record.detail }}</p>
      <dl v-if="record.fields?.length" class="record-fields">
        <div v-for="field in record.fields" :key="`${record.id}-${field.label}`">
          <dt>{{ field.label }}</dt>
          <dd>{{ field.value }}</dd>
        </div>
      </dl>
    </article>
  </section>
</template>

<style scoped>
.task-asset-records {
  display: grid;
  gap: 10px;
}

.task-asset-record {
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.74);
}

.task-asset-record strong {
  color: #0f172a;
  font-size: 0.92rem;
}

.task-asset-record small,
.task-asset-record p {
  color: #64748b;
  font-size: 0.8rem;
  line-height: 1.45;
}

.task-asset-record p {
  margin: 0;
  white-space: pre-wrap;
}

.record-fields {
  display: grid;
  gap: 6px;
  margin: 4px 0 0;
}

.record-fields div {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 10px;
  padding-top: 6px;
  border-top: 1px solid #e2e8f0;
}

.record-fields dt,
.record-fields dd {
  margin: 0;
}

.record-fields dt {
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 700;
}

.record-fields dd {
  color: #0f172a;
  font-size: 0.78rem;
  overflow-wrap: anywhere;
}

@media (max-width: 720px) {
  .record-fields div {
    grid-template-columns: 1fr;
    gap: 3px;
  }
}
</style>
