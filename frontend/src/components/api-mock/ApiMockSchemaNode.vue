<script setup lang="ts">
import { computed, inject, unref } from 'vue'
import type { PropType } from 'vue'

defineOptions({
  name: 'ApiMockSchemaNode',
})
import {
  Plus,
  X,
} from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'

const TYPES = ['string', 'number', 'integer', 'boolean', 'object', 'array'] as const
const TYPE_OPTIONS = TYPES.map(t => ({ label: t, value: t }))

type SchemaNode = Record<string, any>

const props = defineProps({
  modelValue: {
    type: Object as PropType<SchemaNode>,
    required: true,
  },
  nodeKey: {
    type: String,
    default: '',
  },
  isRoot: {
    type: Boolean,
    default: false,
  },
  isRequired: {
    type: Boolean,
    default: false,
  },
  hideKey: {
    type: Boolean,
    default: false,
  },
  depth: {
    type: Number,
    default: 0,
  },
  readonly: {
    type: Boolean,
    default: false,
  },
  refTrail: {
    type: Array as PropType<string[]>,
    default: () => [],
  },
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: SchemaNode): void
  (e: 'update:nodeKey', value: string): void
  (e: 'update:isRequired', value: boolean): void
  (e: 'remove'): void
}>()

// Provide/Inject for globally available entities dropdown
const availableEntities = inject<any[]>('availableEntities', [])

const entityOptions = computed(() => {
  const entities = unref(availableEntities) || []
  return [
    { label: 'Custom Object', value: '' },
    ...entities.map((e: any) => ({ label: e.name, value: e.name }))
  ]
})

const nodeType = computed({
  get: () => {
    if (props.modelValue.$ref) return 'object'
    return props.modelValue.type || 'string'
  },
  set: (newType: string) => {
    const newVal = { ...props.modelValue }
    
    // Clear out $ref if switching away from object
    if (newVal.$ref && newType !== 'object') {
      delete newVal.$ref
    }
    
    if (newType === 'object') {
      newVal.type = 'object'
      newVal.properties = newVal.properties || {}
      delete newVal.items
    } else if (newType === 'array') {
      newVal.type = 'array'
      newVal.items = newVal.items || { type: 'string' }
      delete newVal.properties
      delete newVal.$ref
    } else {
      newVal.type = newType
      delete newVal.properties
      delete newVal.items
      delete newVal.$ref
    }
    emit('update:modelValue', newVal)
  },
})

const currentRefEntity = computed({
  get: () => {
    const r = props.modelValue.$ref as string || ''
    return r.split('/').pop() || ''
  },
  set: (entName: string) => {
    const newVal = { ...props.modelValue }
    if (!entName) {
      // Revert to custom object
      newVal.type = 'object'
      newVal.properties = newVal.properties || {}
      delete newVal.$ref
      delete newVal.items
    } else {
      // Bind reference
      delete newVal.type
      delete newVal.properties
      delete newVal.items
      newVal.$ref = `#/components/schemas/${entName}`
    }
    emit('update:modelValue', newVal)
  },
})

const referencedEntity = computed(() => {
  const refName = currentRefEntity.value
  if (!refName) return null
  const entities = unref(availableEntities) || []
  return entities.find((entity: any) => String(entity?.name || '') === refName) || null
})

const isCircularRef = computed(() => {
  const refName = currentRefEntity.value
  if (!refName) return false
  return props.refTrail.includes(refName)
})

const MAX_SCHEMA_DEPTH = 20
const exceedMaxDepth = computed(() => props.depth >= MAX_SCHEMA_DEPTH)

const nextRefTrail = computed(() => {
  const refName = currentRefEntity.value
  if (!refName) return props.refTrail
  return [...props.refTrail, refName]
})

const referencedEntityProperties = computed<Record<string, SchemaNode>>(() => {
  const schema = referencedEntity.value?.schema_json
  if (!schema || typeof schema !== 'object') return {}
  const properties = (schema as Record<string, unknown>).properties
  if (!properties || typeof properties !== 'object') return {}
  return properties as Record<string, SchemaNode>
})

const referencedEntityRequired = computed<string[]>(() => {
  const schema = referencedEntity.value?.schema_json
  if (!schema || typeof schema !== 'object') return []
  const required = (schema as Record<string, unknown>).required
  if (!Array.isArray(required)) return []
  return required.map((item) => String(item))
})

const hasReferencedEntityPreview = computed(() => {
  if (nodeType.value !== 'object') return false
  if (props.modelValue.properties && typeof props.modelValue.properties === 'object') return false
  if (isCircularRef.value) return false
  if (exceedMaxDepth.value) return false
  return Object.keys(referencedEntityProperties.value).length > 0
})

const noop = () => {}
const noopBool = (_val: boolean) => {}

const updateField = (field: keyof SchemaNode, value: any) => {
  emit('update:modelValue', { ...props.modelValue, [field]: value })
}

const addProperty = () => {
  const propsObj = { ...(props.modelValue.properties || {}) }
  let baseName = 'newField'
  let inc = 1
  while (propsObj[baseName]) {
    baseName = `newField${inc++}`
  }
  propsObj[baseName] = { type: 'string' }
  updateField('properties', propsObj)
}

const updateChildPropertyKey = (oldKey: string, newKey: string) => {
  const propsObj = { ...props.modelValue.properties }
  if (oldKey === newKey || !newKey) return
  propsObj[newKey] = propsObj[oldKey]
  delete propsObj[oldKey]
  
  // also update required array
  const reqs = [...(props.modelValue.required || [])]
  const idx = reqs.indexOf(oldKey)
  if (idx !== -1) {
    reqs[idx] = newKey
    updateField('required', reqs)
  }
  updateField('properties', propsObj)
}

const updateChildPropertyValue = (key: string, val: SchemaNode) => {
  const propsObj = { ...props.modelValue.properties }
  propsObj[key] = val
  updateField('properties', propsObj)
}

const removeChildProperty = (key: string) => {
  const propsObj = { ...props.modelValue.properties }
  delete propsObj[key]
  updateField('properties', propsObj)
  
  const reqs = (props.modelValue.required || []).filter((r: string) => r !== key)
  if (reqs.length !== (props.modelValue.required || []).length) {
    updateField('required', reqs.length > 0 ? reqs : undefined)
  }
}

const toggleChildRequired = (key: string, isReq: boolean) => {
  let reqs = [...(props.modelValue.required || [])]
  if (isReq && !reqs.includes(key)) {
    reqs.push(key)
  } else if (!isReq) {
    reqs = reqs.filter((r) => r !== key)
  }
  updateField('required', reqs.length > 0 ? reqs : undefined)
}
</script>

<template>
  <div class="schema-node-tree">
    <!-- Main Node Row -->
    <div class="pm-row pm-schema-row" :class="{'is-root': isRoot}">
      <!-- KEY COLUMN -->
      <div class="pm-col" style="flex: 2">
        <div :style="{ paddingLeft: `${depth * 1.5}rem`, display: 'flex', alignItems: 'center', width: '100%', gap: '0.4rem' }">
          <span v-if="depth > 0 && !isRoot" class="text-slate-300 font-mono text-[0.75rem]">└</span>
          <input
            v-if="!isRoot && !hideKey"
            :value="nodeKey"
            @input="emit('update:nodeKey', ($event.target as HTMLInputElement).value)"
            class="pm-inp font-mono"
            :disabled="readonly"
            style="font-weight: 500;"
            placeholder="key"
          />
          <span v-else-if="!hideKey" class="pm-inp text-slate-500 font-mono text-[0.82rem] flex items-center" style="font-weight: 600;">{{ isRoot ? 'root' : nodeKey }}</span>
        </div>
      </div>

      <!-- TYPE COLUMN -->
      <div class="pm-col pm-split" style="flex: 1.2">
        <BaseSelect v-model="nodeType" :options="TYPE_OPTIONS" :disabled="readonly" size="sm" class="pm-val-select" />
        <BaseSelect v-if="nodeType === 'object'" v-model="currentRefEntity" :options="entityOptions" :disabled="readonly" size="sm" class="pm-val-select custom-ref" />
      </div>

      <!-- REQ COLUMN -->
      <div class="pm-col pm-check" style="flex: 0.4">
        <input
          v-if="!isRoot"
          type="checkbox"
          :checked="isRequired"
          @change="emit('update:isRequired', ($event.target as HTMLInputElement).checked)"
          :disabled="readonly"
        />
      </div>

      <!-- DESCRIPTION COLUMN -->
      <div class="pm-col" style="flex: 1.5">
        <input
          :value="modelValue.description || ''"
          @input="updateField('description', ($event.target as HTMLInputElement).value)"
          class="pm-inp"
          :disabled="readonly"
          placeholder="Description"
        />
      </div>

      <!-- ACTIONS COLUMN -->
      <div class="pm-col-auto" style="width: 3.5rem; justify-content: flex-end; padding-right: 0.5rem; gap: 0.2rem">
        <button
          v-if="nodeType === 'object' && !readonly"
          @click="addProperty"
          class="pm-del-btn"
          title="Add Property"
        >
          <Plus class="w-3.5 h-3.5" />
        </button>

        <button
          v-if="!isRoot && !readonly"
          @click="emit('remove')"
          class="pm-del-btn"
          title="Remove Node"
        >
          <X class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Children Nodes -->
    <template v-if="nodeType === 'object' && modelValue.properties && !exceedMaxDepth">
      <ApiMockSchemaNode
        v-for="(childVal, childKey) in modelValue.properties"
        :key="String(childKey)"
        :nodeKey="String(childKey)"
        :modelValue="childVal"
        :isRequired="(modelValue.required || []).includes(childKey)"
        :depth="depth + 1"
        :readonly="readonly"
        :ref-trail="refTrail"
        @update:nodeKey="updateChildPropertyKey(String(childKey), $event)"
        @update:modelValue="updateChildPropertyValue(String(childKey), $event)"
        @update:isRequired="toggleChildRequired(String(childKey), $event)"
        @remove="removeChildProperty(String(childKey))"
      />
    </template>

    <template v-if="hasReferencedEntityPreview">
      <div class="pm-row pm-schema-row pm-ref-caption">
        <div class="pm-col" style="flex: 2">
          <div :style="{ paddingLeft: `${(depth + 1) * 1.5}rem`, display: 'flex', alignItems: 'center', width: '100%', gap: '0.4rem' }">
            <span class="text-slate-300 font-mono text-[0.75rem]">└</span>
            <span class="pm-inp text-slate-500 font-mono text-[0.82rem] flex items-center" style="font-weight: 600;">
              {{ currentRefEntity }}
            </span>
          </div>
        </div>
        <div class="pm-col" style="flex: 1.2"></div>
        <div class="pm-col pm-check" style="flex: 0.4"></div>
        <div class="pm-col" style="flex: 1.5"></div>
        <div class="pm-col-auto" style="width: 3.5rem"></div>
      </div>

      <ApiMockSchemaNode
        v-for="(childVal, childKey) in referencedEntityProperties"
        :key="`ref-${String(childKey)}`"
        :nodeKey="String(childKey)"
        :modelValue="childVal"
        :isRequired="referencedEntityRequired.includes(String(childKey))"
        :depth="depth + 2"
        :readonly="true"
        :ref-trail="nextRefTrail"
        @update:nodeKey="noop"
        @update:modelValue="noop"
        @update:isRequired="noopBool"
        @remove="noop"
      />
    </template>

    <template v-if="nodeType === 'array' && modelValue.items && !exceedMaxDepth">
      <ApiMockSchemaNode
        nodeKey="items"
        :hideKey="true"
        :modelValue="modelValue.items"
        :depth="depth + 1"
        :readonly="readonly"
        :ref-trail="refTrail"
        @update:modelValue="updateField('items', $event)"
      />
    </template>

    <div v-if="exceedMaxDepth" class="pm-row pm-schema-row pm-ref-caption">
      <div class="pm-col" style="flex: 2">
        <div :style="{ paddingLeft: `${(depth + 1) * 1.5}rem`, display: 'flex', alignItems: 'center', width: '100%', gap: '0.4rem' }">
          <span class="text-slate-300 font-mono text-[0.75rem]">└</span>
          <span class="pm-inp text-slate-400 font-mono text-[0.78rem] flex items-center" style="font-weight: 500;">
            schema depth limit reached
          </span>
        </div>
      </div>
      <div class="pm-col" style="flex: 1.2"></div>
      <div class="pm-col pm-check" style="flex: 0.4"></div>
      <div class="pm-col" style="flex: 1.5"></div>
      <div class="pm-col-auto" style="width: 3.5rem"></div>
    </div>
  </div>
</template>
