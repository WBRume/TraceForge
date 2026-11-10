/* Generated from Python contracts. Do not edit. */

export type ResourceCommand = (InitializeCommand | SkillsCommand | DocumentsCommand | SnapshotCommand | ProvisionCommand | MaterializeCommand | ProviderForkCommand | ReleaseCommand | RepositoryDetailsCommand | GeneratePatchCommand | ApplyPatchCommand)
export type ContractVersion = 2
export type OperationId = string
export type ResourceId = string
export type TaskId = string
export type PayloadHash = string
export type Kind = "initialize"
export type Payload = (InitializeClean | InitializeFetch | InitializeReset)
export type Action = "clean"
export type Protected = string[]
export type Action1 = "fetch"
export type RepositoryId = string
export type RelPath = string
export type Branch = string
export type Target = (string | null)
export type Action2 = "reset"
export type ContractVersion1 = 2
export type OperationId1 = string
export type ResourceId1 = string
export type TaskId1 = string
export type PayloadHash1 = string
export type Kind1 = "skills"
export type Payload1 = (SkillsReplace | SkillsManifest | SkillsTree | SkillsRead | SkillsWrite)
export type Action3 = "replace"
export type Path = string
export type Content = string
export type Sha256 = string
export type Files = File[]
export type Preserve = boolean
export type Action4 = "manifest"
export type Action5 = "tree"
export type Folder = string
export type Action6 = "read"
export type Folder1 = string
export type Path1 = string
export type Action7 = "write"
export type Folder2 = string
export type Path2 = string
export type Content1 = string
export type ContractVersion2 = 2
export type OperationId2 = string
export type ResourceId2 = string
export type TaskId2 = string
export type PayloadHash2 = string
export type Kind2 = "documents"
export type Payload2 = (DocumentsList | DocumentsRead | DocumentsSave)
export type Action8 = "list"
export type Roots = string[]
export type InitialCheckpoint = (string | null)
export type Action9 = "read"
export type Roots1 = string[]
export type InitialCheckpoint1 = (string | null)
export type Path3 = string
export type Section = ("plans" | "specs")
export type Action10 = "save"
export type Roots2 = string[]
export type InitialCheckpoint2 = (string | null)
export type Path4 = string
export type Section1 = ("plans" | "specs")
export type Content2 = string
export type ContractVersion3 = 2
export type OperationId3 = string
export type ResourceId3 = string
export type TaskId3 = string
export type PayloadHash3 = string
export type Kind3 = "snapshot"
export type Payload3 = (SnapshotCreate | SnapshotExists | SnapshotRestoreWorktree | SnapshotBackupProvider | SnapshotRestoreProvider | SnapshotRestoreProviderBackup | SnapshotForkDsh | SnapshotCleanupDsh | SnapshotCleanup)
export type Action11 = "create"
export type Provider = ("opencode" | "dsh")
export type SessionId = (string | null)
export type InitialCheckpoint3 = (string | null)
export type Action12 = "exists"
export type CheckpointRoot = string
export type Action13 = "restore_worktree"
export type CheckpointRoot1 = string
export type BackupPath = string
export type Action14 = "backup_provider"
export type CheckpointRoot2 = string
export type Provider1 = ("opencode" | "dsh")
export type SessionId1 = (string | null)
export type Action15 = "restore_provider"
export type CheckpointRoot3 = string
export type Action16 = "restore_provider_backup"
export type CheckpointRoot4 = string
export type Action17 = "fork_dsh"
export type CheckpointRoot5 = string
export type SessionId2 = string
export type Action18 = "cleanup_dsh"
export type CheckpointRoot6 = string
export type SessionId3 = string
export type Action19 = "cleanup"
export type CheckpointRoot7 = string
export type ContractVersion4 = 2
export type OperationId4 = string
export type ResourceId4 = string
export type TaskId4 = string
export type PayloadHash4 = string
export type Kind4 = "provision"
export type WorkspaceRoot = string
export type RepositoryId1 = string
export type LocalPath = string
export type ConfiguredGitUrl = string
export type RepoUrl = string
export type RepoName = string
export type RelPath1 = string
export type BranchName = string
export type Repositories = Repository[]
export type ContractVersion5 = 2
export type OperationId5 = string
export type ResourceId5 = string
export type TaskId5 = string
export type PayloadHash5 = string
export type Kind5 = "materialize"
export type Files1 = File[]
export type ContractVersion6 = 2
export type OperationId6 = string
export type ResourceId6 = string
export type TaskId6 = string
export type PayloadHash6 = string
export type Kind6 = "provider_fork"
export type SessionId4 = string
export type Drill = boolean
export type ContractVersion7 = 2
export type OperationId7 = string
export type ResourceId7 = string
export type TaskId7 = string
export type PayloadHash7 = string
export type Kind7 = "release"
export type ContractVersion8 = 2
export type OperationId8 = string
export type ResourceId8 = string
export type TaskId8 = string
export type PayloadHash8 = string
export type Kind8 = "repository_details"
export type ContractVersion9 = 2
export type OperationId9 = string
export type ResourceId9 = string
export type TaskId9 = string
export type PayloadHash9 = string
export type Kind9 = "generate_patch"
export type ContractVersion10 = 2
export type OperationId10 = string
export type ResourceId10 = string
export type TaskId10 = string
export type PayloadHash10 = string
export type Kind10 = "apply_patch"
export type WorkspaceRoot1 = string
export type RepositoryId2 = string
export type LocalPath1 = string
export type ConfiguredGitUrl1 = string
export type RepoSlug = string
export type Patch = string
export type Sha2561 = string
export type BaseCommitSha = string
export type BaseBranch = string
export type Repositories1 = PatchRepository[]

export interface InitializeCommand {
contract_version: ContractVersion
operation_id: OperationId
resource_id: ResourceId
task_id: TaskId
payload_hash: PayloadHash
kind: Kind
payload: Payload
}
export interface InitializeClean {
action: Action
protected: Protected
}
export interface InitializeFetch {
action: Action1
repository: RepositoryTarget
}
export interface RepositoryTarget {
repository_id: RepositoryId
rel_path: RelPath
branch: Branch
target?: Target
}
export interface InitializeReset {
action: Action2
repository: RepositoryTarget
}
export interface SkillsCommand {
contract_version: ContractVersion1
operation_id: OperationId1
resource_id: ResourceId1
task_id: TaskId1
payload_hash: PayloadHash1
kind: Kind1
payload: Payload1
}
export interface SkillsReplace {
action: Action3
files: Files
preserve?: Preserve
}
export interface File {
path: Path
content: Content
sha256: Sha256
}
export interface SkillsManifest {
action: Action4
}
export interface SkillsTree {
action: Action5
folder: Folder
}
export interface SkillsRead {
action: Action6
folder: Folder1
path: Path1
}
export interface SkillsWrite {
action: Action7
folder: Folder2
path: Path2
content: Content1
}
export interface DocumentsCommand {
contract_version: ContractVersion2
operation_id: OperationId2
resource_id: ResourceId2
task_id: TaskId2
payload_hash: PayloadHash2
kind: Kind2
payload: Payload2
}
export interface DocumentsList {
action: Action8
roots: Roots
initial_checkpoint?: InitialCheckpoint
}
export interface DocumentsRead {
action: Action9
roots: Roots1
initial_checkpoint?: InitialCheckpoint1
path: Path3
section: Section
}
export interface DocumentsSave {
action: Action10
roots: Roots2
initial_checkpoint?: InitialCheckpoint2
path: Path4
section: Section1
content: Content2
}
export interface SnapshotCommand {
contract_version: ContractVersion3
operation_id: OperationId3
resource_id: ResourceId3
task_id: TaskId3
payload_hash: PayloadHash3
kind: Kind3
payload: Payload3
}
export interface SnapshotCreate {
action: Action11
provider?: Provider
session_id?: SessionId
initial_checkpoint?: InitialCheckpoint3
}
export interface SnapshotExists {
action: Action12
checkpoint_root: CheckpointRoot
}
export interface SnapshotRestoreWorktree {
action: Action13
checkpoint_root: CheckpointRoot1
backup_path: BackupPath
}
export interface SnapshotBackupProvider {
action: Action14
checkpoint_root: CheckpointRoot2
provider: Provider1
session_id?: SessionId1
}
export interface SnapshotRestoreProvider {
action: Action15
checkpoint_root: CheckpointRoot3
}
export interface SnapshotRestoreProviderBackup {
action: Action16
checkpoint_root: CheckpointRoot4
}
export interface SnapshotForkDsh {
action: Action17
checkpoint_root: CheckpointRoot5
session_id: SessionId2
}
export interface SnapshotCleanupDsh {
action: Action18
checkpoint_root: CheckpointRoot6
session_id: SessionId3
}
export interface SnapshotCleanup {
action: Action19
checkpoint_root: CheckpointRoot7
}
export interface ProvisionCommand {
contract_version: ContractVersion4
operation_id: OperationId4
resource_id: ResourceId4
task_id: TaskId4
payload_hash: PayloadHash4
kind: Kind4
payload: Provision
}
export interface Provision {
workspace_root: WorkspaceRoot
repositories: Repositories
}
export interface Repository {
repository_id: RepositoryId1
local_path: LocalPath
configured_git_url: ConfiguredGitUrl
repo_url: RepoUrl
repo_name: RepoName
rel_path: RelPath1
branch_name: BranchName
}
export interface MaterializeCommand {
contract_version: ContractVersion5
operation_id: OperationId5
resource_id: ResourceId5
task_id: TaskId5
payload_hash: PayloadHash5
kind: Kind5
payload: Materialize
}
export interface Materialize {
files: Files1
}
export interface ProviderForkCommand {
contract_version: ContractVersion6
operation_id: OperationId6
resource_id: ResourceId6
task_id: TaskId6
payload_hash: PayloadHash6
kind: Kind6
payload: ProviderFork
}
export interface ProviderFork {
session_id: SessionId4
drill?: Drill
}
export interface ReleaseCommand {
contract_version: ContractVersion7
operation_id: OperationId7
resource_id: ResourceId7
task_id: TaskId7
payload_hash: PayloadHash7
kind: Kind7
payload: Contract
}
export interface Contract {

}
export interface RepositoryDetailsCommand {
contract_version: ContractVersion8
operation_id: OperationId8
resource_id: ResourceId8
task_id: TaskId8
payload_hash: PayloadHash8
kind: Kind8
payload: Contract
}
export interface GeneratePatchCommand {
contract_version: ContractVersion9
operation_id: OperationId9
resource_id: ResourceId9
task_id: TaskId9
payload_hash: PayloadHash9
kind: Kind9
payload: Contract
}
export interface ApplyPatchCommand {
contract_version: ContractVersion10
operation_id: OperationId10
resource_id: ResourceId10
task_id: TaskId10
payload_hash: PayloadHash10
kind: Kind10
payload: ApplyPatch
}
export interface ApplyPatch {
workspace_root: WorkspaceRoot1
repositories: Repositories1
}
export interface PatchRepository {
repository_id: RepositoryId2
local_path: LocalPath1
configured_git_url: ConfiguredGitUrl1
repo_slug: RepoSlug
patch: Patch
sha256: Sha2561
base_commit_sha: BaseCommitSha
base_branch: BaseBranch
}
