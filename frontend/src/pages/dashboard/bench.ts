// Pure helpers for the On the bench page: grouping builds into days, the one-line
// outcome of a finished build, the stage track of a running one, CPU heat cells.
import type { HistoryItem, TaskResponse } from '../../api/types'
import { parseUtc } from '../../utils/time'
import { STAGE_LABELS } from '../../components/build/stages'

export type BenchEntry =
  | { kind: 'running'; at: Date; task: TaskResponse }
  | { kind: 'finished'; at: Date; item: HistoryItem }
  | { kind: 'cancelled-run'; at: Date; items: HistoryItem[] }

/** Entries shown on the bench; the rest are one click away under Builds. */
export const BENCH_LIMIT = 12
/** This many cancelled builds in a row fold into one line. */
const CANCEL_RUN = 3

export function dayLabel(d: Date, now = new Date()): string {
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((start(now) - start(d)) / 86_400_000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })
}

/**
 * Running builds first, then finished ones newest first, grouped by day. A run
 * of cancelled builds folds into one line, and at most BENCH_LIMIT entries show.
 */
export function benchDays(running: TaskResponse[], history: HistoryItem[], now = new Date()) {
  const runningIds = new Set(running.map((t) => t.id))
  const entries: BenchEntry[] = [
    ...running
      .map((task) => ({ kind: 'running' as const, at: parseUtc(task.created_at), task }))
      .sort((a, b) => b.at.getTime() - a.at.getTime()),
    ...history
      .filter((h) => !runningIds.has(h.task_id) && h.status !== 'running' && h.status !== 'pending')
      .map((item) => ({ kind: 'finished' as const, at: parseUtc(item.start_time), item }))
      .sort((a, b) => b.at.getTime() - a.at.getTime()),
  ]
  const folded: BenchEntry[] = []
  for (const e of entries) {
    const last = folded[folded.length - 1]
    const cancelled = e.kind === 'finished' && e.item.status === 'cancelled'
    if (cancelled && last?.kind === 'cancelled-run' && dayLabel(last.at, now) === dayLabel(e.at, now)) {
      last.items.push(e.item)
    } else if (cancelled) {
      folded.push({ kind: 'cancelled-run', at: e.at, items: [e.item] })
    } else {
      folded.push(e)
    }
  }
  // Short runs read better as the builds themselves.
  const shown = folded
    .flatMap((e): BenchEntry[] =>
      e.kind === 'cancelled-run' && e.items.length < CANCEL_RUN
        ? e.items.map((item) => ({ kind: 'finished' as const, at: parseUtc(item.start_time), item }))
        : [e],
    )
    .slice(0, BENCH_LIMIT)
  const days: { label: string; entries: BenchEntry[] }[] = []
  for (const e of shown) {
    // Running builds always sit under "Today", whenever they were queued.
    const label = e.kind === 'running' ? 'Today' : dayLabel(e.at, now)
    const day = days.find((d) => d.label === label)
    if (day) day.entries.push(e)
    else days.push({ label, entries: [e] })
  }
  return days
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s ? `${m} min ${s} s` : `${m} min`
}

/** What a finished build's row says: its verdict, a detail, and what to do next. */
export function outcomeLine(item: HistoryItem): { verdict: string; detail: string; next: string } {
  const took = item.end_time ? (parseUtc(item.end_time).getTime() - parseUtc(item.start_time).getTime()) / 1000 : null
  const r = item.result
  switch (item.status) {
    case 'completed': {
      const size = r?.artifact?.size_human
      const smoke = r?.verify?.status === 'pass' ? 'smoke test passed' : r?.verify?.status === 'warn' ? 'smoke test warning' : ''
      return {
        verdict: took != null ? `Passed in ${duration(took)}` : 'Passed',
        detail: [size, smoke].filter(Boolean).join(', '),
        next: 'Download',
      }
    }
    case 'failed': {
      const stage = r?.failed_stage ? (STAGE_LABELS[r.failed_stage] ?? r.failed_stage).split(' (')[0].toLowerCase() : ''
      return {
        verdict: stage ? `Failed in ${stage}` : 'Failed',
        detail: r?.diagnosis?.[0]?.problem ?? '',
        next: 'See why',
      }
    }
    case 'cancelled':
      return { verdict: 'Cancelled', detail: '', next: 'Rebuild' }
    default:
      return { verdict: item.status, detail: '', next: '' }
  }
}

/** The stages a running build goes through, given its type, and where it is. */
export function stageTrack(task: TaskResponse): { key: string; label: string; state: 'done' | 'on' | 'todo' }[] {
  const type = task.config.project_type
  const keys = [
    ...(type !== 'backend_only' ? ['frontend'] : []),
    ...(type !== 'frontend_only' ? ['preflight', 'compile', 'bundle', 'verify'] : []),
    ...(task.config.docker_enabled ? ['docker'] : []),
  ]
  const at = keys.indexOf(task.stage)
  return keys.map((key, i) => ({
    key,
    label: (STAGE_LABELS[key] ?? key).split(' (')[0],
    state: at < 0 ? 'todo' : i < at ? 'done' : i === at ? 'on' : 'todo',
  }))
}

/** Average per-core load into `cells` groups (128 cores become 16 squares of 8). */
export function coreHeat(perCore: number[], cells: number): number[] {
  if (perCore.length === 0) return []
  const n = Math.min(cells, perCore.length)
  const size = Math.ceil(perCore.length / n)
  return Array.from({ length: Math.ceil(perCore.length / size) }, (_, i) => {
    const group = perCore.slice(i * size, (i + 1) * size)
    return group.reduce((a, b) => a + b, 0) / group.length
  })
}

/** Colour of one heat cell: idle, light, busy, saturated. */
export const heatColor = (pct: number): string =>
  pct >= 85
    ? 'var(--color-cyber-500)'
    : pct >= 40
      ? 'var(--color-matrix-500)'
      : pct >= 5
        ? 'color-mix(in srgb, var(--color-matrix-500) 45%, var(--color-void-700))'
        : 'var(--color-void-700)'
