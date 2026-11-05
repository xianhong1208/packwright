import type { ReactNode } from 'react'
import {
  ClockCircleOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  StopOutlined,
  WarningOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
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
  pending: { color: 'var(--ink-muted)', bgColor: 'color-mix(in srgb, var(--color-steel-500) 14%, transparent)', label: 'Queued', icon: <ClockCircleOutlined /> },
  running: { color: 'var(--color-teal-400)', bgColor: 'color-mix(in srgb, var(--color-teal-500) 15%, transparent)', label: 'Running', icon: <SyncOutlined spin /> },
  completed: { color: 'var(--color-matrix-400)', bgColor: 'color-mix(in srgb, var(--color-matrix-500) 15%, transparent)', label: 'Passed', icon: <CheckCircleOutlined /> },
  failed: { color: 'var(--color-alert-400)', bgColor: 'color-mix(in srgb, var(--color-alert-500) 15%, transparent)', label: 'Failed', icon: <CloseCircleOutlined /> },
  cancelled: { color: 'var(--color-signal-400)', bgColor: 'color-mix(in srgb, var(--color-signal-500) 15%, transparent)', label: 'Cancelled', icon: <StopOutlined /> },
}

export interface VerifyMeta {
  color: string
  bg: string
  label: string
  icon: ReactNode
}

export const VERIFY_META: Record<VerifyStatus, VerifyMeta> = {
  pass: { color: 'var(--color-matrix-400)', bg: 'color-mix(in srgb, var(--color-matrix-500) 15%, transparent)', label: 'Verified', icon: <CheckCircleOutlined /> },
  warn: { color: 'var(--color-signal-400)', bg: 'color-mix(in srgb, var(--color-signal-500) 15%, transparent)', label: 'Warning', icon: <WarningOutlined /> },
  fail: { color: 'var(--color-alert-400)', bg: 'color-mix(in srgb, var(--color-alert-500) 15%, transparent)', label: 'Verify failed', icon: <CloseCircleOutlined /> },
  skipped: { color: 'var(--ink-muted)', bg: 'color-mix(in srgb, var(--color-steel-500) 14%, transparent)', label: 'Skipped', icon: <MinusCircleOutlined /> },
}

// True once a task will no longer change — used to stop polling / WS.
export const TERMINAL_STATUSES: TaskStatus[] = ['completed', 'failed', 'cancelled']
export const isTerminal = (s: TaskStatus | undefined): boolean =>
  s !== undefined && TERMINAL_STATUSES.includes(s)
