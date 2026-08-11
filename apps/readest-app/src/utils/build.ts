export interface BuildInfo {
  repo: string;
  commit: string;
}

/**
 * Provenance of this build, shown in About so an installed app can be traced
 * back to the exact source it came from. The values are inlined at build time
 * by next.config.mjs (from CI env, falling back to git); a dev server has
 * neither, hence the null.
 */
export const getBuildInfo = (): BuildInfo | null => {
  const repo = process.env['NEXT_PUBLIC_BUILD_REPO'];
  const commit = process.env['NEXT_PUBLIC_BUILD_COMMIT'];
  if (!repo || !commit) return null;
  return { repo, commit };
};

export const getBuildCommitUrl = ({ repo, commit }: BuildInfo): string =>
  `https://github.com/${repo}/commit/${commit.replace(/-dirty$/, '')}`;
