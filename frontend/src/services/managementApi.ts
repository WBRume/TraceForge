import api from '@/utils/api'
import type {
  Paginated,
  Product,
  ProductDetail,
  Project,
  ProjectDetail,
  ProjectLifecycleStatus,
  ProjectRelease,
  ProjectRepoSetItem,
  RemoteRefsPayload,
  RepoGroupTreeNode,
  Repository,
  RepositoryType,
} from '@/types/management'

// ── Products ───────────────────────────────────────────────────────────────

export const listProducts = async (params: {
  keyword?: string
  status?: string
  page?: number
  page_size?: number
} = {}): Promise<Paginated<Product>> => {
  const res = await api.get('/management/products', { params })
  return res.data as Paginated<Product>
}

export const getProduct = async (productId: string): Promise<ProductDetail> => {
  const res = await api.get('/management/products/' + productId)
  return res.data as ProductDetail
}

export const createProduct = async (payload: {
  name: string
  code: string
  product_line?: string | null
  version_no?: string
  release_date?: string | null
  description?: string | null
  status?: string
}): Promise<Product> => {
  const res = await api.post('/management/products', payload)
  return res.data as Product
}

export const updateProduct = async (productId: string, payload: Partial<{
  name: string
  code: string
  product_line: string | null
  version_no: string
  release_date: string | null
  description: string | null
  status: string
}>): Promise<Product> => {
  const res = await api.put('/management/products/' + productId, payload)
  return res.data as Product
}

export const deleteProduct = async (productId: string): Promise<void> => {
  await api.delete('/management/products/' + productId)
}

export const bindProductRepo = async (productId: string, payload: {
  repository_id: string
  ref_type: string
  ref_name: string
}): Promise<{ id: string; product_id: string; repository_id: string; ref_type: string; ref_name: string }> => {
  const res = await api.post('/management/products/' + productId + '/repos', payload)
  return res.data
}

export const unbindProductRepo = async (productId: string, repositoryId: string): Promise<void> => {
  await api.delete('/management/products/' + productId + '/repos/' + repositoryId)
}

// ── Repositories / repo groups ────────────────────────────────────────────

export const listRepositories = async (params: {
  keyword?: string
  repo_type?: RepositoryType | ''
  group_id?: string | null
  page?: number
  page_size?: number
} = {}): Promise<Paginated<Repository>> => {
  const res = await api.get('/management/repositories', { params })
  return res.data as Paginated<Repository>
}

export const getRepository = async (repositoryId: string): Promise<Repository> => {
  const res = await api.get('/management/repositories/' + repositoryId)
  return res.data as Repository
}

export const createRepository = async (payload: {
  name: string
  git_url: string
  repo_type?: string
  default_branch?: string
  group_id?: string | null
  description?: string | null
}): Promise<Repository> => {
  const res = await api.post('/management/repositories', payload)
  return res.data as Repository
}

export const updateRepository = async (repositoryId: string, payload: Partial<{
  name: string
  git_url: string
  repo_type: string
  default_branch: string
  group_id: string | null
  description: string | null
}>): Promise<Repository> => {
  const res = await api.put('/management/repositories/' + repositoryId, payload)
  return res.data as Repository
}

export const deleteRepository = async (repositoryId: string): Promise<void> => {
  await api.delete('/management/repositories/' + repositoryId)
}

export const validateRepositoryAccess = async (gitUrl: string): Promise<RemoteRefsPayload> => {
  const res = await api.post('/management/repositories/validate-access', { git_url: gitUrl })
  return res.data as RemoteRefsPayload
}

export const validateRepositoryRef = async (repositoryId: string, payload: {
  ref_type: string
  ref_name: string
}): Promise<{ repository_id: string; ref_type: string; ref_name: string; exists: boolean }> => {
  const res = await api.post('/management/repositories/' + repositoryId + '/validate-ref', payload)
  return res.data
}

export const moveRepositoryToGroup = async (repositoryId: string, groupId: string | null): Promise<Repository> => {
  const res = await api.post('/management/repo-groups/repositories/' + repositoryId + '/move', { group_id: groupId })
  return res.data as Repository
}

export const getRepoGroupTree = async (): Promise<{ items: RepoGroupTreeNode[] }> => {
  const res = await api.get('/management/repo-groups/tree')
  return res.data
}

export const createRepoGroup = async (payload: {
  name: string
  parent_id?: string | null
  order_index?: number
}): Promise<{ id: string; parent_id: string | null; name: string; order_index: number }> => {
  const res = await api.post('/management/repo-groups', payload)
  return res.data
}

export const updateRepoGroup = async (groupId: string, payload: {
  name?: string
  parent_id?: string | null
  order_index?: number
}): Promise<{ id: string; parent_id: string | null; name: string; order_index: number }> => {
  const res = await api.put('/management/repo-groups/' + groupId, payload)
  return res.data
}

export const deleteRepoGroup = async (groupId: string): Promise<void> => {
  await api.delete('/management/repo-groups/' + groupId)
}

// ── Projects ───────────────────────────────────────────────────────────────

export const listProjects = async (params: {
  keyword?: string
  lifecycle_status?: string
  page?: number
  page_size?: number
} = {}): Promise<Paginated<Project>> => {
  const res = await api.get('/management/projects', { params })
  return res.data as Paginated<Project>
}

export const getProject = async (projectId: string): Promise<ProjectDetail> => {
  const res = await api.get('/management/projects/' + projectId)
  return res.data as ProjectDetail
}

export const createProject = async (payload: {
  name: string
  code: string
  customer?: string | null
  organization?: string | null
  description?: string | null
}): Promise<Project> => {
  const res = await api.post('/management/projects', payload)
  return res.data as Project
}

export const updateProject = async (projectId: string, payload: Partial<{
  name: string
  code: string
  customer: string | null
  organization: string | null
  description: string | null
}>): Promise<Project> => {
  const res = await api.put('/management/projects/' + projectId, payload)
  return res.data as Project
}

export const deleteProject = async (projectId: string): Promise<void> => {
  await api.delete('/management/projects/' + projectId)
}

export const transitionProjectLifecycle = async (projectId: string, targetStatus: ProjectLifecycleStatus): Promise<Project> => {
  const res = await api.post('/management/projects/' + projectId + '/lifecycle/transition', {
    target_status: targetStatus,
  })
  return res.data as Project
}

export const getProjectRepoSet = async (projectId: string, productIds: string[]): Promise<{ project_id: string; repositories: ProjectRepoSetItem[] }> => {
  const res = await api.get('/management/projects/' + projectId + '/repo-set', {
    params: { product_ids: productIds.length > 0 ? productIds : undefined },
  })
  return res.data
}

export const addProjectProduct = async (projectId: string, productId: string): Promise<{ id: string; project_id: string; product_id: string }> => {
  const res = await api.post('/management/projects/' + projectId + '/products', { product_id: productId })
  return res.data
}

export const removeProjectProduct = async (projectId: string, productId: string): Promise<void> => {
  await api.delete('/management/projects/' + projectId + '/products/' + productId)
}

export const transitionProjectProductDelivery = async (projectId: string, productId: string, targetStatus: ProjectLifecycleStatus): Promise<{ id: string; delivery_status: string }> => {
  const res = await api.post('/management/projects/' + projectId + '/products/' + productId + '/transition', {
    target_status: targetStatus,
  })
  return res.data
}

export const createProjectRelease = async (projectId: string, payload: {
  release_no: string
  name: string
  product_id?: string | null
  status?: string
  release_date?: string | null
  notes?: string | null
  custom_repos?: { repository_id: string; ref_type: string; ref_name: string }[]
}): Promise<ProjectRelease> => {
  const res = await api.post('/management/projects/' + projectId + '/releases', payload)
  return res.data as ProjectRelease
}

export const updateProjectRelease = async (projectId: string, releaseId: string, payload: Partial<{
  release_no: string
  name: string
  status: string
  release_date: string | null
  notes: string | null
}>): Promise<ProjectRelease> => {
  const res = await api.put('/management/projects/' + projectId + '/releases/' + releaseId, payload)
  return res.data as ProjectRelease
}

export const deleteProjectRelease = async (projectId: string, releaseId: string): Promise<void> => {
  await api.delete('/management/projects/' + projectId + '/releases/' + releaseId)
}
