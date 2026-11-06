import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ProjectDetail } from '../../api/types'

const api = vi.hoisted(() => ({
  project: { get: vi.fn(), build: vi.fn() },
  task: { diagnoseRepo: vi.fn(), listGitRefs: vi.fn(), scanGitTree: vi.fn() },
}))
vi.mock('../../api/client', () => ({ projectApi: api.project, taskApi: api.task }))

import BuildVersionModal from './BuildVersionModal'

const project = (over: Partial<ProjectDetail> = {}): ProjectDetail => ({
  id: 7, name: 'shop', project_type: 'backend_only', source_type: 'local', source: '/srv/shop',
  created_by: 'tony', created_at: '2026-11-01T00:00:00', updated_at: '2026-11-01T00:00:00',
  builds: 1, latest: null, last_passed: null, can_edit: true,
  config: { pack_mode: 'external', onefile: true, verify_after_build: true, docker_enabled: false, git_ref: '', git_ref_type: 'branch' } as ProjectDetail['config'],
  history: [{ task_id: 'old', version: '1.2.0', status: 'completed', user_name: 'mei', start_time: '2026-11-05T00:00:00', end_time: null }],
  ...over,
})

function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><BuildVersionModal projectId={7} open onClose={() => {}} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  for (const group of Object.values(api)) for (const fn of Object.values(group)) fn.mockReset()
  api.project.build.mockResolvedValue({ id: 'new-task' })
})

describe('Build a new version', () => {
  it('reads the version from the code and says when it already passed', async () => {
    api.project.get.mockResolvedValue(project())
    api.task.diagnoseRepo.mockResolvedValue({ checks: [], version: { value: '1.2.0', source: 'pyproject.toml' } })
    open()

    expect(await screen.findByDisplayValue('1.2.0')).toBeInTheDocument()
    expect(screen.getByText(/Read from pyproject.toml/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('1.2.0 already passed')

    fireEvent.change(screen.getByLabelText('Version'), { target: { value: '1.3.0' } })
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('builds with the version and the settings chosen', async () => {
    api.project.get.mockResolvedValue(project())
    api.task.diagnoseRepo.mockResolvedValue({ checks: [], version: null })
    open()

    fireEvent.change(await screen.findByLabelText('Version'), { target: { value: '2.0.0' } })
    await act(async () => {
      fireEvent.click(screen.getByText('Full'))
      fireEvent.click(screen.getByRole('switch', { name: 'Docker image' }))
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Build 2.0.0/ }))
    })

    await waitFor(() => expect(api.project.build).toHaveBeenCalledTimes(1))
    expect(api.project.build).toHaveBeenCalledWith(7, {
      version: '2.0.0',
      overrides: { pack_mode: 'full', onefile: true, verify_after_build: true, docker_enabled: true },
    })
  })

  it('takes a tag as the version, and builds that tag', async () => {
    api.project.get.mockResolvedValue(project({
      source_type: 'git', source: 'https://git.example.com/shop.git',
      config: { ...project().config, git_ref: 'v3.0.0', git_ref_type: 'tag' },
    }))
    api.task.listGitRefs.mockResolvedValue({ branches: ['main'], tags: ['v3.0.0'] })
    open()

    expect(await screen.findByDisplayValue('v3.0.0')).toBeInTheDocument()
    expect(api.task.scanGitTree).not.toHaveBeenCalled()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Build v3.0.0/ }))
    })
    await waitFor(() => expect(api.project.build).toHaveBeenCalled())
    expect(api.project.build.mock.calls[0][1].overrides).toMatchObject({ git_ref: 'v3.0.0', git_ref_type: 'tag' })
  })
})
