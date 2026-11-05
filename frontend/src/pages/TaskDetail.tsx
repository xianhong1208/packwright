import { useState, useEffect, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Progress, Button, Spin, message, Steps } from 'antd'
import {
  ArrowLeftOutlined,
  StopOutlined,
  RedoOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import LogViewer from '../components/LogViewer'
import BuildResultPanel from '../components/build/BuildResultPanel'
import FailureReport from '../components/build/FailureReport'
import { useWebSocket } from '../hooks/useWebSocket'
import { taskApi } from '../api/client'
import type { TaskResponse, ProjectType } from '../api/types'
import { triggerUrlDownload } from '../utils/download'
import { STATUS_META, isTerminal } from '../utils/statusMeta'
import { getErrorDetail, isNotFound } from '../utils/errors'
import { binaryName } from '../utils/buildConfig'

// ── Build-stage stepper (set by nuitka_worker: preflight→compile→bundle→verify→done) ──
const STAGE_ORDER = ['queued', 'preflight', 'compile', 'bundle', 'verify', 'done'] as const
const STAGE_ITEMS = [
  { title: 'Queued', description: 'Waiting for a build slot' },
  { title: 'Preflight', description: 'Checking the environment' },
  { title: 'Compile', description: 'Nuitka compiling' },
  { title: 'Bundle', description: 'Copying dependencies and data' },
  { title: 'Verify', description: 'Smoke-testing the binary' },
]
const PROJECT_TYPE_LABELS: Record<ProjectType, string> = {
  backend_only: 'Backend',
  frontend_only: 'Frontend',
  fullstack: 'Full-stack',
}

const stageIndex = (stage: string) => {
  const i = STAGE_ORDER.indexOf(stage as (typeof STAGE_ORDER)[number])
  return i < 0 ? 0 : i
}

// Human-readable duration for a seconds count.
const fmtDuration = (secs: number): string =>
  secs >= 60 ? `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s` : `${secs}s`

// Relative time in the GitHub-Actions register ("3 minutes ago").
const timeAgo = (iso: string): string => {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'} ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'} ago`
  const d = Math.floor(h / 24)
  if (d < 30) return `${d} day${d === 1 ? '' : 's'} ago`
  return new Date(iso).toLocaleDateString()
}

// A single label / value row in the config sidebar.
function DetailRow({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="flex-shrink-0" style={{ color: 'var(--ink-faint)' }}>
        {label}
      </span>
      <span
        className={`text-right min-w-0 truncate ${mono ? 'font-mono text-xs' : ''}`}
        style={{ color: 'var(--ink)' }}
      >
        {children}
      </span>
    </div>
  )
}

export default function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [wsConnected, setWsConnected] = useState(false)

  // WebSocket carries live increments; HTTP provides the initial snapshot
  // plus a reconciling poll. While WS is connected we poll slowly (5s) just
  // to correct any drift; if WS drops we fall back to 1s. Either way polling
  // stops once the task reaches a terminal state.
  const { data: task, isLoading, error } = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => taskApi.get(taskId!),
    enabled: !!taskId,
    retry: (failures, err) => !isNotFound(err) && failures < 1,
    refetchInterval: (query) =>
      query.state.error || isTerminal(query.state.data?.status) ? false : wsConnected ? 5000 : 1000,
  })

  // Only running and recently finished builds live in memory; after a restart or
  // eviction the API answers 404 here. The finished build is still in the history,
  // so send the link there instead of a dead end (or a spinner polling forever).
  useEffect(() => {
    if (isNotFound(error)) navigate(`/history/${taskId}`, { replace: true })
  }, [error, taskId, navigate])

  // Apply live updates straight into the query cache so the UI reacts
  // instantly without re-fetching the whole task every tick.
  const { isConnected, stoppedReason: wsStoppedReason } = useWebSocket({
    taskId,
    onMessage: (msg) => {
      queryClient.setQueryData<typeof task>(['task', taskId], (old) => {
        if (!old) return old
        switch (msg.type) {
          case 'log':
            return { ...old, logs: [...(old.logs ?? []), String(msg.data)] }
          case 'status':
            return { ...old, status: msg.data as TaskResponse['status'] }
          case 'progress':
            return { ...old, progress: Number(msg.data) }
          case 'status_msg':
            return { ...old, status_msg: String(msg.data) }
          case 'stage':
            return { ...old, stage: String(msg.data) }
          case 'result':
            return { ...old, result: msg.data as TaskResponse['result'] }
          default:
            return old
        }
      })
    },
  })
  useEffect(() => {
    setWsConnected(isConnected)
  }, [isConnected])

  const [downloading, setDownloading] = useState(false)

  // Cancel mutation
  const cancelMutation = useMutation({
    mutationFn: taskApi.cancel,
    onSuccess: () => {
      message.success('Cancellation request sent.')
      queryClient.invalidateQueries({ queryKey: ['task', taskId] })
    },
    onError: (err) => {
      message.error(getErrorDetail(err, 'Could not cancel the run. Please try again.'))
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spin size="large" />
      </div>
    )
  }

  if (!task) {
    return (
      <div className="text-center py-20">
        <h2 className="text-xl mb-4" style={{ color: 'var(--ink-muted)' }}>
          We couldn't find this build run.
        </h2>
        <button onClick={() => navigate('/')} className="btn-cyber">
          Back to dashboard
        </button>
      </div>
    )
  }

  const config = STATUS_META[task.status]
  const isActive = task.status === 'pending' || task.status === 'running'
  const result = task.result
  const hasBackend =
    task.config.project_type === 'backend_only' || task.config.project_type === 'fullstack'
  const hasFrontend =
    task.config.project_type === 'frontend_only' || task.config.project_type === 'fullstack'

  return (
    <div>
      {/* Run header — status glyph + run title + a muted meta line, GitHub-Actions style. */}
      <div className="flex items-start gap-3 mb-6">
        <button
          onClick={() => navigate('/')}
          aria-label="Back to dashboard"
          className="p-2 rounded-lg mt-0.5 transition-colors"
          style={{ color: 'var(--ink-muted)' }}
        >
          <ArrowLeftOutlined className="text-lg" />
        </button>

        <span
          className="mt-0.5 flex-shrink-0"
          style={{ color: config.color, fontSize: 22, display: 'inline-flex' }}
        >
          {config.icon}
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1
              className="text-xl font-semibold"
              style={{ color: 'var(--ink)', fontFamily: 'var(--font-display)' }}
            >
              {task.project_name}
            </h1>
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium uppercase"
              style={{ backgroundColor: config.bgColor, color: config.color }}
            >
              {config.label}
            </span>
          </div>

          <div
            className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm mt-1"
            style={{ color: 'var(--ink-faint)' }}
          >
            <span>{PROJECT_TYPE_LABELS[task.config.project_type]}</span>
            {task.config.docker_enabled && (
              <>
                <span aria-hidden>·</span>
                <span>Docker</span>
              </>
            )}
            <span aria-hidden>·</span>
            <span>Triggered by {task.user_name}</span>
            <span aria-hidden>·</span>
            <span>Started {timeAgo(task.created_at)}</span>
            {typeof result?.duration_seconds === 'number' && (
              <>
                <span aria-hidden>·</span>
                <span className="font-mono">{fmtDuration(result.duration_seconds)}</span>
              </>
            )}
            <span className="font-mono ml-1" style={{ color: 'var(--ink-faint)' }}>
              #{task.id.slice(0, 8)}
            </span>
          </div>
        </div>

        {/* Primary actions */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {isActive ? (
            <Button
              danger
              icon={<StopOutlined />}
              onClick={() => cancelMutation.mutate(task.id)}
              loading={cancelMutation.isPending}
            >
              Cancel run
            </Button>
          ) : (
            <>
              <Button
                icon={<RedoOutlined />}
                onClick={() =>
                  navigate('/create', {
                    state: {
                      rebuild: true,
                      projectName: task.project_name,
                      config: task.config,
                    },
                  })
                }
              >
                Rebuild
              </Button>
              {task.status === 'completed' && (
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  loading={downloading}
                  onClick={async () => {
                    setDownloading(true)
                    try {
                      triggerUrlDownload(await taskApi.getOutputDownloadUrl(task.id))
                      message.success('Download started.')
                    } catch (err: unknown) {
                      message.error(
                        getErrorDetail(err, 'Could not download the output. Please try again.')
                      )
                    } finally {
                      setDownloading(false)
                    }
                  }}
                >
                  Download output
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Build stage stepper — backend / fullstack only */}
      {hasBackend && task.stage && (
        <div className="glass-card p-4 mb-6">
          <Steps
            size="small"
            current={stageIndex(task.stage)}
            status={task.status === 'failed' || task.status === 'cancelled' ? 'error' : undefined}
            items={STAGE_ITEMS}
          />
        </div>
      )}

      {/* Failure diagnosis — shown for FAILED tasks even when result is null,
          so a failed build always explains itself. */}
      {task.status === 'failed' && (
        <FailureReport
          result={result}
          logs={task.logs}
          statusMsg={task.status_msg}
          logHint="the full log on the right"
          onApplyFix={(overrides) =>
            navigate('/create', {
              state: { rebuild: true, projectName: task.project_name, config: { ...task.config, ...overrides } },
            })
          }
        />
      )}

      <BuildResultPanel result={result} />

      {/* Body — config sidebar + the live log stream as the focus. */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Config / details sidebar */}
        <div className="lg:col-span-1">
          <div className="glass-card p-5 space-y-5">
            {/* Progress — while the run is active */}
            {isActive && (
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span style={{ color: 'var(--ink-muted)' }}>Progress</span>
                  <span className="font-mono text-cyber-400">{task.progress}%</span>
                </div>
                <Progress percent={task.progress} showInfo={false} />
                {task.status_msg && (
                  <p className="text-sm mt-2" style={{ color: 'var(--ink-muted)' }}>
                    {task.status_msg}
                  </p>
                )}
              </div>
            )}

            <div className="space-y-2.5 text-sm">
              <DetailRow label="Project type">
                {PROJECT_TYPE_LABELS[task.config.project_type]}
              </DetailRow>
              {task.config.docker_enabled && <DetailRow label="Docker">Enabled</DetailRow>}

              {/* Backend settings */}
              {hasBackend && (
                <>
                  <DetailRow label="Pack mode">
                    {{ full: 'Full', external: 'External' }[task.config.pack_mode]}
                  </DetailRow>
                  <DetailRow label="Python">{task.python_version}</DetailRow>
                  <DetailRow label="Entry point" mono>
                    {task.config.entry_point}
                  </DetailRow>
                  <DetailRow label="Binary name" mono>
                    {binaryName(task.config)}
                  </DetailRow>
                  <DetailRow label="One-file binary">
                    {task.config.onefile ? 'Yes' : 'No'}
                  </DetailRow>
                  <DetailRow label="CPU jobs">
                    {task.config.nuitka_jobs > 0 ? `${task.config.nuitka_jobs} cores` : 'Auto'}
                  </DetailRow>
                  {task.config.include_packages && (
                    <DetailRow label="Included packages" mono>
                      {task.config.include_packages}
                    </DetailRow>
                  )}
                </>
              )}

              {/* Frontend settings */}
              {hasFrontend && (
                <>
                  <DetailRow label="Frontend dir" mono>
                    {task.config.frontend_dir}
                  </DetailRow>
                  <DetailRow label="Build tool">{task.config.frontend_build_tool}</DetailRow>
                  <DetailRow label="Build command" mono>
                    {task.config.frontend_build_command}
                  </DetailRow>
                  {task.config.frontend_env_content && (
                    <DetailRow label="Env file" mono>
                      {task.config.frontend_env_filename}
                    </DetailRow>
                  )}
                </>
              )}

              {/* Docker settings */}
              {task.config.docker_enabled && (
                <>
                  {task.config.docker_image_name && (
                    <DetailRow label="Docker image" mono>
                      {task.config.docker_image_name}
                    </DetailRow>
                  )}
                  <DetailRow label="Base image" mono>
                    {task.config.docker_base_image}
                  </DetailRow>
                </>
              )}

              <DetailRow label="Created">
                <span className="text-xs">{new Date(task.created_at).toLocaleString()}</span>
              </DetailRow>
            </div>
          </div>
        </div>

        {/* Live log stream — the focus of the page */}
        <div className="lg:col-span-2">
          <div className="flex items-center justify-between mb-2 px-1">
            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--ink-faint)' }}>
              {isActive &&
                (wsConnected ? (
                  <span className="inline-flex items-center gap-1.5 text-matrix-400">
                    <span
                      className="inline-block w-2 h-2 rounded-full"
                      style={{ background: 'currentColor' }}
                    />
                    Streaming live
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-signal-400">
                    <span
                      className="inline-block w-2 h-2 rounded-full"
                      style={{ background: 'currentColor' }}
                    />
                    Reconnecting…
                  </span>
                ))}
            </div>
            <span className="text-xs font-mono" style={{ color: 'var(--ink-faint)' }}>
              {task.logs.length} lines
            </span>
          </div>

          {/* The stream can stop for reasons retrying cannot fix (session
              expired, task evicted from memory). Say so — otherwise the log
              panel just silently stops updating. */}
          {wsStoppedReason && (
            <div className="mb-2 px-3 py-2 rounded-lg text-xs border bg-signal-500/10 border-signal-500/30 text-signal-400">
              Live logs stopped: {wsStoppedReason}
            </div>
          )}

          <LogViewer logs={task.logs} title="Build log" height="calc(100vh - 280px)" />
        </div>
      </div>
    </div>
  )
}
