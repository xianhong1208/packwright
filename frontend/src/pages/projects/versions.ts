// A project's builds, by the version they were of. Kept pure so the grouping and
// the "already built" check are tested.
import type { BuildBrief, ProjectSummary } from '../../api/types'

export interface VersionGroup {
  /** null: builds made without a version. */
  version: string | null
  /** Newest first. */
  builds: BuildBrief[]
  lastPassed: BuildBrief | null
}

/** Group a project's builds (newest first) by version, the most recently built version first. */
export function groupByVersion(history: BuildBrief[]): VersionGroup[] {
  const groups = new Map<string | null, BuildBrief[]>()
  for (const b of history) {
    const key = b.version || null
    groups.set(key, [...(groups.get(key) ?? []), b])
  }
  return [...groups.entries()].map(([version, builds]) => ({
    version,
    builds,
    lastPassed: builds.find((b) => b.status === 'completed') ?? null,
  }))
}

/** The most recent passed build of exactly this version, if there is one. */
export function passedBefore(history: BuildBrief[], version: string): BuildBrief | null {
  const v = version.trim()
  if (!v) return null
  return history.find((b) => b.version === v && b.status === 'completed') ?? null
}

/** A source as one short line: the folder's last two parts, or host/path of a Git URL. */
export function sourceLabel(p: Pick<ProjectSummary, 'source_type' | 'source'>): string {
  if (p.source_type === 'git') return p.source.replace(/^https?:\/\//, '').replace(/\.git$/, '')
  const parts = p.source.split('/').filter(Boolean)
  return parts.length > 2 ? `…/${parts.slice(-2).join('/')}` : p.source
}
