import type { BuildTrigger } from '../api/types'

// How a build was started, as the Builds list and a build's page say it.
export const TRIGGER_LABEL: Record<BuildTrigger, string> = {
  console: 'Console',
  api: 'API',
  push: 'Push',
  tag: 'Tag push',
  schedule: 'Schedule',
}

/** The label for a build's trigger; builds from before triggers were recorded are console builds. */
export function triggerLabel(trigger: BuildTrigger | null | undefined): string {
  return TRIGGER_LABEL[trigger ?? 'console'] ?? String(trigger)
}

/** The short form of a commit id shown in lists (the full id is copied). */
export function shortCommit(sha: string): string {
  return sha.slice(0, 7)
}
