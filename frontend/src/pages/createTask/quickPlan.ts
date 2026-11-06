// What Quick build works out from a project on its own, so a first build needs
// only a source. Pure, so each guess is tested; anything it cannot tell is null
// and the page asks instead.
import type { ProjectType, RepoDiagnosisCheck } from '../../api/types'

export interface ProjectGuess {
  /** null: neither a Python entry point nor a package.json was found. */
  projectType: ProjectType | null
  /** Relative to the project, e.g. "app/main.py". */
  entryPoint: string | null
  /** Where package.json is: "." for the project root, or its directory. */
  frontendDir: string | null
}

/** Read the project type, entry point and frontend directory off the repo fingerprints. */
export function guessProject(checks: RepoDiagnosisCheck[]): ProjectGuess {
  const found = (key: string) => checks.find((c) => c.key === key && c.status === 'ok')?.path ?? null
  const entryPoint = found('entry_point')
  const packageJson = found('package_json')
  const python = entryPoint !== null || found('pyproject') !== null
  const frontendDir = packageJson === null ? null : packageJson.includes('/') ? packageJson.slice(0, packageJson.lastIndexOf('/')) : '.'
  const projectType: ProjectType | null =
    python && packageJson ? 'fullstack' : packageJson ? 'frontend_only' : python ? 'backend_only' : null
  return { projectType, entryPoint, frontendDir }
}

/** A project name from a folder path or a Git URL: its last part, without ".git". */
export function nameFromSource(source: string): string {
  const last = source.trim().replace(/[/\\]+$/, '').split(/[/\\:]/).pop() ?? ''
  return last.replace(/\.git$/i, '')
}
