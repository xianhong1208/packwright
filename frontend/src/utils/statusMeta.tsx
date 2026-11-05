import type { ReactNode } from 'react'
import { ArrowsClockwiseIcon, CheckCircleIcon, ClockIcon, MinusCircleIcon, ProhibitIcon, WarningIcon, XCircleIcon } from '../components/ui/icons'
import type { TaskStatus, VerifyStatus } from '../api/types'

// Single source of truth for task-status presentation. Previously copied
// verbatim into TaskDetail / HistoryDetail / TaskCard / History with three
// different label styles (English "Running" vs Traditional Chinese vs raw enum). Unified here.
export interface StatusMeta {
  color: string
  bgColor: string
  label: string // display label
  icon: ReactNode
}

export const STATUS_META: Record<TaskStatus, StatusMeta> = {
  pending: { color: 'var(--ink-muted)', bgColor: 'color-mix(in srgb, var(--color-steel-500) 14%, transparent)', label: 'Queued', icon: <ClockIcon /> },
  running: { color: 'var(--color-teal-400)', bgColor: 'color-mix(in srgb, var(--color-teal-500) 15%, transparent)', label: 'Running', icon: <ArrowsClockwiseIcon spin /> },
  completed: { color: 'var(--color-matrix-400)', bgColor: 'color-mix(in srgb, var(--color-matrix-500) 15%, transparent)', label: 'Passed', icon: <CheckCircleIcon /> },
  failed: { color: 'var(--color-alert-400)', bgColor: 'color-mix(in srgb, var(--color-alert-500) 15%, transparent)', label: 'Failed', icon: <XCircleIcon /> },
  cancelled: { color: 'var(--color-signal-400)', bgColor: 'color-mix(in srgb, var(--color-signal-500) 15%, transparent)', label: 'Cancelled', icon: <ProhibitIcon /> },
}

export interface VerifyMeta {
  color: string
  bg: string
  label: string
  icon: ReactNode
}

export const VERIFY_META: Record<VerifyStatus, VerifyMeta> = {
  pass: { color: 'var(--color-matrix-400)', bg: 'color-mix(in srgb, var(--color-matrix-500) 15%, transparent)', label: 'Verified', icon: <CheckCircleIcon /> },
  warn: { color: 'var(--color-signal-400)', bg: 'color-mix(in srgb, var(--color-signal-500) 15%, transparent)', label: 'Warning', icon: <WarningIcon /> },
  fail: { color: 'var(--color-alert-400)', bg: 'color-mix(in srgb, var(--color-alert-500) 15%, transparent)', label: 'Verify failed', icon: <XCircleIcon /> },
  skipped: { color: 'var(--ink-muted)', bg: 'color-mix(in srgb, var(--color-steel-500) 14%, transparent)', label: 'Skipped', icon: <MinusCircleIcon /> },
}

// True once a task will no longer change — used to stop polling / WS.
export const TERMINAL_STATUSES: TaskStatus[] = ['completed', 'failed', 'cancelled']
export const isTerminal = (s: TaskStatus | undefined): boolean =>
  s !== undefined && TERMINAL_STATUSES.includes(s)
