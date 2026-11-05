/**
 * The name of the binary a backend build produces. An empty `output_name` means
 * "derive it from the entry point" (the backend uses the file's stem), so showing
 * the raw field would leave the row blank on most builds.
 */
export function binaryName(config: { output_name?: string; entry_point?: string }): string {
  if (config.output_name) return config.output_name
  const file = (config.entry_point || '').split(/[\\/]/).pop() || ''
  return file.replace(/\.[^.]*$/, '') || '—'
}
