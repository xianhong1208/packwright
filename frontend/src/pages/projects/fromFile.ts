// A project's settings next to what its repository's packwright.toml sets.
import type { BuildConfig, FileKey } from '../../api/types'

export type FileFieldMap = Partial<Record<keyof BuildConfig, FileKey>>

/** What the settings page shows: the project's settings with the file's values over them. */
export function withFileValues(config: BuildConfig, fields: FileFieldMap | null | undefined): BuildConfig {
  if (!fields) return config
  const out: Record<string, unknown> = { ...config }
  for (const [name, field] of Object.entries(fields)) {
    if (field && field.value !== undefined) out[name] = field.value
  }
  return out as unknown as BuildConfig
}

/**
 * What saving writes: the edited settings, except that a field the file sets keeps
 * the project's own saved value. The file's values are never written into the
 * project's settings: they belong to the repository, and apply only while it has them.
 */
export function keepSavedValues(
  edited: BuildConfig,
  saved: BuildConfig,
  fields: FileFieldMap | null | undefined,
): BuildConfig {
  if (!fields) return edited
  const out: Record<string, unknown> = { ...edited }
  for (const name of Object.keys(fields)) {
    out[name] = (saved as unknown as Record<string, unknown>)[name]
  }
  return out as unknown as BuildConfig
}
