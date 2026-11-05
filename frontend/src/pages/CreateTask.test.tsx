/**
 * Integration tests for the New build wizard, written before splitting the
 * 2,200-line CreateTask.tsx into per-step components: they pin what a user sees
 * and what gets submitted, so the split has to keep both.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { BuildConfig } from '../api/types'

const api = vi.hoisted(() => ({
  getSystemInfo: vi.fn(),
  listDirectories: vi.fn(),
  analyzeProject: vi.fn(),
  listPyprojectGroups: vi.fn(),
  detectFrontendConfig: vi.fn(),
  listEnvFiles: vi.fn(),
  readEnvFile: vi.fn(),
  listGitRefs: vi.fn(),
  scanGitTree: vi.fn(),
  previewGitFrontend: vi.fn(),
  create: vi.fn(),
}))
vi.mock('../api/client', () => ({ taskApi: api }))

import CreateTask from './CreateTask'

function renderWizard(state?: unknown) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: '/create', state }]}>
        <Routes>
          <Route path="/create" element={<CreateTask />} />
          <Route path="/task/:id" element={<div>task page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Step titles in the desktop rail, in order. */
function railSteps(): string[] {
  const nav = screen.getByRole('navigation', { name: 'Build steps' })
  return Array.from(nav.querySelectorAll('li')).map((li) => li.textContent ?? '')
}

const rebuildOf = (config: Partial<BuildConfig>) => ({
  rebuild: true,
  projectName: 'again',
  // A stored config is a full dump of BuildConfig; these are the fields the wizard validates.
  config: { project_name: 'again', project_path: '/srv/projects/app', python_version: 'auto', entry_point: 'main.py', ...config } as BuildConfig,
})

async function goToReview() {
  for (let i = 0; i < 6 && !screen.queryByRole('button', { name: /Start (re)?build/ }); i++) {
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: /^Next/ }).at(-1)!)
    })
  }
  return screen.getByRole('button', { name: /Start (re)?build/ })
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('bc_tour_createtask_v1', '1') // the first-visit tour is not under test
  for (const fn of Object.values(api)) fn.mockReset()
  api.getSystemInfo.mockResolvedValue({ cpu_count: 8, python_versions: ['3.12', '3.13'] })
  api.listDirectories.mockResolvedValue({ path: '/srv/projects/app', directories: ['config', 'src'] })
  api.analyzeProject.mockResolvedValue({ directories: [], entry_imports: [], suggested_extra_dirs: [], suggested_data_dirs: [] })
  api.listPyprojectGroups.mockResolvedValue({ groups: [] })
  api.detectFrontendConfig.mockResolvedValue({})
  api.listEnvFiles.mockResolvedValue({ files: [] })
  api.create.mockResolvedValue({ id: 'new-task' })
})

describe('New build wizard', () => {
  it.each([
    ['backend_only', ['Basics', 'Backend', 'Docker', 'Review']],
    ['frontend_only', ['Basics', 'Frontend', 'Docker', 'Review']],
    ['fullstack', ['Basics', 'Backend', 'Frontend', 'Docker', 'Review']],
  ] as const)('shows the steps a %s build needs', async (projectType, expected) => {
    renderWizard(rebuildOf({ project_type: projectType }))
    await waitFor(() => expect(railSteps().length).toBe(expected.length))
    railSteps().forEach((text, i) => expect(text).toContain(expected[i]))
  })

  it('submits what the user entered, with the defaults for the rest', async () => {
    renderWizard()
    fireEvent.change(screen.getByPlaceholderText('my-project'), { target: { value: 'hello-cli' } })
    fireEvent.change(screen.getByPlaceholderText('/path/to/your/project'), { target: { value: '/srv/projects/app' } })

    const start = await goToReview()
    expect(screen.getByText('hello-cli')).toBeInTheDocument() // the review shows it
    await act(async () => {
      fireEvent.click(start)
    })

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    const sent = api.create.mock.calls[0][0]
    expect(sent.project_name).toBe('hello-cli')
    expect(sent.config).toMatchObject({
      project_type: 'backend_only',
      source_type: 'local',
      project_path: '/srv/projects/app',
      entry_point: 'main.py',
      pack_mode: 'external',
      docker_enabled: false,
    })
    await screen.findByText('task page')
  })

  it('does not leave Basics while the project path is missing', async () => {
    renderWizard()
    fireEvent.change(screen.getByPlaceholderText('my-project'), { target: { value: 'x' } })
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: /^Next/ }).at(-1)!)
    })
    expect(screen.queryByRole('button', { name: /Start build/ })).toBeNull()
    expect(railSteps()[0]).toContain('Basics')
    expect(api.create).not.toHaveBeenCalled()
  })

  it('rebuild prefills the stored config and resubmits it', async () => {
    renderWizard(rebuildOf({ project_type: 'backend_only', entry_point: 'src/app.py', pack_mode: 'full', nuitka_jobs: 4 }))
    expect(await screen.findByRole('heading', { name: 'Rebuild' })).toBeInTheDocument()

    const start = await goToReview()
    await act(async () => {
      fireEvent.click(start)
    })

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    expect(api.create.mock.calls[0][0].config).toMatchObject({
      project_path: '/srv/projects/app',
      entry_point: 'src/app.py',
      pack_mode: 'full',
      nuitka_jobs: 4,
    })
  })

  it('keeps a draft of the form and restores it on the next visit', async () => {
    const first = renderWizard()
    fireEvent.change(screen.getByPlaceholderText('my-project'), { target: { value: 'draft-me' } })
    await waitFor(() => expect(localStorage.getItem('createTaskDraft') ?? '').toContain('draft-me'), {
      timeout: 3000,
    })
    first.unmount()

    renderWizard()
    expect(await screen.findByDisplayValue('draft-me')).toBeInTheDocument()
  })
})
