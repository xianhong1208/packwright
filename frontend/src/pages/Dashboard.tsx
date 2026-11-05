import { useEffect, useMemo, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Empty, message, notification, Spin } from 'antd'
import { PlusIcon, WarningIcon } from '../components/ui/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api, { taskApi } from '../api/client'
import type { BuildStats, HistoryItem, SystemStats, TaskResponse } from '../api/types'
import { useTaskStore } from '../store/taskStore'
import { getErrorDetail } from '../utils/errors'
import { STATUS_META } from '../utils/statusMeta'
import { PROJECT_TYPE_META } from '../utils/projectTypeMeta'
import { STAGE_LABELS } from '../components/build/stages'
import { benchDays, coreHeat, duration, heatColor, outcomeLine, stageTrack } from './dashboard/bench'
import { parseUtc } from '../utils/time'
import PageHeader from '../components/layout/PageHeader'

/**
 * On the bench: what is running now and what ran recently, as one timeline,
 * with the last 30 days and the machine in a quiet side column.
 */
export default function Dashboard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { setTasks, tasks } = useTaskStore()

  const { data: activeTasks } = useQuery({ queryKey: ['activeTasks'], queryFn: taskApi.getActive, refetchInterval: 5000 })
  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['benchHistory'],
    queryFn: () => taskApi.getHistory({ limit: 30 }),
    refetchInterval: 15_000,
  })
  const { data: stats } = useQuery({ queryKey: ['buildStats'], queryFn: () => taskApi.getBuildStats(30), refetchInterval: 60_000, staleTime: 30_000 })
  const { data: machine } = useQuery<SystemStats>({
    queryKey: ['benchMachine'],
    queryFn: async () => (await api.get('/monitoring/stats')).data,
    refetchInterval: 5000,
  })

  useEffect(() => {
    if (activeTasks) setTasks(activeTasks)
  }, [activeTasks, setTasks])

  // A build leaving the running list gets a toast that opens its result.
  const prevActiveRef = useRef<Map<string, string> | null>(null)
  useEffect(() => {
    if (!activeTasks) return
    const current = new Map(activeTasks.map((t) => [t.id, t.project_name]))
    if (prevActiveRef.current) {
      for (const [id, name] of prevActiveRef.current) {
        if (!current.has(id)) {
          notification.info({ message: `${name} finished`, description: 'Open it to see the result.', duration: 6, onClick: () => navigate(`/task/${id}`) })
          queryClient.invalidateQueries({ queryKey: ['benchHistory'] })
        }
      }
    }
    prevActiveRef.current = current
  }, [activeTasks, navigate, queryClient])

  const cancel = useMutation({
    mutationFn: taskApi.cancel,
    onSuccess: () => {
      message.success('Build cancelled')
      queryClient.invalidateQueries({ queryKey: ['activeTasks'] })
    },
    onError: (err) => message.error(getErrorDetail(err, 'Could not cancel the build')),
  })

  const running = Array.from(tasks.values())
  const days = useMemo(() => benchDays(running, history ?? []), [running, history])

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
      <section aria-label="On the bench" className="min-w-0">
        <PageHeader
          title="On the bench"
          lead={running.length > 0
            ? `${running.length} ${running.length === 1 ? 'build is' : 'builds are'} running.`
            : 'Nothing is running. Recent builds are below.'}
        />

        {stats && stats.environment.degraded.length > 0 && <DegradedBanner stats={stats} />}

        {historyLoading && running.length === 0 ? (
          <div className="py-20 text-center"><Spin size="large" /></div>
        ) : days.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ color: 'var(--ink-muted)' }}>Nothing has been built yet.</span>}
            className="py-12"
          >
            <Button type="primary" icon={<PlusIcon />} onClick={() => navigate('/create')}>New build</Button>
          </Empty>
        ) : (
          <div className="bench">
            {days.map((day) => (
              <div key={day.label}>
                <h2 className="bench-day">{day.label}</h2>
                {day.entries.map((e) =>
                  e.kind === 'running' ? (
                    <RunningEntry key={e.task.id} task={e.task} onOpen={() => navigate(`/task/${e.task.id}`)} onCancel={() => cancel.mutate(e.task.id)} cancelling={cancel.isPending} />
                  ) : e.kind === 'cancelled-run' ? (
                    <CancelledRun key={e.items[0].task_id} items={e.items} />
                  ) : (
                    <FinishedEntry key={e.item.task_id} item={e.item} />
                  ),
                )}
              </div>
            ))}
            <Link to="/history" className="inline-block mt-2 ml-[112px] max-sm:ml-6" style={{ color: 'var(--color-cyber-400)' }}>
              All builds
            </Link>
          </div>
        )}
      </section>

      <aside className="flex flex-col gap-4" aria-label="Health">
        <LastThirtyDays stats={stats} />
        <Machine machine={machine} running={running.length} />
      </aside>
    </div>
  )
}

function RunningEntry({ task, onOpen, onCancel, cancelling }: { task: TaskResponse; onOpen: () => void; onCancel: () => void; cancelling: boolean }) {
  const track = stageTrack(task)
  const tail = task.logs.slice(-2)
  return (
    <div className="bench-entry">
      <span className="bench-time">{parseUtc(task.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      <span className="bench-dot" style={{ background: 'var(--color-teal-400)' }} aria-hidden="true" />
      <article className="bench-card running">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Link to={`/task/${task.id}`} className="bench-name">{task.project_name}</Link>
          <span className="bench-what">{PROJECT_TYPE_META[task.config.project_type].label}</span>
          <span className="ml-auto font-semibold" style={{ color: 'var(--color-teal-400)' }}>
            {task.status === 'pending' ? 'Waiting for a build slot' : task.status_msg || 'Running'}
          </span>
        </div>
        <div className="bench-track" aria-label={`Stage ${STAGE_LABELS[task.stage] ?? task.stage}, ${task.progress}% overall`}>
          {track.map((s) => (
            <div key={s.key} className="min-w-0">
              <div className={`bench-seg ${s.state}`} style={s.state === 'on' ? { ['--fill' as string]: `${task.progress}%` } : undefined} />
              <div className={`bench-seglabel ${s.state}`}>{s.label}{s.state === 'on' ? ` ${task.progress}%` : ''}</div>
            </div>
          ))}
        </div>
        {tail.length > 0 && (
          <div className="bench-tail" aria-label="Latest log lines">
            {tail.map((l, i) => <div key={i} className="truncate">{l}</div>)}
          </div>
        )}
        <div className="flex gap-2 mt-3">
          <Button size="small" onClick={onOpen}>Open build</Button>
          <Button size="small" danger onClick={onCancel} loading={cancelling}>Cancel</Button>
        </div>
      </article>
    </div>
  )
}

function FinishedEntry({ item }: { item: HistoryItem }) {
  const meta = STATUS_META[item.status]
  const type = item.config?.project_type ? PROJECT_TYPE_META[item.config.project_type] : null
  const line = outcomeLine(item)
  return (
    <div className="bench-entry">
      <span className="bench-time">{parseUtc(item.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      <span className="bench-dot" style={{ background: meta.color }} aria-hidden="true" />
      <Link to={`/history/${item.task_id}`} className="bench-card finished">
        <div className="min-w-0 flex-1">
          <div className="bench-name">{item.project_name}</div>
          <div className="bench-what truncate">{[type?.label, line.detail].filter(Boolean).join(', ')}</div>
        </div>
        <div className="text-right flex-none">
          <div className="font-semibold" style={{ color: meta.color }}>{line.verdict}</div>
          <div className="bench-what">{line.next}</div>
        </div>
      </Link>
    </div>
  )
}

function CancelledRun({ items }: { items: HistoryItem[] }) {
  const names = [...new Set(items.map((i) => i.project_name))]
  const at = (i: HistoryItem) => parseUtc(i.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <div className="bench-entry">
      <span className="bench-time">{at(items[0])}</span>
      <span className="bench-dot" style={{ background: STATUS_META.cancelled.color }} aria-hidden="true" />
      <Link to="/history" className="bench-card finished quiet">
        <div className="min-w-0 flex-1">
          <div className="bench-what" style={{ color: 'var(--ink)' }}>{items.length} builds cancelled</div>
          <div className="bench-what truncate">{names.slice(0, 4).join(', ')}{names.length > 4 ? ` and ${names.length - 4} more` : ''}</div>
        </div>
        <div className="bench-what flex-none">since {at(items[items.length - 1])}</div>
      </Link>
    </div>
  )
}

function LastThirtyDays({ stats }: { stats: BuildStats | undefined }) {
  const s = stats?.summary
  const finished = s ? s.completed + s.failed : 0
  const topFailure = stats?.top_failures[0]
  return (
    <div className="glass-card p-5">
      <h2 className="text-[15px] font-semibold m-0 mb-3" style={{ color: 'var(--ink)' }}>Last 30 days</h2>
      {!s ? (
        <Spin />
      ) : finished === 0 ? (
        <p className="m-0" style={{ color: 'var(--ink-muted)' }}>No finished builds yet.</p>
      ) : (
        <>
          <div className="text-[52px] font-bold leading-none" style={{ color: (s.success_rate ?? 0) >= 80 ? 'var(--color-matrix-400)' : (s.success_rate ?? 0) >= 50 ? 'var(--color-signal-400)' : 'var(--color-alert-400)' }}>
            {Math.round(s.success_rate ?? 0)}%
          </div>
          <p className="mt-2 mb-0 text-sm" style={{ color: 'var(--ink-muted)' }}>
            {s.completed} of {finished} finished builds passed.
            {s.cancelled > 0 && ` ${s.cancelled} cancelled ${s.cancelled === 1 ? 'build is' : 'builds are'} not counted.`}
          </p>
          {s.avg_duration_seconds != null && (
            <div className="flex justify-between mt-4 text-sm"><span style={{ color: 'var(--ink-muted)' }}>Typical build</span><b>{duration(s.avg_duration_seconds)}</b></div>
          )}
          {topFailure && (
            <p className="mt-3 mb-0 text-sm" style={{ color: 'var(--ink-faint)' }}>
              Most common failure ({topFailure.count}×): {topFailure.problem}
            </p>
          )}
        </>
      )}
    </div>
  )
}

function Machine({ machine, running }: { machine: SystemStats | undefined; running: number }) {
  if (!machine) return <div className="glass-card p-5"><Spin /></div>
  const heat = coreHeat(machine.cpu.percent_per_core, 16)
  return (
    <Link to="/monitor" className="glass-card p-5 block" style={{ color: 'var(--ink)' }}>
      <h2 className="text-[15px] font-semibold m-0 mb-3">Machine</h2>
      <div className="flex justify-between text-sm"><span style={{ color: 'var(--ink-muted)' }}>{machine.cpu.count_logical} cores</span><b>{Math.round(machine.cpu.percent)}% busy</b></div>
      <div className="core-heat" aria-label={`Core load in ${heat.length} groups of ${Math.ceil(machine.cpu.percent_per_core.length / heat.length)} cores`}>
        {heat.map((pct, i) => <i key={i} title={`${Math.round(pct)}%`} style={{ background: heatColor(pct) }} />)}
      </div>
      <Meter label="Memory" pct={machine.memory.percent} />
      <Meter label="Disk" pct={machine.disk.percent} />
      <div className="flex justify-between text-sm mt-1"><span style={{ color: 'var(--ink-muted)' }}>Running builds</span><span>{running}</span></div>
    </Link>
  )
}

function Meter({ label, pct }: { label: string; pct: number }) {
  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm"><span style={{ color: 'var(--ink-muted)' }}>{label}</span><span>{Math.round(pct)}%</span></div>
      <div className="meter"><span style={{ width: `${pct}%`, background: pct >= 90 ? 'var(--color-alert-400)' : 'var(--ink-muted)' }} /></div>
    </div>
  )
}

function DegradedBanner({ stats }: { stats: BuildStats }) {
  const env = stats.environment
  // First and loud on purpose: a compile target whose venv stopped resolving
  // produces no error anywhere — builds silently fall back to the service's own
  // Python and hand users a binary that breaks on their machine.
  return (
    <div className="glass-card p-4 mb-6" style={{ borderColor: 'var(--color-alert-500)', background: 'color-mix(in srgb, var(--color-alert-500) 7%, transparent)' }}>
      <div className="flex items-center gap-2 mb-1 font-semibold text-alert-400">
        <WarningIcon /> Python {env.degraded.join(', ')} cannot be compiled for right now
      </div>
      <div className="text-sm" style={{ color: 'var(--ink-muted)' }}>
        Builds that pick it fall back to the service&apos;s Python {env.service_python}, and the result fails with
        ModuleNotFoundError where it runs. Run <code className="text-[var(--ink)]">bash scripts/setup_nuitka_venvs.sh</code> on the server.
      </div>
    </div>
  )
}
