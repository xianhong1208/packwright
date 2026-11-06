import type { BuildResult } from '../../api/types'

// Plain-language names for the stage a build was in, keyed by the values the
// backend writes (`task.stage`, `result.failed_stage`). A key missing here shows
// up raw in the UI, so new backend stages belong here too.
export const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued (waiting for a build slot)',
  frontend: 'Frontend (installing dependencies and running the build command)',
  preflight: 'Preflight (checking paths, the Python version and the dependency environment)',
  compile: 'Compile (Nuitka running)',
  bundle: 'Bundle (copying dependencies and data directories)',
  verify: 'Verify (smoke-testing the built binary)',
  docker: 'Docker (building and exporting the image)',
  done: 'Finishing up',
}

/** Whether a result has anything for the panel to show (a duration alone does not). */
export function hasBuildResult(result: BuildResult | null | undefined): result is BuildResult {
  return Boolean(result && (result.verify || result.artifact || result.preflight?.length || result.report_file))
}

export type TrackState = 'done' | 'on' | 'todo' | 'failed' | 'stopped'

/**
 * The stage track for a build in any state. stageTrack() describes a running
 * build; a finished one sits at stage "done", which is not on the track, so
 * every stage would read as not started. This lays the outcome over it: a
 * passed build is done throughout, a failed one fails at the stage it was in
 * (result.failed_stage when the live stage is gone), and a cancelled one stops there.
 */
export function trackFor(
  track: { key: string; label: string; state: 'done' | 'on' | 'todo' }[],
  status: string,
  failedStage?: string | null,
): { key: string; label: string; state: TrackState }[] {
  if (status === 'completed') return track.map((s) => ({ ...s, state: 'done' }))
  if (status !== 'failed' && status !== 'cancelled') return track
  const end: TrackState = status === 'failed' ? 'failed' : 'stopped'
  let at = track.findIndex((s) => s.state === 'on')
  if (at < 0 && failedStage) at = track.findIndex((s) => s.key === failedStage)
  if (at < 0) return track
  return track.map((s, i) => ({ ...s, state: i < at ? 'done' : i === at ? end : 'todo' }))
}
