import { getSddDesktop } from '@/utils/runtime'
import { remoteUrlsMatch } from './localAgentUtils'

export type GitFetchRemote = { name: string; fetchUrl: string }

export async function getLocalGitRemotes(repoPath: string): Promise<GitFetchRemote[]> {
  const git = getSddDesktop()?.git
  if (!repoPath || !git) return []
  try {
    const remotes = git.getFetchRemotes
      ? await git.getFetchRemotes(repoPath)
      : [{ name: 'origin', fetchUrl: (await git.getRemoteUrl(repoPath)).remoteUrl }]
    return remotes.filter(remote => Boolean(remote.name && remote.fetchUrl))
  } catch {
    return []
  }
}

export function chooseGitRemote(
  remotes: GitFetchRemote[],
  options: { currentUrl?: string; preferredUrl?: string } = {},
): GitFetchRemote | undefined {
  const current = remotes.find(remote => remoteUrlsMatch(remote.fetchUrl, options.currentUrl))
  if (current) return current
  return remotes.find(remote => remote.name.toLowerCase() === 'origin')
    || remotes.find(remote => remoteUrlsMatch(remote.fetchUrl, options.preferredUrl))
    || remotes[0]
}
