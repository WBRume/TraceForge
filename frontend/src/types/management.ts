export type ProductStatus = 'ACTIVE' | 'ARCHIVED'
export type ProductVersionStatus = 'PLANNED' | 'ACTIVE' | 'EOL'
export type RepositoryType = 'OOTB' | 'CUSTOM'
export type RepoRefType = 'BRANCH' | 'TAG'
export type OrgNodeType = 'PRODUCT_LINE' | 'PROJECT_GROUP'
export type ProjectLifecycleStatus = 'INITIATED' | 'DEVELOPING' | 'DELIVERING' | 'MAINTAINING' | 'RETIRED'
export type ReleaseStatus = 'DRAFT' | 'PUBLISHED' | 'RETIRED'
export type ReleaseRepoKind = 'OOTB' | 'CUSTOM'

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Product {
  id: string
  name: string
  code: string
  product_line: string | null
  description: string | null
  status: ProductStatus
  created_at: string
  updated_at: string | null
}

export interface VersionRepoBinding {
  id: string
  repository_id: string
  repository_name: string
  git_url: string | null
  repo_type: RepositoryType | null
  branch_name: string
  created_at: string
}

export interface ProductVersion {
  id: string
  product_id: string
  version_no: string
  status: ProductVersionStatus
  release_date: string | null
  description: string | null
  repo_bindings: VersionRepoBinding[]
  created_at: string
  updated_at: string | null
}

export interface ProductDetail extends Product {
  versions: ProductVersion[]
}

export interface Repository {
  id: string
  name: string
  git_url: string
  repo_type: RepositoryType
  default_branch: string
  org_node_id: string | null
  description: string | null
  last_synced_at: string | null
  branch_count: number
  tag_count: number
  created_at: string
  updated_at: string | null
}

export interface RepoRef {
  id: string
  ref_type: RepoRefType
  ref_name: string
  ref_sha: string | null
  synced_at: string
}

export interface RepoRefList {
  repository_id: string
  items: RepoRef[]
  total: number
  last_synced_at: string | null
}

export interface OrgNodeRepo {
  id: string
  name: string
  git_url: string
  repo_type: RepositoryType
}

export interface OrgTreeNode {
  id: string | null
  parent_id: string | null
  name: string
  node_type: OrgNodeType | 'UNASSIGNED'
  order_index: number
  repositories: OrgNodeRepo[]
  children: OrgTreeNode[]
}

export interface Project {
  id: string
  name: string
  code: string
  customer: string | null
  organization: string | null
  lifecycle_status: ProjectLifecycleStatus
  description: string | null
  created_at: string
  updated_at: string | null
}

export interface ProjectReleaseRepo {
  id: string
  repository_id: string
  repository_name: string | null
  git_url: string | null
  branch_name: string
  repo_kind: ReleaseRepoKind
}

export interface ProjectRelease {
  id: string
  project_id: string
  release_no: string
  name: string
  product_id: string | null
  product_name: string | null
  product_version_id: string | null
  product_version_no: string | null
  status: ReleaseStatus
  release_date: string | null
  notes: string | null
  created_at: string
  repos: ProjectReleaseRepo[]
}

export interface ProjectProductDep {
  id: string
  product_id: string
  product_name: string | null
  product_version_id: string | null
  product_version_no: string | null
}

export interface ProjectRepoAssociation {
  id: string
  repository_id: string
  repository_name: string | null
  git_url: string | null
  repo_type: RepositoryType | null
  branch_name: string | null
}

export interface ProjectDetail extends Project {
  releases: ProjectRelease[]
  product_deps: ProjectProductDep[]
  repo_associations: ProjectRepoAssociation[]
}

export interface ProjectRepoSetItem {
  repository_id: string
  repository_name: string
  git_url: string
  repo_type: RepositoryType
  default_branch: string
  branch_name: string
  repo_kind: 'OOTB' | 'CUSTOM'
}

export const LIFECYCLE_FLOW: Record<ProjectLifecycleStatus, ProjectLifecycleStatus | null> = {
  INITIATED: 'DEVELOPING',
  DEVELOPING: 'DELIVERING',
  DELIVERING: 'MAINTAINING',
  MAINTAINING: 'RETIRED',
  RETIRED: null,
}
