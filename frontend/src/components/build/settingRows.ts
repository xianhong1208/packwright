// The rows of a build's "Settings and where they came from" list: which settings
// apply to this kind of build, how a value reads, and how its origin is said.
import type { BuildConfig, EffectiveSettings, FileKey, SettingOrigin } from '../../api/types'

type Field = keyof BuildConfig
type Group = 'Build' | 'Python' | 'Frontend' | 'Docker'

const ROWS: { field: Field; label: string; group: Group }[] = [
  { field: 'project_type', label: 'Project type', group: 'Build' },
  { field: 'version', label: 'Version', group: 'Build' },
  { field: 'output_dir', label: 'Output directory', group: 'Build' },
  { field: 'verify_after_build', label: 'Smoke test', group: 'Build' },
  { field: 'python_version', label: 'Python', group: 'Python' },
  { field: 'entry_point', label: 'Entry point', group: 'Python' },
  { field: 'output_name', label: 'Program name', group: 'Python' },
  { field: 'onefile', label: 'Single file', group: 'Python' },
  { field: 'pack_mode', label: 'Pack mode', group: 'Python' },
  { field: 'extra_dirs', label: 'Source directories', group: 'Python' },
  { field: 'data_dirs', label: 'Data directories', group: 'Python' },
  { field: 'include_packages', label: 'Included packages', group: 'Python' },
  { field: 'dependency_groups', label: 'Dependency groups', group: 'Python' },
  { field: 'nuitka_jobs', label: 'CPU jobs', group: 'Python' },
  { field: 'enable_anti_bloat', label: 'Anti-bloat', group: 'Python' },
  { field: 'include_package_data', label: 'Package data', group: 'Python' },
  { field: 'generate_report', label: 'Nuitka report', group: 'Python' },
  { field: 'frontend_dir', label: 'Frontend directory', group: 'Frontend' },
  { field: 'frontend_build_tool', label: 'Build tool', group: 'Frontend' },
  { field: 'frontend_build_command', label: 'Build command', group: 'Frontend' },
  { field: 'frontend_output_dir', label: 'Build output', group: 'Frontend' },
  { field: 'frontend_env_filename', label: 'Env file', group: 'Frontend' },
  { field: 'frontend_env_content', label: 'Build env', group: 'Frontend' },
  { field: 'docker_enabled', label: 'Docker image', group: 'Docker' },
  { field: 'docker_image_name', label: 'Image name', group: 'Docker' },
  { field: 'docker_base_image', label: 'Base image', group: 'Docker' },
  { field: 'docker_expose_port', label: 'Port', group: 'Docker' },
  { field: 'docker_env_vars', label: 'Image env', group: 'Docker' },
  { field: 'docker_custom_commands', label: 'Custom commands', group: 'Docker' },
  { field: 'docker_install_node', label: 'Node.js in image', group: 'Docker' },
  { field: 'docker_api_proxy', label: 'API proxy', group: 'Docker' },
  { field: 'docker_volumes', label: 'Volumes', group: 'Docker' },
  { field: 'docker_run_as_root', label: 'Runs as root', group: 'Docker' },
  { field: 'nginx_client_max_body_size', label: 'nginx body size', group: 'Docker' },
  { field: 'nginx_proxy_read_timeout', label: 'nginx read timeout', group: 'Docker' },
  { field: 'nginx_streaming', label: 'nginx streaming', group: 'Docker' },
  { field: 'nginx_gzip', label: 'nginx gzip', group: 'Docker' },
]

export const ORIGIN_LABELS: Record<SettingOrigin, string> = {
  file: 'packwright.toml',
  override: 'this build',
  project: 'project',
  detected: 'detected',
}

/** A setting's value as one line of text. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  const text = String(value)
  const lines = text.split('\n').filter(Boolean)
  return lines.length > 1 ? `${lines[0]} (+${lines.length - 1} more)` : text
}

export interface SettingRow {
  field: Field
  label: string
  value: string
  origin: SettingOrigin
  file?: FileKey
}

/**
 * Rows grouped for a build: the settings that apply to its type (a frontend-only
 * build has no Python group, an image's settings only when it builds one).
 */
export function settingRows(effective: EffectiveSettings | null | undefined, submitted: BuildConfig) {
  const config = (effective?.config ?? submitted) as BuildConfig
  const type = config.project_type
  const groups: Record<Group, boolean> = {
    Build: true,
    Python: type !== 'frontend_only',
    Frontend: type !== 'backend_only',
    Docker: Boolean(config.docker_enabled),
  }
  const out: { group: Group; rows: SettingRow[] }[] = []
  for (const row of ROWS) {
    if (!groups[row.group]) continue
    if (row.field === 'version' && !config.version) continue
    if (row.field.startsWith('nginx_') && type !== 'frontend_only') continue
    const file = effective?.file?.fields?.[row.field]
    const origin: SettingOrigin = file ? 'file' : (effective?.origins?.[row.field] ?? 'project')
    let bucket = out.find((g) => g.group === row.group)
    if (!bucket) out.push((bucket = { group: row.group, rows: [] }))
    bucket.rows.push({ field: row.field, label: row.label, value: formatValue(config[row.field]), origin, file })
  }
  return out
}
