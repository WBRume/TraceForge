<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Pencil } from 'lucide-vue-next'
import AdminGuard from '@/components/management/AdminGuard.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import IconActionButton from '@/components/management/IconActionButton.vue'
import ProjectFormModal from '@/components/management/ProjectFormModal.vue'
import LifecycleTransitionPanel from '@/components/management/LifecycleTransitionPanel.vue'
import ProjectProductsPanel from '@/components/management/ProjectProductsPanel.vue'
import ProjectRepoAssociationsPanel from '@/components/management/ProjectRepoAssociationsPanel.vue'
import ReleaseListSection from '@/components/management/ReleaseListSection.vue'
import ReleaseFormModal from '@/components/management/ReleaseFormModal.vue'
import { deleteProjectRelease, getProject } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'
import type { Project, ProjectDetail, ProjectRelease } from '@/types/management'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => Boolean(authStore.user?.is_admin))

const projectId = computed(() => String(route.params.projectId ?? ''))

const project = ref<ProjectDetail | null>(null)
const loading = ref(true)

const load = async () => {
  loading.value = true
  try {
    project.value = await getProject(projectId.value)
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

const goBack = () => {
  router.push('/management/projects')
}

// 编辑
const editShow = ref(false)

const handleProjectSaved = () => {
  editShow.value = false
  void load()
}

const handleLifecycleChanged = (_updated: Project) => {
  void load()
}

// 发布新建/编辑/删除
const releaseModalShow = ref(false)
const editingRelease = ref<ProjectRelease | null>(null)

const openAddRelease = () => {
  editingRelease.value = null
  releaseModalShow.value = true
}

const openEditRelease = (release: ProjectRelease) => {
  editingRelease.value = release
  releaseModalShow.value = true
}

const handleReleaseSaved = () => {
  releaseModalShow.value = false
  void load()
}

const removingRelease = ref<ProjectRelease | null>(null)
const removeReleaseLoading = ref(false)

const confirmRemoveRelease = async () => {
  if (!removingRelease.value) return
  removeReleaseLoading.value = true
  try {
    await deleteProjectRelease(projectId.value, removingRelease.value.id)
    removingRelease.value = null
    ElMessage.success(t('common.success'))
    void load()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    removeReleaseLoading.value = false
  }
}
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <div class="mgmt-back-row">
          <button class="btn-ghost mgmt-back-btn" @click="goBack">
            <ArrowLeft class="w-4 h-4" /> {{ $t('management.project.back_to_list') }}
          </button>
        </div>
        <h2>{{ project?.name ?? '' }}</h2>
        <p class="mgmt-subtitle">
          <span class="mgmt-code">{{ project?.code ?? '' }}</span>
          <template v-if="project?.customer"> · {{ project.customer }}</template>
          <template v-if="project?.organization"> · {{ project.organization }}</template>
        </p>
      </div>
      <AdminGuard :show-hint="false">
        <IconActionButton
          :icon="Pencil"
          :title="$t('management.common.edit')"
          :disabled="!project"
          @click="editShow = true"
        />
      </AdminGuard>
    </div>

    <AdminGuard />

    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <template v-else-if="project">
      <LifecycleTransitionPanel
        :project="project"
        :can-manage="isAdmin"
        @changed="handleLifecycleChanged"
      />

      <ProjectProductsPanel
        :project="project"
        :can-manage="isAdmin"
        @changed="load"
      />

      <ProjectRepoAssociationsPanel
        :project="project"
        :can-manage="isAdmin"
        @changed="load"
      />

      <ReleaseListSection
        :releases="project.releases"
        :can-manage="isAdmin"
        @add="openAddRelease"
        @edit="openEditRelease"
        @remove="removingRelease = $event"
      />
    </template>

    <div v-else class="mgmt-empty">{{ $t('management.common.empty') }}</div>

    <ProjectFormModal
      :show="editShow"
      :project="project"
      @saved="handleProjectSaved"
      @cancel="editShow = false"
    />

    <ReleaseFormModal
      :show="releaseModalShow"
      :project-id="projectId"
      :release="editingRelease"
      @saved="handleReleaseSaved"
      @cancel="releaseModalShow = false"
    />

    <ConfirmActionModal
      :show="Boolean(removingRelease)"
      :title="$t('management.project.release_delete_confirm', { no: removingRelease?.release_no || '' })"
      :message="$t('management.project.release_delete_confirm', { no: removingRelease?.release_no || '' })"
      :emphasis-label="$t('management.project.release_no')"
      :emphasis-value="removingRelease?.release_no || ''"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="removeReleaseLoading"
      @cancel="removingRelease = null"
      @confirm="confirmRemoveRelease"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-back-row {
  margin-bottom: 0.5rem;
}

.mgmt-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
}

.mgmt-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
  color: #64748b;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
