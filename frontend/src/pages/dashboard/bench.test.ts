import { describe, it, expect } from 'vitest'
import type { HistoryItem, TaskResponse } from '../../api/types'
import { BENCH_LIMIT, benchDays, coreHeat, duration, outcomeLine, stageTrack } from './bench'

const hist = (over: Partial<HistoryItem>): HistoryItem => ({
  task_id: 't', user_name: 'admin', project_name: 'p', python_version: '3.13',
  start_time: '2026-11-05T05:00:00', end_time: '2026-11-05T05:00:32', status: 'completed', output_dir: 'dist',
  ...over,
})
const task = (over: Omit<Partial<TaskResponse>, 'config'> & { config?: Partial<TaskResponse['config']> }): TaskResponse => ({
  id: 'r', user_name: 'admin', project_name: 'live', python_version: '3.13', status: 'running', progress: 40,
  status_msg: '', stage: 'compile', created_at: '2026-11-05T06:00:00', updated_at: null, logs: [], result: null,
  ...over,
  config: { project_type: 'backend_only', docker_enabled: false, ...(over.config ?? {}) } as TaskResponse['config'],
})

describe('benchDays', () => {
  const now = new Date(2026, 10, 5, 12, 0)
  it('puts running builds first under Today, then finished ones newest first by day', () => {
    const days = benchDays(
      [task({ id: 'r1' })],
      [
        hist({ task_id: 'old', start_time: new Date(2026, 10, 4, 9).toISOString() }),
        hist({ task_id: 'new', start_time: new Date(2026, 10, 5, 9).toISOString() }),
        hist({ task_id: 'r1', status: 'running', start_time: new Date(2026, 10, 5, 11).toISOString() }),
      ],
      now,
    )
    expect(days.map((d) => d.label)).toEqual(['Today', 'Yesterday'])
    expect(days[0].entries.map((e) => (e.kind === 'running' ? e.task.id : e.kind === 'finished' ? e.item.task_id : 'run'))).toEqual(['r1', 'new'])
    expect(days[1].entries).toHaveLength(1)
  })
})

describe('benchDays folding', () => {
  const now = new Date(2026, 10, 5, 12, 0)
  const at = (h: number, m: number) => new Date(2026, 10, 5, h, m).toISOString()
  it('folds three or more cancelled builds in a row into one line, keeps shorter runs', () => {
    const days = benchDays([], [
      hist({ task_id: 'ok', start_time: at(11, 0) }),
      ...[1, 2, 3, 4].map((i) => hist({ task_id: `c${i}`, status: 'cancelled', start_time: at(10, 10 - i) })),
      hist({ task_id: 'fail', status: 'failed', start_time: at(9, 0) }),
      ...[1, 2].map((i) => hist({ task_id: `d${i}`, status: 'cancelled', start_time: at(8, 10 - i) })),
    ], now)
    expect(days[0].entries.map((e) => (e.kind === 'cancelled-run' ? `run:${e.items.length}` : e.kind === 'finished' ? e.item.task_id : 'r')))
      .toEqual(['ok', 'run:4', 'fail', 'd1', 'd2'])
  })
  it('shows at most BENCH_LIMIT entries', () => {
    const many = Array.from({ length: 30 }, (_, i) => hist({ task_id: `p${i}`, start_time: at(11, 59 - i) }))
    expect(benchDays([], many, now).flatMap((d) => d.entries)).toHaveLength(BENCH_LIMIT)
  })
})

describe('outcomeLine', () => {
  it('says how long a passed build took and what it produced', () => {
    const line = outcomeLine(hist({ result: { artifact: { size_human: '37.8 MB' }, verify: { status: 'pass' } } as HistoryItem['result'] }))
    expect(line).toEqual({ verdict: 'Passed in 32 s', detail: '37.8 MB, smoke test passed', next: 'Download' })
  })
  it('names the stage a failed build stopped in and its first diagnosis', () => {
    const line = outcomeLine(hist({ status: 'failed', result: { failed_stage: 'frontend', diagnosis: [{ problem: 'No package.json' }] } as HistoryItem['result'] }))
    expect(line).toEqual({ verdict: 'Failed in frontend', detail: 'No package.json', next: 'See why' })
  })
  it('offers a rebuild for a cancelled build', () => {
    expect(outcomeLine(hist({ status: 'cancelled' })).next).toBe('Rebuild')
  })
})

describe('stageTrack', () => {
  const keys = (t: TaskResponse) => stageTrack(t).map((s) => s.key)
  it('follows the stages each kind of build goes through', () => {
    expect(keys(task({}))).toEqual(['preflight', 'compile', 'bundle', 'verify'])
    expect(keys(task({ config: { project_type: 'frontend_only' } }))).toEqual(['frontend'])
    expect(keys(task({ config: { project_type: 'fullstack', docker_enabled: true } }))).toEqual(['frontend', 'preflight', 'compile', 'bundle', 'verify', 'docker'])
  })
  it('marks finished, current and coming stages', () => {
    expect(stageTrack(task({ stage: 'compile' })).map((s) => s.state)).toEqual(['done', 'on', 'todo', 'todo'])
    expect(stageTrack(task({ stage: 'queued' })).every((s) => s.state === 'todo')).toBe(true)
  })
})

describe('coreHeat', () => {
  it('averages 128 cores into 16 cells of 8', () => {
    const perCore = Array.from({ length: 128 }, (_, i) => (i === 1 ? 80 : 0))
    const heat = coreHeat(perCore, 16)
    expect(heat).toHaveLength(16)
    expect(heat[0]).toBe(10) // one core at 80% among eight
    expect(heat.slice(1).every((v) => v === 0)).toBe(true)
  })
  it('keeps one cell per core on a small machine', () => {
    expect(coreHeat([10, 20, 30, 40], 16)).toEqual([10, 20, 30, 40])
  })
})

describe('duration', () => {
  it('reads like speech', () => {
    expect(duration(2)).toBe('2 s')
    expect(duration(78)).toBe('1 min 18 s')
    expect(duration(120)).toBe('2 min')
  })
})
