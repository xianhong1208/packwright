import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ProjectSchedule } from '../../api/types'

const api = vi.hoisted(() => ({
  schedules: vi.fn(), previewSchedule: vi.fn(), addSchedule: vi.fn(), updateSchedule: vi.fn(),
  removeSchedule: vi.fn(), scheduleRuns: vi.fn(),
}))
vi.mock('../../api/client', () => ({ projectApi: api }))

import Schedules from './Schedules'
import { timeUntil, zonedTime } from '../../utils/time'

const schedule: ProjectSchedule = {
  id: 7, cron: '0 2 * * *', description: 'At 02:00', timezone: 'Asia/Taipei', ref: 'main', ref_type: 'branch',
  skip_unchanged: true, enabled: true, disabled_reason: null, next_run_at: '2026-11-22T18:00:00Z',
  last_run_at: '2026-11-21T18:00:05', created_by: 'tony', created_at: '2026-11-20T00:00:00', can_edit: true,
  last_run: {
    id: 1, due_at: '2026-11-21T18:00:00', ran_at: '2026-11-21T18:00:05', result: 'skipped',
    reason: 'unchanged: commit abc and the settings were built as 12345678', commit_sha: 'a'.repeat(40), task_id: '12345678-aaaa',
  },
}

function show(props: Partial<{ canEdit: boolean; fromGit: boolean }> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Schedules projectId={3} canEdit={props.canEdit ?? true} fromGit={props.fromGit ?? true}
          defaultRef="develop" defaultRefType="branch" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  api.schedules.mockResolvedValue([schedule])
  api.previewSchedule.mockImplementation(async (_id: number, body: { cron: string; timezone?: string }) => ({
    cron: body.cron, timezone: body.timezone ?? 'Europe/Berlin', description: 'At 02:00',
    next_runs: ['2026-11-23T01:00:00Z', '2026-11-24T01:00:00Z', '2026-11-25T01:00:00Z'],
  }))
})

describe('Project schedules', () => {
  it('lists a schedule with its expression, zone, branch, next and last run and who it builds as', async () => {
    show()
    const card = await screen.findByRole('region', { name: 'Schedule 0 2 * * *' })
    expect(within(card).getByText('At 02:00')).toBeInTheDocument()
    expect(within(card).getByText('Asia/Taipei')).toBeInTheDocument()
    expect(within(card).getByText('main')).toBeInTheDocument()
    expect(within(card).getByText('tony')).toBeInTheDocument()
    expect(within(card).getByText(/Skipped/)).toBeInTheDocument()
    // 18:00 UTC is 02:00 the next day in Taipei.
    expect(within(card).getByText(/Nov.*02:00/)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Schedule 0 2 * * * on' })).toBeChecked()
  })

  it('adds a schedule: the dialog shows the next run times in the server zone, then saves', async () => {
    api.addSchedule.mockResolvedValue({ ...schedule, id: 8 })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /Add a schedule/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Branch name')).toHaveValue('develop')
    const times = await within(dialog).findByRole('list', { name: 'Next run times' })
    expect(within(times).getAllByRole('listitem')).toHaveLength(3)
    expect(within(dialog).getByText(/Next runs \(Europe\/Berlin\)/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByText('Hourly'))
    expect(within(dialog).getByLabelText('Cron expression')).toHaveValue('0 * * * *')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add schedule' }))
    await waitFor(() => expect(api.addSchedule).toHaveBeenCalledWith(3, {
      cron: '0 * * * *', timezone: 'Europe/Berlin', ref: 'develop', ref_type: 'branch', skip_unchanged: true,
    }))
  })

  it('shows why an expression cannot be used and will not save it', async () => {
    api.previewSchedule.mockRejectedValue(new Error('Invalid cron expression: Bad minute'))
    show()
    fireEvent.click(await screen.findByRole('button', { name: /Add a schedule/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Cron expression'), { target: { value: '61 * * * *' } })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Bad minute')
    expect(within(dialog).getByRole('button', { name: 'Add schedule' })).toBeDisabled()
  })

  it('shows why Packwright turned a schedule off and offers to take it over', async () => {
    api.schedules.mockResolvedValue([{ ...schedule, enabled: false, next_run_at: null, disabled_reason: "tony's account is deactivated" }])
    api.updateSchedule.mockResolvedValue(schedule)
    show()
    expect(await screen.findByText(/Turned off: tony's account is deactivated/)).toBeInTheDocument()
    expect(screen.getByText('none (off)')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Take it over and turn it on' }))
    await waitFor(() => expect(api.updateSchedule).toHaveBeenCalledWith(3, 7, { enabled: true, take_over: true }))
  })

  it('lists runs with the build they started or matched and the reason', async () => {
    api.scheduleRuns.mockResolvedValue([
      { id: 2, due_at: '2026-11-21T18:00:00', ran_at: '2026-11-21T18:00:03', result: 'built', reason: null,
        commit_sha: 'b'.repeat(40), task_id: 'abcdef12-3456' },
      { id: 1, due_at: '2026-11-21T17:00:00', ran_at: '2026-11-21T17:00:03', result: 'skipped',
        reason: 'overlap: build abcdef12 of this project is still queued or running', commit_sha: null, task_id: 'abcdef12-3456' },
    ])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Runs' }))
    const runs = await screen.findByRole('list', { name: 'Runs' })
    expect(within(runs).getByText('Built')).toBeInTheDocument()
    expect(within(runs).getByText(/overlap: build abcdef12/)).toBeInTheDocument()
    expect(within(runs).getAllByRole('link', { name: 'Build abcdef12' })[0]).toHaveAttribute('href', '/history/abcdef12-3456')
  })

  it('hides changes from someone who may not make them, and folder projects get none', async () => {
    api.schedules.mockResolvedValue([{ ...schedule, can_edit: false }])
    show({ canEdit: false })
    await screen.findByRole('region', { name: 'Schedule 0 2 * * *' })
    expect(screen.queryByRole('button', { name: /Add a schedule/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    expect(screen.getByRole('switch', { name: 'Schedule 0 2 * * * on' })).toBeDisabled()
  })

  it('formats times in the schedule zone and counts down to them', () => {
    expect(zonedTime('2026-11-22T18:00:00Z', 'Asia/Taipei')).toMatch(/02:00/)
    expect(zonedTime('2026-11-22T18:00:00', 'UTC')).toMatch(/18:00/)
    const now = Date.parse('2026-11-22T17:55:00Z')
    expect(timeUntil('2026-11-22T18:00:00Z', now)).toBe('in 5 min')
    expect(timeUntil('2026-11-22T17:55:20Z', now)).toBe('in under a minute')
    expect(timeUntil('2026-11-25T18:00:00Z', now)).toBe('in 3 days')
  })
})
