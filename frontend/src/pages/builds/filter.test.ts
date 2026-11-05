import { describe, it, expect } from 'vitest'
import type { HistoryItem } from '../../api/types'
import { DEFAULT_FILTERS, filterBuilds, statusCounts, tookSeconds } from './filter'

const item = (over: Partial<HistoryItem> & { type?: 'backend_only' | 'frontend_only' | 'fullstack' }): HistoryItem => {
  const { type = 'backend_only', ...rest } = over
  return {
    task_id: rest.task_id ?? 'id', user_name: 'admin', project_name: 'p', python_version: '3.13',
    start_time: '2026-11-05T05:00:00', end_time: '2026-11-05T05:00:30', status: 'completed', output_dir: 'dist',
    config: { project_type: type } as HistoryItem['config'],
    ...rest,
  }
}

const items = [
  item({ task_id: 'a', project_name: 'web-shop', type: 'frontend_only', start_time: '2026-11-05T05:00:00', end_time: '2026-11-05T05:00:02' }),
  item({ task_id: 'b', project_name: 'api', status: 'failed', start_time: '2026-11-05T06:00:00', end_time: '2026-11-05T06:01:00' }),
  item({ task_id: 'c', project_name: 'api', status: 'cancelled', start_time: '2026-11-05T07:00:00' }),
  item({ task_id: 'd', project_name: 'worker', status: 'running', user_name: 'mei', start_time: '2026-11-05T08:00:00', end_time: null }),
]
const ids = (xs: HistoryItem[]) => xs.map((x) => x.task_id)

describe('filterBuilds', () => {
  it('lists newest first by default', () => {
    expect(ids(filterBuilds(items, DEFAULT_FILTERS))).toEqual(['d', 'c', 'b', 'a'])
  })
  it('searches project and user names', () => {
    expect(ids(filterBuilds(items, { ...DEFAULT_FILTERS, query: 'API' }))).toEqual(['c', 'b'])
    expect(ids(filterBuilds(items, { ...DEFAULT_FILTERS, query: 'mei' }))).toEqual(['d'])
  })
  it('filters by status and type together', () => {
    expect(ids(filterBuilds(items, { ...DEFAULT_FILTERS, status: 'failed' }))).toEqual(['b'])
    expect(ids(filterBuilds(items, { ...DEFAULT_FILTERS, type: 'frontend_only' }))).toEqual(['a'])
    expect(ids(filterBuilds(items, { ...DEFAULT_FILTERS, status: 'completed', type: 'backend_only' }))).toEqual([])
  })
  it('sorts by duration, unfinished builds last', () => {
    expect(ids(filterBuilds(items, { ...DEFAULT_FILTERS, sort: 'longest' }))).toEqual(['b', 'a', 'c', 'd'])
  })
})

describe('statusCounts', () => {
  it('counts per status within the other filters', () => {
    const c = statusCounts(items, { ...DEFAULT_FILTERS, query: 'api' })
    expect([c.all, c.failed, c.cancelled, c.completed, c.running]).toEqual([2, 1, 1, 0, 0])
  })
})

describe('tookSeconds', () => {
  it('measures how long a build took', () => {
    expect(tookSeconds(items[1])).toBe(60)
    expect(tookSeconds(items[3])).toBeNull()
  })
})
