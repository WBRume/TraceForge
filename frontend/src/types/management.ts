export type ProductStatus = 'ACTIVE' | 'ARCHIVED'
export type ProductType = 'OOTB' | 'CUSTOM'
export type ProductVersionStatus = 'PLANNED' | 'ACTIVE' | 'EOL'
export type RepositoryType = 'OOTB' | 'CUSTOM'
export type RepoRefType = 'BRANCH' | 'TAG'
export type ProjectLifecycleStatus = 'INITIATED' | 'DEVELOPING' | 'DELIVERING' | 'MAINTAINING' | 'RETIRED'
export type ReleaseStatus = 'DRAFT' | 'PUBLISHED' | 'RETIRED'
export type ReleaseRepoKind = 'OOTB' | 'CUSTOM'

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ProductBaseRepo {
  id: string
  product_id: string
  repository_id: string
  repository_name: string
  git_url: string | null
  repo_type: RepositoryType | null
  default_branch: string | null
  created_at: string
}

export interface ProductRepoBinding {
  id: string
  repository_id: string
  repository_name: string
  git_url: string | null
  repo_type: RepositoryType | null
  ref_type: RepoRefType
  ref_name: string
  created_at: string
}

export interface ProductVersion {
  id: string
  product_id: string
  version_no: string
  status: ProductVersionStatus
  release_date: string | null
  description: string | null
  baseline_product_version_id: string | null
  baseline_version_no: string | null
  baseline_product_name: string | null
  created_at: string
  updated_at: string | null
}

export interface EffectiveRepoBinding extends ProductRepoBinding {
  source: 'baseline' | 'custom' | 'custom_override'
  default_branch: string | null
}

export interface ProductVersionDetail extends ProductVersion {
  repo_bindings: ProductRepoBinding[]
  effective_repo_bindings: EffectiveRepoBinding[]
}

export interface Product {
  id: string
  name: string
  code: string
  product_line: string | null
  version_no: string
  release_date: string | null
  description: string | null
  status: ProductStatus
  product_type: ProductType
  baseline_product_id: string | null
  baseline_product_name: string | null
  created_at: string
  updated_at: string | null
  /** Present when listProducts is called with include_versions=true. */
  versions?: ProductVersion[]
}

export interface ProductDetail extends Product {
  base_repos: ProductBaseRepo[]
  versions: ProductVersionDetail[]
}

export interface Repository {
  id: string
  name: string
  git_url: string
  repo_type: RepositoryType
  default_branch: string
  group_id: string | null
  group_name: string | null
  description: string | null
  created_at: string
  updated_at: string | null
}

export interface RepoGroupRepo {
  id: string
  name: string
  git_url: string
  repo_type: RepositoryType
}

export interface RepoGroupTreeNode {
  id: string | null
  parent_id: string | null
  name: string
  order_index: number
  repositories: RepoGroupRepo[]
  children: RepoGroupTreeNode[]
}

export interface Project {
  id: string
  name: string
  code: string
  customer: string | null
  organization: string | null
  lifecycle_status: ProjectLifecycleStatus
  description: string | null
  product_count: number | null
  created_at: string
  updated_at: string | null
}

export interface ProjectProduct {
  id: string
  project_id: string
  product_id: string
  product_version_id: string | null
  product_name: string | null
  product_code: string | null
  product_version_no: string | null
  delivery_status: ProjectLifecycleStatus
  created_at: string
}

export interface ProjectReleaseRepo {
  id: string
  repository_id: string
  repository_name: string | null
  git_url: string | null
  ref_type: RepoRefType
  ref_name: string
  repo_kind: ReleaseRepoKind
}

export interface ProjectRelease {
  id: string
  project_id: string
  release_no: string
  name: string
  product_id: string | null
  product_name: string | null
  product_version_no: string | null
  status: ReleaseStatus
  release_date: string | null
  notes: string | null
  created_at: string
  repos: ProjectReleaseRepo[]
}

export interface ProjectDetail extends Project {
  releases: ProjectRelease[]
  products: ProjectProduct[]
}

export interface ProjectRepoSetItem {
  repository_id: string
  repository_name: string
  git_url: string
  repo_type: RepositoryType
  default_branch: string
  ref_type: RepoRefType
  ref_name: string
  branch_name: string
  repo_kind: 'OOTB' | 'CUSTOM'
}

export interface RemoteRefsPayload {
  git_url: string
  accessible: boolean
  branches: string[]
  tags: string[]
  branch_count?: number
  tag_count?: number
}

export const LIFECYCLE_FLOW: Record<ProjectLifecycleStatus, ProjectLifecycleStatus | null> = {
  INITIATED: 'DEVELOPING',
  DEVELOPING: 'DELIVERING',
  DELIVERING: 'MAINTAINING',
  MAINTAINING: 'RETIRED',
  RETIRED: null,
}

export const LIFECYCLE_PREV: Record<ProjectLifecycleStatus, ProjectLifecycleStatus | null> = {
  INITIATED: null,
  DEVELOPING: 'INITIATED',
  DELIVERING: 'DEVELOPING',
  MAINTAINING: 'DELIVERING',
  RETIRED: 'MAINTAINING',
}
