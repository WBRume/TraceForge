<script setup lang="ts">
import { computed } from 'vue'
import type { EvidenceReceipt } from '@/types/diagnosisPlaybook'
const props = defineProps<{ receipts: readonly EvidenceReceipt[] }>()
const receipt = computed(() => [...props.receipts].reverse().find(item => 'comparison.baseline_target_failed' in item.facts))
const checks: [string, string][] = [
  ['baseline_target_failed', '基线捕获原始故障'], ['patch_target_passed', '补丁通过相同目标用例'],
  ['oracle_digest_equal', '判别器保持一致'], ['environment_equal_except_patch', '除补丁外环境一致'],
  ['expected_tests_collected', '目标测试完整收集'], ['regression_passed', '既有业务行为回归'],
  ['balance_conserved', '余额守恒与事务结果'], ['request_coverage_complete', '请求数量与完成度'],
  ['lock_order_consistent', '取锁顺序符合全序'],
]
</script>
<template>
  <details v-if="receipt" class="verification-comparison" open>
    <summary>基线 / 补丁物理对照</summary>
    <table><thead><tr><th scope="col">验证条件</th><th scope="col">独立判别结果</th></tr></thead>
      <tbody><tr v-for="[key, label] in checks" :key="key"><th scope="row">{{ label }}</th><td :class="{ passed: receipt.facts[`comparison.${key}`] === true }">{{ receipt.facts[`comparison.${key}`] === true ? '通过' : receipt.facts[`comparison.${key}`] === false ? '未通过' : '缺少证据' }}</td></tr></tbody>
    </table>
    <small>结果仅适用于本次绑定环境与工作快照。</small>
  </details>
</template>
<style scoped>
.verification-comparison { margin:12px 0 }.verification-comparison table { width:100%; margin:8px 0; border-collapse:collapse }.verification-comparison th,.verification-comparison td { text-align:left; font-weight:normal; padding:5px 8px; border-bottom:1px solid var(--border-color,#ddd) }.passed { color:var(--success-color,#16804a) }
</style>
