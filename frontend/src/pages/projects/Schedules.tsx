import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Input, Modal, Popconfirm, Segmented, Select, Switch, Tooltip, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectApi } from '../../api/client'
import type { ProjectSchedule, ScheduleInput, ScheduleRun } from '../../api/types'
import { ClockIcon, PencilSimpleIcon, PlusIcon, TrashIcon, WarningIcon } from '../../components/ui/icons'
import { getErrorDetail } from '../../utils/errors'
import { parseUtc, timeAgo, timeUntil, zonedTime } from '../../utils/time'

const PRESETS: { label: string; cron: string }[] = [
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Nightly', cron: '0 2 * * *' },
  { label: 'Weeknights', cron: '0 2 * * 1-5' },
  { label: 'Weekly', cron: '0 3 * * 1' },
]
const CUSTOM = 'Custom'

function zones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  const list = intl.supportedValuesOf ? intl.supportedValuesOf('timeZone') : []
  return list.includes('UTC') ? list : ['UTC', ...list]
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return settled
}

/**
 * Scheduled builds: a branch or tag built at set times, as the person who set
 * the schedule up. Changes save at once.
 */
export default function Schedules({ projectId, canEdit, fromGit, defaultRef, defaultRefType }: {
  projectId: number; canEdit: boolean; fromGit: boolean; defaultRef: string; defaultRefType: 'branch' | 'tag'
}) {
  const key = ['schedules', projectId]
  const queryClient = useQueryClient()
  const { data: list = [] } = useQuery({ queryKey: key, queryFn: () => projectApi.schedules(projectId), refetchInterval: 30_000 })
  const [editing, setEditing] = useState<ProjectSchedule | 'new' | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-sm" style={{ color: 'var(--ink-muted)' }}>
        A schedule builds a branch or tag at set times, as the person who set it up. When it runs, the branch is read
        and that exact commit is built. A run is skipped while a build of this project is queued or running, and, unless
        you turn it off, when the commit and the settings are the same as the last successful build. Runs missed while
        Packwright was not running are not made up. Changes here are saved at once.
      </p>
      {!fromGit && (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>
          This project builds from a folder. Schedules need a project that builds from a Git URL.
        </p>
      )}
      {fromGit && list.length === 0 && (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>No schedules yet.</p>
      )}
      {list.map((s) => (
        <ScheduleCard key={s.id} projectId={projectId} schedule={s} onChange={refresh} onEdit={() => setEditing(s)} />
      ))}
      {fromGit && (canEdit ? (
        <div>
          <Button type="primary" icon={<PlusIcon />} onClick={() => setEditing('new')}>Add a schedule</Button>
        </div>
      ) : (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>Only the project's creator or a project manager can change these.</p>
      ))}
      {editing !== null && (
        <ScheduleDialog
          projectId={projectId}
          schedule={editing === 'new' ? null : editing}
          defaultRef={defaultRef}
          defaultRefType={defaultRefType}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh() }}
        />
      )}
    </div>
  )
}

function ScheduleCard({ projectId, schedule: s, onChange, onEdit }: {
  projectId: number; schedule: ProjectSchedule; onChange: () => void; onEdit: () => void
}) {
  const [showRuns, setShowRuns] = useState(false)
  const failed = (fallback: string) => (err: unknown) => message.error(getErrorDetail(err, fallback))
  const update = useMutation({
    mutationFn: (body: ScheduleInput) => projectApi.updateSchedule(projectId, s.id, body),
    onSuccess: onChange,
    onError: failed('Could not save the schedule'),
  })
  const remove = useMutation({
    mutationFn: () => projectApi.removeSchedule(projectId, s.id),
    onSuccess: onChange,
    onError: failed('Could not delete the schedule'),
  })
  const name = `Schedule ${s.cron}`
  const kind = s.ref_type === 'tag' ? 'Tag' : 'Branch'

  return (
    <section className="glass-card p-4" aria-label={name} data-enabled={s.enabled}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-semibold inline-flex flex-wrap items-center gap-2" style={{ color: 'var(--ink)' }}>
            <ClockIcon /> {s.description ?? s.cron}
            {!s.enabled && <span className="hook-state">off</span>}
          </div>
          <div className="schedule-cron"><code>{s.cron}</code> <span>{s.timezone}</span></div>
        </div>
        <label className="inline-flex items-center gap-2 text-sm" style={{ color: 'var(--ink-muted)' }}>
          <Switch size="small" checked={s.enabled} disabled={!s.can_edit} loading={update.isPending}
            aria-label={`${name} on`} onChange={(v) => update.mutate({ enabled: v })} />
          On
        </label>
      </div>

      {s.disabled_reason && (
        <div className="hook-disabled" role="status">
          <WarningIcon />
          <span>
            Turned off: {s.disabled_reason}.{' '}
            {s.can_edit && (
              <Button size="small" type="link" className="p-0 h-auto"
                onClick={() => update.mutate({ enabled: true, take_over: true })}>
                Take it over and turn it on
              </Button>
            )}
          </span>
        </div>
      )}

      <dl className="hook-facts">
        <div><dt>{kind}</dt><dd><code>{s.ref}</code></dd></div>
        <div>
          <dt>Next run</dt>
          <dd>{s.next_run_at
            ? <Tooltip title={timeUntil(s.next_run_at)}><span>{zonedTime(s.next_run_at, s.timezone)}</span></Tooltip>
            : 'none (off)'}</dd>
        </div>
        <div>
          <dt>Last run</dt>
          <dd>{s.last_run
            ? <span className="schedule-last" data-result={s.last_run.result}>
                {RESULT_TEXT[s.last_run.result]} {timeAgo(s.last_run.ran_at)}
              </span>
            : 'none yet'}</dd>
        </div>
        <div><dt>If unchanged</dt><dd>{s.skip_unchanged ? 'skip' : 'build anyway'}</dd></div>
        <div><dt>Builds as</dt><dd>{s.created_by}</dd></div>
      </dl>

      <div className="flex flex-wrap gap-2 mt-3">
        <Button size="small" onClick={() => setShowRuns((v) => !v)} aria-expanded={showRuns}>
          {showRuns ? 'Hide runs' : 'Runs'}
        </Button>
        {s.can_edit && (
          <>
            <Button size="small" icon={<PencilSimpleIcon />} onClick={onEdit}>Edit</Button>
            <Popconfirm title="Delete this schedule?" description="Its run history goes with it; the builds stay."
              okText="Delete" okButtonProps={{ danger: true }} onConfirm={() => remove.mutate()}>
              <Button size="small" danger icon={<TrashIcon />} loading={remove.isPending}>Delete</Button>
            </Popconfirm>
          </>
        )}
      </div>
      {showRuns && <Runs projectId={projectId} scheduleId={s.id} zone={s.timezone} />}
    </section>
  )
}

function ScheduleDialog({ projectId, schedule, defaultRef, defaultRefType, onClose, onSaved }: {
  projectId: number
  schedule: ProjectSchedule | null
  defaultRef: string
  defaultRefType: 'branch' | 'tag'
  onClose: () => void
  onSaved: () => void
}) {
  const [cron, setCron] = useState(schedule?.cron ?? PRESETS[1].cron)
  const [zone, setZone] = useState(schedule?.timezone ?? '')
  const [ref, setRef] = useState(schedule?.ref ?? defaultRef)
  const [refType, setRefType] = useState<'branch' | 'tag'>(schedule?.ref_type ?? defaultRefType)
  const [skip, setSkip] = useState(schedule?.skip_unchanged ?? true)
  const zoneOptions = useMemo(() => zones().map((z) => ({ value: z, label: z })), [])
  const preset = PRESETS.find((p) => p.cron === cron.trim())?.label ?? CUSTOM

  const asked = useDebounced({ cron: cron.trim(), zone }, 300)
  const preview = useQuery({
    queryKey: ['schedule-preview', projectId, asked.cron, asked.zone],
    queryFn: () => projectApi.previewSchedule(projectId, { cron: asked.cron, timezone: asked.zone || undefined }),
    enabled: asked.cron !== '',
    retry: false,
  })
  // A new schedule starts in the server's zone, which the first preview names.
  const effectiveZone = zone || preview.data?.timezone || ''

  const save = useMutation({
    mutationFn: () => {
      const body = { cron: cron.trim(), timezone: effectiveZone || undefined, ref: ref.trim(), ref_type: refType, skip_unchanged: skip }
      return schedule ? projectApi.updateSchedule(projectId, schedule.id, body) : projectApi.addSchedule(projectId, body)
    },
    onSuccess: onSaved,
    onError: (err) => message.error(getErrorDetail(err, 'Could not save the schedule')),
  })
  const shownZone = preview.data?.timezone ?? effectiveZone

  return (
    <Modal
      title={schedule ? 'Edit schedule' : 'Add a schedule'}
      open
      onCancel={onClose}
      okText={schedule ? 'Save' : 'Add schedule'}
      onOk={() => save.mutate()}
      okButtonProps={{ loading: save.isPending, disabled: !cron.trim() || !ref.trim() || preview.isError }}
      destroyOnHidden
    >
      <div className="schedule-form">
        <div className="hook-field-label">How often</div>
        <div className="schedule-presets" role="group" aria-label="How often">
          {[...PRESETS, { label: CUSTOM, cron: '' }].map((p) => (
            <Button key={p.label} size="small" type={preset === p.label ? 'primary' : 'default'}
              aria-pressed={preset === p.label} onClick={() => (p.cron ? setCron(p.cron) : document.getElementById('schedule-cron')?.focus())}>
              {p.label}
            </Button>
          ))}
        </div>
        <label className="block">
          <span className="hook-field-label">Cron expression</span>
          <Input id="schedule-cron" className="input-field font-mono" value={cron} aria-label="Cron expression" placeholder="0 2 * * *"
            onChange={(e) => setCron(e.target.value)} />
        </label>
        <p className="m-0 mt-1 text-[13px]" style={{ color: 'var(--ink-faint)' }}>
          Five fields: minute, hour, day of month, month, day of week (<code>0 2 * * 1-5</code> is 02:00 on weekdays).
        </p>
        <label className="block">
          <span className="hook-field-label">Time zone</span>
          <Select className="w-full" showSearch value={effectiveZone || undefined} options={zoneOptions} aria-label="Time zone"
            placeholder="The server's time zone" onChange={setZone} />
        </label>
        <div className="hook-field-label">What to build</div>
        <div className="schedule-ref">
          <Segmented<'branch' | 'tag'> value={refType} onChange={setRefType} aria-label="Branch or tag"
            options={[{ value: 'branch', label: 'Branch' }, { value: 'tag', label: 'Tag' }]} />
          <Input className="input-field" value={ref} aria-label={refType === 'tag' ? 'Tag name' : 'Branch name'}
            placeholder={refType === 'tag' ? 'v1.0.0' : 'main'} onChange={(e) => setRef(e.target.value)} />
        </div>
        <label className="schedule-skip">
          <Switch size="small" checked={skip} onChange={setSkip} aria-label="Skip when unchanged" />
          <span>Skip a run when the commit and the settings are the same as the last successful build</span>
        </label>

        <div className="schedule-preview" aria-live="polite">
          <div className="hook-field-label">Next runs{shownZone ? ` (${shownZone})` : ''}</div>
          {preview.isError ? (
            <p className="schedule-error" role="alert">{getErrorDetail(preview.error, 'This expression cannot be used')}</p>
          ) : preview.data ? (
            <>
              {preview.data.description && <p className="m-0 mb-1 text-sm" style={{ color: 'var(--ink)' }}>{preview.data.description}</p>}
              <ol aria-label="Next run times">
                {preview.data.next_runs.map((t) => <li key={t}>{zonedTime(t, preview.data.timezone)}</li>)}
              </ol>
            </>
          ) : (
            <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>Working out the next runs…</p>
          )}
        </div>
      </div>
    </Modal>
  )
}

const RESULT_TEXT: Record<ScheduleRun['result'], string> = { built: 'Built', skipped: 'Skipped', failed: 'Failed' }

function Runs({ projectId, scheduleId, zone }: { projectId: number; scheduleId: number; zone: string }) {
  const { data = [], isLoading } = useQuery({
    queryKey: ['schedule-runs', scheduleId],
    queryFn: () => projectApi.scheduleRuns(projectId, scheduleId),
    refetchInterval: 10_000,
  })
  if (isLoading) return <p className="text-sm mt-3 mb-0" style={{ color: 'var(--ink-faint)' }}>Loading runs…</p>
  if (data.length === 0) {
    return <p className="text-sm mt-3 mb-0" style={{ color: 'var(--ink-faint)' }}>No runs yet. The newest 50 are kept.</p>
  }
  return (
    <ul className="hook-deliveries" aria-label="Runs">
      {data.map((r) => (
        <li key={r.id} data-result={r.result}>
          <span className="hook-result">{RESULT_TEXT[r.result]}</span>
          <div className="min-w-0">
            <div className="hook-delivery-what">
              <Tooltip title={`handled ${parseUtc(r.ran_at).toLocaleString()}`}><span>{zonedTime(r.due_at, zone)}</span></Tooltip>
              {r.commit_sha && <code>{r.commit_sha.slice(0, 12)}</code>}
            </div>
            <div className="hook-delivery-why">
              {r.task_id
                ? <Link to={`/history/${r.task_id}`}>Build {r.task_id.slice(0, 8)}</Link>
                : null}
              {r.reason && <span>{r.task_id ? ' · ' : ''}{r.reason}</span>}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}
