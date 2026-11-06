import { Form, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { taskApi } from '../../api/client'
import { useCreateTask } from '../createTask/context'
import { assembleTaskCreate } from '../createTask/buildConfig'

/**
 * The commands a build with these settings runs, updated as they change: what a
 * switch does is seen, not guessed (auto-py-to-exe shows PyInstaller's line the
 * same way).
 */
export default function CommandPreview() {
  const { form, selectedDirs, selectedDataDirs } = useCreateTask()
  // Every value, so the preview follows any change; a string key keeps the query stable.
  const values = Form.useWatch((v) => JSON.stringify(v), { form, preserve: true })
  const config = values ? assembleTaskCreate({ values: form.getFieldsValue(true), selectedDirs, selectedDataDirs }).config : null
  const { data, isFetching, isError } = useQuery({
    queryKey: ['previewCommands', values, selectedDirs.join(','), selectedDataDirs.join(',')],
    queryFn: () => taskApi.previewCommands(config!),
    enabled: Boolean(config),
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  })

  return (
    <section className="glass-card p-6 mb-4" aria-labelledby="commands">
      <div className="flex items-center gap-3 mb-1">
        <h2 id="commands" className="text-[17px] font-semibold m-0" style={{ color: 'var(--ink)' }}>Commands a build runs</h2>
        {isFetching && <Spin size="small" />}
      </div>
      <p className="m-0 mb-4 text-sm" style={{ color: 'var(--ink-muted)' }}>Worked out from the settings on the other tabs; nothing is run.</p>
      {isError ? (
        <p style={{ color: 'var(--color-alert-400)' }}>These settings cannot be turned into a build yet. Check the other tabs.</p>
      ) : (
        <ol className="command-steps">
          {data?.steps.map((s) => (
            <li key={s.stage}>
              <div className="command-stage">{s.stage}</div>
              <pre className="command-line">{s.command}</pre>
            </li>
          ))}
        </ol>
      )}
      {data && data.notes.length > 0 && (
        <ul className="command-notes">
          {data.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </section>
  )
}
