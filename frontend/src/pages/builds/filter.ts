// Filtering and ordering for the Builds list, kept pure so it can be tested.
import type { HistoryItem, ProjectType, TaskStatus } from '../../api/types'
import { parseUtc } from '../../utils/time'

export type StatusFilter = 'all' | TaskStatus
export type SortOrder = 'newest' | 'oldest' | 'longest'

export interface BuildFilters {
  query: string
  status: StatusFilter
  type: 'all' | ProjectType
  sort: SortOrder
}

export const DEFAULT_FILTERS: BuildFilters = { query: '', status: 'all', type: 'all', sort: 'newest' }

/** Seconds a finished build took; null while it has no end time. */
export function tookSeconds(item: HistoryItem): number | null {
  if (!item.end_time) return null
  const s = (parseUtc(item.end_time).getTime() - parseUtc(item.start_time).getTime()) / 1000
  return s >= 0 ? s : null
}

/** Builds matching the search, type and status, in the chosen order. */
export function filterBuilds(items: HistoryItem[], f: BuildFilters): HistoryItem[] {
  const q = f.query.trim().toLowerCase()
  const out = items.filter(
    (i) =>
      (!q || i.project_name.toLowerCase().includes(q) || i.user_name.toLowerCase().includes(q)) &&
      (f.type === 'all' || i.config?.project_type === f.type) &&
      (f.status === 'all' || i.status === f.status || (f.status === 'running' && i.status === 'pending')),
  )
  const time = (i: HistoryItem) => parseUtc(i.start_time).getTime()
  if (f.sort === 'newest') out.sort((a, b) => time(b) - time(a))
  if (f.sort === 'oldest') out.sort((a, b) => time(a) - time(b))
  if (f.sort === 'longest') out.sort((a, b) => (tookSeconds(b) ?? -1) - (tookSeconds(a) ?? -1))
  return out
}

/** How many builds each status chip would show, given the other filters. */
export function statusCounts(items: HistoryItem[], f: BuildFilters): Record<StatusFilter, number> {
  const base = filterBuilds(items, { ...f, status: 'all' })
  const count = (s: TaskStatus) => base.filter((i) => i.status === s).length
  return {
    all: base.length,
    running: count('running') + count('pending'),
    pending: count('pending'),
    completed: count('completed'),
    failed: count('failed'),
    cancelled: count('cancelled'),
  }
}

