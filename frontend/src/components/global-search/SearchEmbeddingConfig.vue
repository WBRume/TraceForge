<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { ElButton, ElInput, ElMessage, ElCheckbox } from 'element-plus'
import api from '@/utils/api'
const profile = shallowRef<any>(null)
const endpoint = shallowRef('https://api.siliconflow.cn/v1/embeddings')
const model = shallowRef('BAAI/bge-m3')
const key = shallowRef('')
const clearKey = shallowRef(false)
const busy = shallowRef(false)
const targets = shallowRef<any[]>([])
const load = async () => {
  const { data } = await api.get('/admin/search/embedding')
  targets.value = data.targets
  profile.value = data.profiles[0] || null
  if (profile.value) { endpoint.value = profile.value.endpoint; model.value = profile.value.model_id }
  key.value = ''
  clearKey.value = false
}
const perform = async (action: () => Promise<unknown>) => {
  busy.value = true
  try { await action(); await load(); ElMessage.success('操作成功') }
  catch (err: any) { ElMessage.error(typeof err.response?.data?.detail === 'string' ? err.response.data.detail : '操作失败，请稍后重试') }
  finally { busy.value = false }
}
const save = () => perform(() => api.put('/admin/search/embedding', {
  id: profile.value?.id, revision: profile.value?.revision || 0, endpoint: endpoint.value, model_id: model.value,
  ...(key.value ? { api_key: key.value } : {}), clear_api_key: clearKey.value,
}))
onMounted(() => void load().catch(() => ElMessage.error('搜索配置加载失败')))
</script>
<template>
  <section class="embedding-config">
    <h3>历史搜索 · 向量模型</h3>
    <p>模型配置保存在服务端。修改地址或模型后需重建索引，原索引在切换前继续服务。</p>
    <label>完整 Embeddings API 地址<ElInput v-model="endpoint" :disabled="busy" /></label>
    <label>模型 ID<ElInput v-model="model" :disabled="busy" /></label>
    <label>API key<ElInput v-model="key" type="password" autocomplete="new-password" :disabled="busy || clearKey" :placeholder="profile?.has_api_key ? '已配置，留空保留现有密钥' : '输入 API key'" /></label>
    <ElCheckbox v-model="clearKey" :disabled="busy">清除已保存的密钥</ElCheckbox>
    <div class="embedding-actions">
      <ElButton :loading="busy" @click="save">保存配置</ElButton>
      <ElButton :disabled="busy || !profile || !!key || endpoint !== profile.endpoint || model !== profile.model_id" @click="perform(() => api.post(`/admin/search/embedding/${profile.id}/test`))">测试连接与维度</ElButton>
      <ElButton :disabled="busy || !profile?.dimension" @click="perform(() => api.post(`/admin/search/embedding/${profile.id}/build`))">建立新索引</ElButton>
    </div>
    <p v-if="profile">状态：{{ profile.status }} · 维度：{{ profile.dimension || '未探测' }}</p>
    <div v-for="target in targets" :key="target.target_id" class="target-row">
      <span>{{ target.status }} · Python RRF · {{ target.verified ? '已核验' : '等待核验' }}</span>
      <ElButton size="small" :disabled="busy" @click="perform(() => api.post(`/admin/search/targets/${target.target_id}/verify`))">核验</ElButton>
      <ElButton size="small" :disabled="busy || !target.verified || target.status === 'active'" @click="perform(() => api.post(`/admin/search/targets/${target.target_id}/activate`))">切换</ElButton>
    </div>
    <ElButton link :disabled="busy" @click="perform(async () => {})">刷新状态</ElButton>
  </section>
</template>
<style scoped>
.embedding-config { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 22px; margin-top: 24px; max-width: 900px; }
.embedding-config p { color: var(--el-text-color-secondary); font-size: 13px; }
.embedding-config label { display: block; margin: 14px 0; font-size: 13px; line-height: 2; }
.embedding-actions, .target-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 14px; }
</style>
