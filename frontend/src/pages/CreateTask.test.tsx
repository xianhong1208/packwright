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
  diagnoseRepo: vi.fn(),
  create: vi.fn(),
}))
const projects = vi.hoisted(() => ({ sameVersion: vi.fn() }))
vi.mock('../api/client', () => ({ taskApi: api, projectApi: projects }))

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

/** New build opens on Quick build; the wizard is behind "All settings". */
async function openAllSettings() {
  await act(async () => {
    fireEvent.click(await screen.findByRole('button', { name: /All settings/ }))
  })
}

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
  api.diagnoseRepo.mockResolvedValue({ checks: [] })
  projects.sameVersion.mockReset()
  projects.sameVersion.mockResolvedValue([])
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
    await openAllSettings()
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
    await openAllSettings()
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

  it('rebuild keeps the stored frontend build command when detection says otherwise', async () => {
    api.detectFrontendConfig.mockResolvedValue({ detected: true, build_tool: 'npm', build_command: 'build', output_dir: 'dist' })
    renderWizard(rebuildOf({ project_type: 'frontend_only', frontend_dir: '.', frontend_build_tool: 'pnpm', frontend_build_command: 'build:prod' }))
    await waitFor(() => expect(api.detectFrontendConfig).toHaveBeenCalled(), { timeout: 3000 })

    const start = await goToReview()
    await act(async () => {
      fireEvent.click(start)
    })
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    expect(api.create.mock.calls[0][0].config).toMatchObject({ frontend_build_tool: 'pnpm', frontend_build_command: 'build:prod' })
  })

  it('keeps a draft of the form and restores it on the next visit', async () => {
    const first = renderWizard()
    await openAllSettings()
    fireEvent.change(screen.getByPlaceholderText('my-project'), { target: { value: 'draft-me' } })
    await waitFor(() => expect(localStorage.getItem('createTaskDraft') ?? '').toContain('draft-me'), {
      timeout: 3000,
    })
    first.unmount()

    renderWizard()
    await openAllSettings()
    expect(await screen.findByDisplayValue('draft-me')).toBeInTheDocument()
  })
})

const ok = (key: string, path: string) => ({ key, label: '', status: 'ok' as const, path })
const FULLSTACK = [ok('entry_point', 'app/main.py'), ok('package_json', 'frontend/package.json'), ok('pyproject', 'pyproject.toml')]

async function pointAt(path: string) {
  fireEvent.change(screen.getByLabelText('Project folder'), { target: { value: path } })
}

describe('Quick build', () => {
  it('reads the project, names the build after its folder and submits what it found', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: FULLSTACK })
    renderWizard()
    await pointAt('/srv/projects/shop')

    expect(await screen.findByText(/A frontend and a Python backend/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByLabelText('Build name')).toHaveValue('shop')
    // The frontend field is not on this screen; what it shows must still be what is sent.
    expect(await screen.findByText('frontend/')).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Start build/ }))
    })

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    expect(api.create.mock.calls[0][0]).toMatchObject({
      project_name: 'shop',
      config: { project_type: 'fullstack', project_path: '/srv/projects/shop', entry_point: 'app/main.py', frontend_dir: 'frontend' },
    })
  })

  it('asks for the type when the files do not say, and will not start on a guess nobody made', async () => {
    renderWizard()
    await pointAt('/srv/projects/odd')

    expect(await screen.findByText(/Could not tell from the files/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start build/ })).toBeDisabled()

    await act(async () => {
      fireEvent.click(screen.getByText('Frontend'))
    })
    expect(screen.getByRole('button', { name: /Start build/ })).toBeEnabled()
  })

  it('keeps what it found when switching to All settings', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: FULLSTACK })
    renderWizard()
    await pointAt('/srv/projects/shop')
    await screen.findByText(/A frontend and a Python backend/, {}, { timeout: 3000 })

    await openAllSettings()

    expect(screen.getByPlaceholderText('my-project')).toHaveValue('shop')
    expect(screen.getByPlaceholderText('/path/to/your/project')).toHaveValue('/srv/projects/shop')
    await waitFor(() => expect(railSteps().length).toBe(5)) // full stack: Basics, Backend, Frontend, Docker, Review
  })

  it('does not replace a name the person typed when the folder changes', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: FULLSTACK })
    renderWizard()
    await pointAt('/srv/projects/shop')
    await screen.findByText(/A frontend and a Python backend/, {}, { timeout: 3000 })
    fireEvent.change(screen.getByLabelText('Build name'), { target: { value: 'storefront' } })

    await pointAt('/srv/projects/shop-v2')
    await waitFor(() => expect(api.diagnoseRepo).toHaveBeenLastCalledWith('/srv/projects/shop-v2'), { timeout: 3000 })

    expect(screen.getByLabelText('Build name')).toHaveValue('storefront')
  })

  it('reads a Git repository the same way, naming the build after it', async () => {
    api.listGitRefs.mockResolvedValue({ branches: ['main'], tags: [] })
    api.scanGitTree.mockResolvedValue({ directories: ['src'], dependency_groups: [], checks: [ok('package_json', 'package.json')] })
    api.previewGitFrontend.mockResolvedValue({ frontend_config: { detected: false }, env_files: {}, frontend_dir_exists: true })
    renderWizard()
    await act(async () => {
      fireEvent.click(screen.getByText('A Git repository'))
    })
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://github.com/acme/storefront.git' } })

    expect(await screen.findByText(/A web frontend, built into static files/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(api.scanGitTree).toHaveBeenCalledWith('https://github.com/acme/storefront.git', 'main', 'branch')
    expect(screen.getByLabelText('Build name')).toHaveValue('storefront')
  })

  it('still scans a Git repository when the type already says frontend', async () => {
    api.listGitRefs.mockResolvedValue({ branches: ['main'], tags: [] })
    api.scanGitTree.mockResolvedValue({ directories: [], dependency_groups: [], checks: FULLSTACK })
    api.previewGitFrontend.mockResolvedValue({ frontend_config: { detected: false }, env_files: {}, frontend_dir_exists: true })
    renderWizard()
    // An unrecognised folder first, set to Frontend by hand...
    await pointAt('/srv/projects/odd')
    await screen.findByText(/Could not tell from the files/, {}, { timeout: 3000 })
    await act(async () => {
      fireEvent.click(screen.getByText('Frontend'))
    })
    // ...then the code turns out to be in Git. The scan is what tells Quick build
    // anything, so it has to run whatever the type says.
    await act(async () => {
      fireEvent.click(screen.getByText('A Git repository'))
    })
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://github.com/acme/shop.git' } })

    await waitFor(() => expect(api.scanGitTree).toHaveBeenCalled(), { timeout: 5000 })
  })

  it('says why a folder could not be read instead of calling it unrecognised', async () => {
    api.diagnoseRepo.mockRejectedValue({ response: { data: { detail: 'Access denied: path must be under /srv/projects' } } })
    renderWizard()
    await pointAt('/media/elsewhere/app')

    expect(await screen.findByText('Access denied: path must be under /srv/projects', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText(/Could not tell from the files/)).toBeNull()
    expect(screen.getByRole('button', { name: /Start build/ })).toBeDisabled()
  })

  it('leaves the entry point empty and required when the usual ones are missing', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: [ok('pyproject', 'pyproject.toml')] })
    renderWizard()
    await pointAt('/srv/projects/tool')

    const entry = await screen.findByLabelText('Entry point', {}, { timeout: 3000 })
    expect(entry).toHaveValue('')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Start build/ }))
    })
    expect(api.create).not.toHaveBeenCalled()
  })

  it('submits the settings changed in place', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: [ok('entry_point', 'main.py')] })
    renderWizard()
    await pointAt('/srv/projects/svc')
    await screen.findByText('Settings', {}, { timeout: 3000 })

    await act(async () => {
      fireEvent.click(screen.getByText('Full'))
      fireEvent.click(screen.getByText('A folder'))
      fireEvent.click(screen.getByRole('switch', { name: 'Docker image' }))
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Start build/ }))
    })

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    expect(api.create.mock.calls[0][0].config).toMatchObject({ pack_mode: 'full', onefile: false, docker_enabled: true })
  })

  it('opens the full wizard at the step that holds a setting', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: [ok('entry_point', 'main.py')] })
    renderWizard()
    await pointAt('/srv/projects/svc')

    // Wait outside act(): updates inside it are held until it returns, so the
    // button would never appear while act() is waiting for it.
    const change = await screen.findByRole('button', { name: 'Change Dependency group' }, { timeout: 3000 })
    await act(async () => {
      fireEvent.click(change)
    })

    const current = screen.getByRole('navigation', { name: 'Build steps' }).querySelector('[aria-current="step"]')
    expect(current?.textContent).toContain('Backend')
  })

  it('fills in the version the project states, and sends it', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: [ok('entry_point', 'main.py')], version: { value: '1.4.0', source: 'pyproject.toml' } })
    renderWizard()
    await pointAt('/srv/projects/svc')

    // The field shows at once; the version arrives with the project's fingerprints.
    await waitFor(() => expect(screen.getByLabelText('Version')).toHaveValue('1.4.0'), { timeout: 3000 })
    expect(screen.getByText('Read from pyproject.toml.')).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Start build/ }))
    })
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    expect(api.create.mock.calls[0][0].config.version).toBe('1.4.0')
  })

  it('asks before building a version that already passed', async () => {
    api.diagnoseRepo.mockResolvedValue({ checks: [ok('entry_point', 'main.py')], version: { value: '1.4.0', source: 'pyproject.toml' } })
    projects.sameVersion.mockResolvedValue([{ task_id: 'old', status: 'completed', user_name: 'mei', start_time: '2026-11-05T00:00:00' }])
    renderWizard()
    await pointAt('/srv/projects/svc')
    await waitFor(() => expect(screen.getByLabelText('Version')).toHaveValue('1.4.0'), { timeout: 3000 })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Start build/ }))
    })
    // antd's confirm renders the title for display and again for assistive tech.
    expect((await screen.findAllByText('svc 1.4.0 already passed')).length).toBeGreaterThan(0)
    expect(api.create).not.toHaveBeenCalled()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Build again' }))
    })
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
  })
})
