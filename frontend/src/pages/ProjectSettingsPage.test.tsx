import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ProjectDetail } from '../api/types'

const api = vi.hoisted(() => ({
  project: { get: vi.fn(), update: vi.fn() },
  task: {
    getSystemInfo: vi.fn(), listDirectories: vi.fn(), analyzeProject: vi.fn(), listPyprojectGroups: vi.fn(),
    detectFrontendConfig: vi.fn(), listEnvFiles: vi.fn(), diagnoseRepo: vi.fn(), previewCommands: vi.fn(),
    listGitRefs: vi.fn(), scanGitTree: vi.fn(), previewGitFrontend: vi.fn(),
  },
}))
vi.mock('../api/client', () => ({ projectApi: api.project, taskApi: api.task }))

import ProjectSettingsPage from './ProjectSettingsPage'

const project = (over: Partial<ProjectDetail> = {}, config: Record<string, unknown> = {}): ProjectDetail => ({
  id: 3, name: 'shop', project_type: 'backend_only', source_type: 'local', source: '/srv/shop',
  created_by: 'tony', created_at: '2026-11-01T00:00:00', updated_at: '2026-11-01T00:00:00',
  builds: 0, latest: null, last_passed: null, can_edit: true, history: [],
  config: {
    project_type: 'backend_only', source_type: 'local', project_path: '/srv/shop', git_url: '', git_ref: '', git_ref_type: 'branch',
    entry_point: 'main.py', pack_mode: 'full', onefile: false, python_version: 'auto', output_dir: 'dist',
    frontend_dir: '.', frontend_build_tool: 'pnpm', frontend_build_command: 'build:prod', frontend_output_dir: 'dist', ...config,
  } as unknown as ProjectDetail['config'],
  ...over,
})

function openSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/3/settings']}>
        <Routes>
          <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
          <Route path="/projects/:projectId" element={<div>project page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.setItem('bc_tour_createtask_v1', '1')
  for (const group of Object.values(api)) for (const fn of Object.values(group)) fn.mockReset()
  api.task.getSystemInfo.mockResolvedValue({ cpu_count: 8, python_versions: ['3.13'] })
  api.task.listDirectories.mockResolvedValue({ path: '/srv/shop', directories: [] })
  api.task.analyzeProject.mockResolvedValue({ directories: [], entry_imports: [], suggested_extra_dirs: [], suggested_data_dirs: [] })
  api.task.listPyprojectGroups.mockResolvedValue({ groups: [] })
  api.task.listEnvFiles.mockResolvedValue({ files: [] })
  api.task.diagnoseRepo.mockResolvedValue({ checks: [] })
  api.task.previewCommands.mockResolvedValue({ steps: [], notes: [] })
  api.task.detectFrontendConfig.mockResolvedValue({ detected: false })
  api.project.update.mockResolvedValue(project())
})

describe('Project settings', () => {
  it('saves what was changed and keeps everything else as stored', async () => {
    api.project.get.mockResolvedValue(project())
    // The code states a version; a project's settings have none, so it must not slip in.
    api.task.diagnoseRepo.mockResolvedValue({ checks: [], version: { value: '9.9.9', source: 'pyproject.toml' } })
    openSettings()

    expect(await screen.findByRole('tab', { name: 'Backend' })).toBeInTheDocument()
    await waitFor(() => expect(api.task.diagnoseRepo).toHaveBeenCalled(), { timeout: 3000 })
    expect(screen.queryByLabelText('Version')).toBeNull() // a version belongs to a build
    fireEvent.change(screen.getByDisplayValue('main.py'), { target: { value: 'server.py' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save as defaults/ }))
    })

    await waitFor(() => expect(api.project.update).toHaveBeenCalledTimes(1))
    const [id, body] = api.project.update.mock.calls[0]
    expect(id).toBe(3)
    expect(body.name).toBe('shop')
    expect(body.config).toMatchObject({ entry_point: 'server.py', pack_mode: 'full', onefile: false })
    expect(body.config.version).toBe('')
  })

  it('offers what the project says instead of overwriting a stored setting', async () => {
    api.project.get.mockResolvedValue(project({ project_type: 'frontend_only' }, { project_type: 'frontend_only' }))
    api.task.detectFrontendConfig.mockResolvedValue({ detected: true, build_tool: 'npm', build_command: 'build', output_dir: 'dist' })
    openSettings()
    await act(async () => {
      fireEvent.click(await screen.findByRole('tab', { name: 'Frontend' }))
    })

    expect(await screen.findByText('build', { selector: 'code' }, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByDisplayValue('build:prod')).toBeInTheDocument()

    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: 'Use it' })[1])
    })
    expect(screen.getByDisplayValue('build')).toBeInTheDocument()
  })

  it('lets only its creator or a project manager save', async () => {
    api.project.get.mockResolvedValue(project({ can_edit: false }))
    openSettings()
    expect(await screen.findByRole('button', { name: /Save as defaults/ })).toBeDisabled()
    expect(screen.getByText(/Only tony or a project manager/)).toBeInTheDocument()
  })
})
