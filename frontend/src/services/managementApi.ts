import api from '@/utils/api'
import type {
  OrgTreeNode,
  Paginated,
  Product,
  ProductDetail,
  ProductVersion,
  Project,
  ProjectDetail,
  ProjectLifecycleStatus,
  ProjectRelease,
  ProjectRepoSetItem,
  RepoRefList,
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
  description: string | null
  status: string
}>): Promise<Product> => {
  const res = await api.put('/management/products/' + productId, payload)
  return res.data as Product
}

export const deleteProduct = async (productId: string): Promise<void> => {
  await api.delete('/management/products/' + productId)
}

export const createProductVersion = async (productId: string, payload: {
  version_no: string
  status?: string
  release_date?: string | null
  description?: string | null
}): Promise<ProductVersion> => {
  const res = await api.post('/management/products/' + productId + '/versions', payload)
  return res.data as ProductVersion
}

export const updateProductVersion = async (productId: string, versionId: string, payload: Partial<{
  version_no: string
  status: string
  release_date: string | null
  description: string | null
}>): Promise<ProductVersion> => {
  const res = await api.put('/management/products/' + productId + '/versions/' + versionId, payload)
  return res.data as ProductVersion
}

export const deleteProductVersion = async (productId: string, versionId: string): Promise<void> => {
  await api.delete('/management/products/' + productId + '/versions/' + versionId)
}

export const bindVersionRepo = async (productId: string, versionId: string, payload: {
  repository_id: string
  branch_name: string
}): Promise<{ id: string; product_version_id: string; repository_id: string; branch_name: string }> => {
  const res = await api.post('/management/products/' + productId + '/versions/' + versionId + '/repos', payload)
  return res.data
}

export const unbindVersionRepo = async (productId: string, versionId: string, repositoryId: string): Promise<void> => {
  await api.delete('/management/products/' + productId + '/versions/' + versionId + '/repos/' + repositoryId)
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

export const getProjectRepoSet = async (projectId: string): Promise<{ project_id: string; repositories: ProjectRepoSetItem[] }> => {
  const res = await api.get('/management/projects/' + projectId + '/repo-set')
  return res.data
}

export const createProjectRelease = async (projectId: string, payload: {
  release_no: string
  name: string
  product_id?: string | null
  product_version_id?: string | null
  status?: string
  release_date?: string | null
  notes?: string | null
  custom_repos?: { repository_id: string; branch_name: string }[]
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

export const addProjectProductDep = async (projectId: string, payload: {
  product_id: string
  product_version_id?: string | null
}): Promise<{ id: string; project_id: string; product_id: string; product_version_id: string | null }> => {
  const res = await api.post('/management/projects/' + projectId + '/product-deps', payload)
  return res.data
}

export const updateProjectProductDep = async (projectId: string, productId: string, payload: {
  product_version_id?: string | null
}): Promise<{ id: string; project_id: string; product_id: string; product_version_id: string | null }> => {
  const res = await api.put('/management/projects/' + projectId + '/product-deps/' + productId, payload)
  return res.data
}

export const removeProjectProductDep = async (projectId: string, productId: string): Promise<void> => {
  await api.delete('/management/projects/' + projectId + '/product-deps/' + productId)
}

export const associateProjectRepo = async (projectId: string, payload: {
  repository_id: string
  branch_name?: string | null
}): Promise<{ id: string; project_id: string; repository_id: string; branch_name: string | null }> => {
  const res = await api.post('/management/projects/' + projectId + '/repos', payload)
  return res.data
}

export const dissociateProjectRepo = async (projectId: string, repositoryId: string): Promise<void> => {
  await api.delete('/management/projects/' + projectId + '/repos/' + repositoryId)
}

// ── Repositories ───────────────────────────────────────────────────────────

export const listRepositories = async (params: {
  keyword?: string
  repo_type?: RepositoryType | ''
  org_node_id?: string
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
  org_node_id?: string | null
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
  org_node_id: string | null
  description: string | null
}>): Promise<Repository> => {
  const res = await api.put('/management/repositories/' + repositoryId, payload)
  return res.data as Repository
}

export const deleteRepository = async (repositoryId: string): Promise<void> => {
  await api.delete('/management/repositories/' + repositoryId)
}

export const listRepositoryRefs = async (repositoryId: string, refType?: 'branch' | 'tag' | ''): Promise<RepoRefList> => {
  const res = await api.get('/management/repositories/' + repositoryId + '/refs', {
    params: refType ? { ref_type: refType } : undefined,
  })
  return res.data as RepoRefList
}

export const syncRepositoryRefs = async (repositoryId: string): Promise<{ job_id: string; job_type: string; status: string }> => {
  const res = await api.post('/management/repositories/' + repositoryId + '/sync')
  return res.data
}

export const validateRepositoryAccess = async (gitUrl: string): Promise<{
  git_url: string
  accessible: boolean
  branch_count: number
  tag_count: number
  branches: string[]
  tags: string[]
}> => {
  const res = await api.post('/management/repositories/validate-access', { git_url: gitUrl })
  return res.data
}

export const validateRepositoryBranch = async (repositoryId: string, branchName: string): Promise<{
  repository_id: string
  branch_name: string
  exists: boolean
}> => {
  const res = await api.post('/management/repositories/' + repositoryId + '/validate-branch', { branch_name: branchName })
  return res.data
}

// ── Org tree ───────────────────────────────────────────────────────────────

export const getOrgTree = async (): Promise<{ items: OrgTreeNode[] }> => {
  const res = await api.get('/management/org/tree')
  return res.data
}

export const createOrgNode = async (payload: {
  parent_id?: string | null
  name: string
  node_type: string
  order_index?: number
}): Promise<{ id: string; parent_id: string | null; name: string; node_type: string; order_index: number }> => {
  const res = await api.post('/management/org/nodes', payload)
  return res.data
}

export const updateOrgNode = async (nodeId: string, payload: {
  parent_id?: string | null
  name?: string
  order_index?: number
}): Promise<{ id: string; parent_id: string | null; name: string; node_type: string; order_index: number }> => {
  const res = await api.put('/management/org/nodes/' + nodeId, payload)
  return res.data
}

export const deleteOrgNode = async (nodeId: string): Promise<void> => {
  await api.delete('/management/org/nodes/' + nodeId)
}

export const moveRepositoryToNode = async (repositoryId: string, orgNodeId: string | null): Promise<Repository> => {
  const res = await api.post('/management/org/repositories/' + repositoryId + '/move', { org_node_id: orgNodeId })
  return res.data as Repository
}
