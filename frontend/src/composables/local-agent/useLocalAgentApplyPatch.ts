import { createConflictReport, submitApplyResult } from '@/services/agentApi'
import type { AgentTask, ChangeProposal, ChangeProposalRepoPatch } from '@/types/agent'
import type { SddDesktopApi } from '@/types/sddDesktop'
import {
  createPatchBranchName,
  createRepoPatchBranchName,
  excerptText,
  normalizeRemoteUrl,
  remoteUrlsMatch,
} from './localAgentUtils'

export type ApplyPatchProgress = {
  step: string
  detail?: string
  repoName?: string
  level?: 'info' | 'success' | 'warning' | 'error'
}

export type ApplyPatchOptions = {
  desktop: SddDesktopApi
  task: AgentTask
  proposal: ChangeProposal
  repoPath: string
  patchText: string
  onProgress?: (event: ApplyPatchProgress) => void
}

export type ApplyRepoPatchOptions = {
  desktop: SddDesktopApi
  task: AgentTask
  proposal: ChangeProposal
  repoPatches: ChangeProposalRepoPatch[]
  repoPaths: Record<string, string>
  onProgress?: (event: ApplyPatchProgress) => void
}

const ensure = (condition: boolean, message: string) => {
  if (!condition) throw new Error(message)
}

const emit = (
  options: { onProgress?: (event: ApplyPatchProgress) => void },
  event: ApplyPatchProgress,
) => {
  options.onProgress?.(event)
}

const buildConflictExcerpt = (repo: ChangeProposalRepoPatch, branchName: string, conflictedFiles: string[], stderr: string): string => {
  return excerptText(
    [
      'Repository: ' + repo.repo_name,
      'Branch: ' + branchName,
      'Files: ' + (conflictedFiles.join(', ') || 'unknown'),
      '',
      stderr,
    ].join('\n'),
  )
}

const applySingleRepoPatch = async (options: {
  desktop: SddDesktopApi
  task: AgentTask
  proposal: ChangeProposal
  repo: ChangeProposalRepoPatch
  repoPath: string
  onProgress?: (event: ApplyPatchProgress) => void
}): Promise<{ status: 'applied' | 'conflict'; branchName: string }> => {
  const { desktop, task, proposal, repo, repoPath } = options
  const expectedRemote = repo.repo_url || proposal.base_repo_url || task.git_repo_url || ''
  ensure(Boolean(repoPath), '仓库 ' + repo.repo_name + ' 未绑定本地路径')
  ensure(Boolean(repo.patch_text.trim()), '仓库 ' + repo.repo_name + ' 的补丁内容为空')

  emit(options, { step: 'validate-repo', repoName: repo.repo_name, detail: '校验本地 Git 仓库' })
  const repoValidation = await desktop.git.validateGitRepo(repoPath)
  ensure(repoValidation.ok, repoValidation.stderr || '所选目录不是 Git 仓库')

  const remote = await desktop.git.getRemoteUrl(repoPath)
  ensure(
    remoteUrlsMatch(remote.remoteUrl, expectedRemote),
    '本地仓库 remote.origin.url 与云端仓库不一致',
  )

  const status = await desktop.git.getStatus(repoPath)
  ensure(status.isClean, '本地仓库存在未提交修改，请先提交或清理后再应用补丁')

  emit(options, { step: 'fetch', repoName: repo.repo_name, detail: 'git fetch origin' })
  await desktop.git.fetchOrigin(repoPath)

  emit(options, { step: 'checkout-base', repoName: repo.repo_name, detail: 'git checkout ' + repo.base_branch })
  await desktop.git.checkoutBranch(repoPath, repo.base_branch)

  emit(options, { step: 'pull', repoName: repo.repo_name, detail: 'git pull --ff-only origin ' + repo.base_branch })
  await desktop.git.pullFfOnly(repoPath, repo.base_branch)

  const baseHead = await desktop.git.getHeadSha(repoPath)
  ensure(
    baseHead.headSha === repo.base_commit_sha,
    '仓库 ' + repo.repo_name + ' 本地主干 HEAD(' + baseHead.headSha + ') 与补丁 base_commit_sha(' + repo.base_commit_sha + ') 不一致',
  )

  const isLegacySingleRepo = repo.repo_slug === 'repo'
  const branchName = isLegacySingleRepo
    ? createPatchBranchName(task.id, proposal.patch_set_no)
    : createRepoPatchBranchName(task.id, proposal.patch_set_no, repo.repo_slug)
  emit(options, { step: 'create-branch', repoName: repo.repo_name, detail: 'git checkout -b ' + branchName })
  await desktop.git.createLocalBranch(repoPath, branchName)

  emit(options, { step: 'apply', repoName: repo.repo_name, detail: 'git apply --3way' })
  const applyResult = await desktop.git.applyPatchWithThreeWay(repoPath, repo.patch_text)
  let localHead: { headSha: string } | null = null
  try {
    localHead = await desktop.git.getHeadSha(repoPath)
  } catch {
    localHead = { headSha: baseHead.headSha }
  }

  if (applyResult.ok) {
    emit(options, { step: 'done', repoName: repo.repo_name, detail: '补丁已应用到本地分支 ' + branchName, level: 'success' })
    return { status: 'applied', branchName }
  }

  const stderr = applyResult.stderr || 'git apply --3way failed'
  emit(options, { step: 'conflict', repoName: repo.repo_name, detail: '仓库 ' + repo.repo_name + ' 应用冲突', level: 'error' })
  await createConflictReport({
    taskId: task.id,
    proposalId: proposal.id,
    baseCommitSha: repo.base_commit_sha,
    localHeadSha: localHead ? localHead.headSha : null,
    conflictedFiles: applyResult.conflictedFiles,
    gitApplyStderr: stderr,
    conflictExcerpt: buildConflictExcerpt(repo, branchName, applyResult.conflictedFiles, stderr),
  })
  return { status: 'conflict', branchName }
}

export const applyProposalRepoPatches = async (options: ApplyRepoPatchOptions): Promise<{ status: 'applied' | 'conflict' }> => {
  const { desktop, task, proposal, repoPatches, onProgress } = options
  ensure(repoPatches.length > 0, '没有可应用的仓库补丁')

  const appliedBranches: string[] = []
  for (const repo of repoPatches) {
    const remoteKey = normalizeRemoteUrl(repo.repo_url || '')
    const repoPath = options.repoPaths[remoteKey] || ''
    try {
      const result = await applySingleRepoPatch({
        desktop,
        task,
        proposal,
        repo,
        repoPath,
        onProgress,
      })
      if (result.status === 'applied') {
        appliedBranches.push(repo.repo_name + ':' + result.branchName)
        continue
      }
      // Conflict in one repository fails the whole patch set.
      await submitApplyResult({
        taskId: task.id,
        proposalId: proposal.id,
        status: 'conflict',
        baseCommitSha: proposal.base_commit_sha,
        localHeadSha: null,
        message: 'Conflict applying repository patches: ' + repo.repo_name,
      })
      emit(options, { step: 'conflict', detail: '部分仓库补丁应用冲突，已上传冲突报告', level: 'error' })
      return { status: 'conflict' }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error)
      try {
        await submitApplyResult({
          taskId: task.id,
          proposalId: proposal.id,
          status: 'conflict',
          baseCommitSha: proposal.base_commit_sha,
          localHeadSha: null,
          message: 'Failed applying repository patches: ' + message,
        })
      } catch {
        // Result submission is best-effort during failure handling.
      }
      emit(options, { step: 'error', repoName: repo.repo_name, detail: message, level: 'error' })
      throw error
    }
  }

  await submitApplyResult({
    taskId: task.id,
    proposalId: proposal.id,
    status: 'applied',
    baseCommitSha: proposal.base_commit_sha,
    localHeadSha: null,
    message: 'Applied locally: ' + appliedBranches.join('; '),
  })
  emit(options, { step: 'done', detail: '全部仓库补丁已应用到本地分支', level: 'success' })
  return { status: 'applied' }
}

export const applyProposalPatch = async (options: ApplyPatchOptions): Promise<{ status: 'applied' | 'conflict' }> => {
  const { desktop, task, proposal, repoPath, patchText } = options
  const expectedRemote = proposal.base_repo_url || task.git_repo_url || ''
  const repoPatch: ChangeProposalRepoPatch = {
    id: 'legacy-' + proposal.id,
    proposal_id: proposal.id,
    repository_id: null,
    repo_url: expectedRemote || null,
    repo_name: 'repository',
    repo_slug: 'repo',
    base_branch: proposal.base_branch,
    base_commit_sha: proposal.base_commit_sha,
    cloud_task_branch: proposal.cloud_task_branch,
    cloud_head_sha: proposal.cloud_head_sha || null,
    changed_files_count: proposal.changed_files_count,
    insertions: proposal.insertions,
    deletions: proposal.deletions,
    patch_asset_id: proposal.patch_asset_id || null,
    patch_asset_version_id: proposal.patch_asset_version_id || null,
    created_at: proposal.created_at,
    patch_text: patchText,
  }
  return applyProposalRepoPatches({
    desktop,
    task,
    proposal,
    repoPatches: [repoPatch],
    repoPaths: { [normalizeRemoteUrl(expectedRemote)]: repoPath },
    onProgress: options.onProgress,
  })
}
