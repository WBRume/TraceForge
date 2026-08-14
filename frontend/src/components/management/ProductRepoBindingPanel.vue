<!--
ProductRepoBindingPanel: list product's repository bindings and add new ones
via a repo-group tree picker. Each pending binding gets a ref type + name.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import { GitBranch, Tag as TagIcon, Trash2 } from 'lucide-vue-next';
import ConfirmActionModal from '@/components/ConfirmActionModal.vue';
import IconActionButton from '@/components/management/IconActionButton.vue';
import RepoGroupPicker from '@/components/management/RepoGroupPicker.vue';
import RefNameInput from '@/components/management/RefNameInput.vue';
import { bindProductRepo, getRepoGroupTree, unbindProductRepo } from '@/services/managementApi';
import { formatApiError } from '@/utils/error';
import type { ProductDetail, ProductRepoBinding, RepoGroupTreeNode, RepoRefType } from '@/types/management';

const props = defineProps<{
  product: ProductDetail | null;
  canManage: boolean;
}>();

const emit = defineEmits<{
  (e: 'changed'): void;
}>();

const { t } = useI18n();

type RefValue = { ref_type: RepoRefType; ref_name: string };

const pickerVisible = ref(false);
const selectedRepoIds = ref<string[]>([]);
const pendingRefs = ref<Record<string, RefValue>>({});
const repoNameMap = ref<Record<string, string>>({});

const savingBinding = ref(false);

const deleteTarget = ref<ProductRepoBinding | null>(null);
const deletingBinding = ref(false);

const bindings = computed<ProductRepoBinding[]>(() => props.product?.repo_bindings ?? []);

const boundRepoIds = computed<string[]>(() => bindings.value.map((b) => b.repository_id));

const repoName = (repoId: string): string => repoNameMap.value[repoId] ?? repoId;

const loadRepoNames = async () => {
  try {
    const res = await getRepoGroupTree();
    const map: Record<string, string> = {};
    for (const node of res.items ?? []) {
      collectNames(node, map);
    }
    repoNameMap.value = map;
  } catch (err) {
    console.error(err);
  }
};

const collectNames = (node: RepoGroupTreeNode, map: Record<string, string>): void => {
  for (const repo of node.repositories) {
    map[repo.id] = repo.name;
  }
  for (const child of node.children) {
    collectNames(child, map);
  }
};

const openPicker = () => {
  pickerVisible.value = true;
};

const defaultRef = (): RefValue => ({ ref_type: 'BRANCH', ref_name: '' });

const ensureRef = (repoId: string): RefValue => {
  if (!pendingRefs.value[repoId]) {
    pendingRefs.value[repoId] = defaultRef();
  }
  return pendingRefs.value[repoId];
};

const updatePendingRef = (repoId: string, value: RefValue) => {
  pendingRefs.value[repoId] = value;
};

const saveBindings = async () => {
  if (!props.product) return;
  const ids = selectedRepoIds.value;
  if (ids.length === 0) return;

  savingBinding.value = true;
  try {
    for (const repoId of ids) {
      const ref = pendingRefs.value[repoId] ?? defaultRef();
      if (!ref.ref_name.trim()) {
        ElMessage.warning(t('management.common.required'));
        return;
      }
      await bindProductRepo(props.product.id, {
        repository_id: repoId,
        ref_type: ref.ref_type,
        ref_name: ref.ref_name.trim(),
      });
    }
    ElMessage.success(t('common.success'));
    selectedRepoIds.value = [];
    pendingRefs.value = {};
    emit('changed');
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t));
  } finally {
    savingBinding.value = false;
  }
};

const confirmUnbind = async () => {
  if (!props.product || !deleteTarget.value) return;
  deletingBinding.value = true;
  try {
    await unbindProductRepo(props.product.id, deleteTarget.value.repository_id);
    ElMessage.success(t('management.common.deleted'));
    deleteTarget.value = null;
    emit('changed');
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t));
  } finally {
    deletingBinding.value = false;
  }
};

watch(
  () => selectedRepoIds.value,
  (ids) => {
    for (const id of ids) {
      ensureRef(id);
    }
  },
  { immediate: true },
);

watch(
  () => pickerVisible.value,
  (visible) => {
    if (visible) void loadRepoNames();
  },
);
</script>

<template>
  <div class="mgmt-card">
    <div class="mgmt-section-head">
      <h3>{{ $t('management.product.bindings_title') }}</h3>
      <button v-if="canManage" class="btn-secondary" @click="openPicker">
        {{ $t('management.product.add_binding') }}
      </button>
    </div>

    <div v-if="bindings.length === 0" class="mgmt-empty">
      {{ $t('management.product.no_bindings') }}
    </div>

    <table v-else class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.product.binding_repo') }}</th>
          <th>{{ $t('management.common.type') }}</th>
          <th>{{ $t('management.product.ref_name') }}</th>
          <th v-if="canManage">{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="binding in bindings" :key="binding.id">
          <td>
            <div class="mgmt-repo-cell">
              <span class="mgmt-repo-name">{{ binding.repository_name }}</span>
              <span v-if="binding.git_url" class="mgmt-repo-url">{{ binding.git_url }}</span>
            </div>
          </td>
          <td>
            <span class="mgmt-tag" :class="binding.repo_type === 'CUSTOM' ? 'custom' : 'ootb'">
              {{ binding.repo_type === 'CUSTOM'
                ? $t('management.repository.type_custom')
                : $t('management.repository.type_ootb') }}
            </span>
          </td>
          <td>
            <span class="mgmt-ref-badge">
              <TagIcon v-if="binding.ref_type === 'TAG'" class="w-4 h-4" />
              <GitBranch v-else class="w-4 h-4" />
              <span class="mgmt-ref-text">{{ binding.ref_type === 'TAG' ? $t('management.product.ref_tag') + ' · ' : '' }}{{ binding.ref_name }}</span>
            </span>
          </td>
          <td v-if="canManage">
            <div class="row-actions">
              <IconActionButton
                :icon="Trash2"
                :title="$t('management.common.delete')"
                tone="danger"
                @click="deleteTarget = binding"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Pending bindings awaiting ref configuration -->
    <div v-if="canManage && selectedRepoIds.length > 0" class="mgmt-pending">
      <p class="mgmt-hint">{{ $t('management.product.binding_validate_hint') }}</p>
      <div v-for="repoId in selectedRepoIds" :key="repoId" class="mgmt-pending-row">
        <span class="mgmt-pending-name">{{ repoName(repoId) }}</span>
        <RefNameInput
          :model-value="ensureRef(repoId)"
          :repository-id="repoId"
          @update:model-value="updatePendingRef(repoId, $event)"
        />
      </div>
      <div class="mgmt-modal-actions">
        <button class="btn-primary" :disabled="savingBinding" @click="saveBindings">
          {{ savingBinding ? $t('management.common.saving') : $t('management.common.save') }}
        </button>
      </div>
    </div>

    <div v-if="canManage" class="mgmt-hint">{{ $t('management.product.select_repos_hint') }}</div>

    <RepoGroupPicker
      :show="pickerVisible"
      :exclude-ids="boundRepoIds"
      v-model="selectedRepoIds"
      @close="pickerVisible = false"
    />

    <ConfirmActionModal
      :show="Boolean(deleteTarget)"
      :title="$t('management.product.bindings_title')"
      :message="$t('management.product.unbind_confirm', {
        name: deleteTarget?.repository_name ?? '',
      })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="deletingBinding"
      @cancel="deleteTarget = null"
      @confirm="confirmUnbind"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.mgmt-repo-cell {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.mgmt-repo-name {
  font-weight: 600;
  color: #334155;
}

.mgmt-repo-url {
  font-size: 0.72rem;
  color: #94a3b8;
  word-break: break-all;
}

.mgmt-ref-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  color: #475569;
}

.mgmt-ref-text {
  white-space: nowrap;
}

.mgmt-pending {
  margin-top: 1rem;
  border-top: 1px solid #e2e8f0;
  padding-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.mgmt-pending-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.mgmt-pending-name {
  width: 180px;
  flex-shrink: 0;
  font-weight: 600;
  font-size: 0.84rem;
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
