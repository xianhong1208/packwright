import { Form } from 'antd'
import { useCreateTask } from '../context'
import { guessProject } from '../quickPlan'

const LABELS: Record<string, string> = { backend_only: 'Backend', frontend_only: 'Frontend', fullstack: 'Full stack' }

/**
 * What the project itself says about a field, next to the field: "Detected: X ·
 * Use it" when the value differs. On a project's settings a match is said too, so
 * every detected field reads as checked. Nothing is filled in by itself here.
 */
export default function DetectedHint({ field }: { field: 'project_type' | 'entry_point' | 'frontend_dir' | 'frontend_build_tool' | 'frontend_build_command' | 'frontend_output_dir' }) {
  const { form, repoChecks, frontendDetected, purpose } = useCreateTask()
  const current = Form.useWatch(field, { form, preserve: true }) as string | undefined
  const guess = repoChecks ? guessProject(repoChecks) : null
  const detected = {
    project_type: guess?.projectType,
    entry_point: guess?.entryPoint,
    frontend_dir: guess?.frontendDir,
    frontend_build_tool: frontendDetected?.build_tool,
    frontend_build_command: frontendDetected?.build_command,
    frontend_output_dir: frontendDetected?.output_dir,
  }[field]
  if (!detected) return null
  const shown = field === 'project_type' ? LABELS[detected] ?? detected : detected
  if (current === detected) {
    return purpose === 'settings' ? <span className="detected-hint" data-match>Matches what the project says.</span> : null
  }
  return (
    <span className="detected-hint">
      The project says <code>{shown}</code>.{' '}
      <button type="button" onClick={() => form.setFieldValue(field, detected)}>Use it</button>
    </span>
  )
}
