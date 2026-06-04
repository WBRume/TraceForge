import { createConflictReport, submitApplyResult } from '@/services/agentApi'
import type { AgentTask, ChangeProposal } from '@/types/agent'
import type { SddDesktopApi } from '@/types/sddDesktop'
import { createPatchBranchName, excerptText, remoteUrlsMatch } from './localAgentUtils'

export type ApplyPatchProgress = {
  step: string
  detail?: string
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

const ensure = (condition: boolean, message: string) => {
  if (!condition) throw new Error(message)
}

const emit = (options: ApplyPatchOptions, event: ApplyPatchProgress) => {
  options.onProgress?.(event)
}

export const applyProposalPatch = async (options: ApplyPatchOptions): Promise<{ status: 'applied' | 'conflict' }> => {
  const { desktop, task, proposal, repoPath, patchText } = options
  const expectedRemote = proposal.base_repo_url || task.git_repo_url || ''
  ensure(Boolean(repoPath), '请先绑定本地仓库')
  ensure(Boolean(patchText.trim()), '补丁内容为空')

  emit(options, { step: 'validate-repo', detail: '校验本地 Git 仓库' })
  const repoValidation = await desktop.git.validateGitRepo(repoPath)
  ensure(repoValidation.ok, repoValidation.stderr || '所选目录不是 Git 仓库')

  const remote = await desktop.git.getRemoteUrl(repoPath)
  ensure(remoteUrlsMatch(remote.remoteUrl, expectedRemote), '本地仓库 remote.origin.url 与云端仓库不一致')

  const status = await desktop.git.getStatus(repoPath)
  ensure(status.isClean, '本地仓库存在未提交修改，请先提交或清理后再应用补丁')

  emit(options, { step: 'fetch', detail: 'git fetch origin' })
  await desktop.git.fetchOrigin(repoPath)

  emit(options, { step: 'checkout-base', detail: `git checkout ${proposal.base_branch}` })
  await desktop.git.checkoutBranch(repoPath, proposal.base_branch)

  emit(options, { step: 'pull', detail: `git pull --ff-only origin ${proposal.base_branch}` })
  await desktop.git.pullFfOnly(repoPath, proposal.base_branch)

  const baseHead = await desktop.git.getHeadSha(repoPath)
  ensure(
    baseHead.headSha === proposal.base_commit_sha,
    `本地主干 HEAD(${baseHead.headSha}) 与变更提案 base_commit_sha(${proposal.base_commit_sha}) 不一致`,
  )

  const branchName = createPatchBranchName(task.id, proposal.patch_set_no)
  emit(options, { step: 'create-branch', detail: `git checkout -b ${branchName}` })
  await desktop.git.createLocalBranch(repoPath, branchName)

  emit(options, { step: 'apply', detail: 'git apply --3way' })
  const applyResult = await desktop.git.applyPatchWithThreeWay(repoPath, patchText)
  const localHead = await desktop.git.getHeadSha(repoPath).catch(() => ({ headSha: baseHead.headSha }))

  if (applyResult.ok) {
    await submitApplyResult({
      taskId: task.id,
      proposalId: proposal.id,
      status: 'applied',
      baseCommitSha: proposal.base_commit_sha,
      localHeadSha: localHead.headSha,
      message: `Applied locally on ${branchName}`,
    })
    emit(options, { step: 'done', detail: '补丁已应用到本地分支', level: 'success' })
    return { status: 'applied' }
  }

  const stderr = applyResult.stderr || 'git apply --3way failed'
  const conflictExcerpt = excerptText(
    [
      `Branch: ${branchName}`,
      `文件：${applyResult.conflictedFiles.join(', ') || '未知'}`,
      '',
      stderr,
    ].join('\n'),
  )

  await submitApplyResult({
    taskId: task.id,
    proposalId: proposal.id,
    status: 'conflict',
    baseCommitSha: proposal.base_commit_sha,
    localHeadSha: localHead.headSha,
    message: conflictExcerpt,
  })
  await createConflictReport({
    taskId: task.id,
    proposalId: proposal.id,
    baseCommitSha: proposal.base_commit_sha,
    localHeadSha: localHead.headSha,
    conflictedFiles: applyResult.conflictedFiles,
    gitApplyStderr: stderr,
    conflictExcerpt,
  })
  emit(options, { step: 'conflict', detail: '补丁应用发生冲突，已上传冲突报告', level: 'error' })
  return { status: 'conflict' }
}
