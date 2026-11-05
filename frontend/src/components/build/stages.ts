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
