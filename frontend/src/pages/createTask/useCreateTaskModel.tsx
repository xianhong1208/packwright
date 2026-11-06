import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Form, Button, Modal, message, notification, Tag, Tooltip } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { projectApi, taskApi } from '../../api/client'
import type {
  BuildConfig,
  ProjectType,
  SourceType,
  GitRefs,
  ProjectAnalysis,
  RepoDiagnosisCheck,
  DetectedVersion,
  DetectedFrontendConfig,
  TaskCreate,
} from '../../api/types'
import { useFormDraft } from '../../hooks/useFormDraft'
import { parseUtc } from '../../utils/time'
import { ALL_STEPS, activeSteps, clampStepIndex, type StepDef, type StepKey } from './steps'
import { assembleTaskCreate } from './buildConfig'
import { findPythonMismatch, pickDefaultRef } from './pythonVersion'
import type { DepGroupsRead } from './depGroups'
import { guessProject, nameFromSource, type ProjectGuess } from './quickPlan'
import type { Preset } from './initialValues'

export interface RebuildState {
  rebuild: boolean
  projectName: string
  config: BuildConfig
}

export interface ModelOptions {
  /** Start from this config instead of the navigation state (a project's settings). */
  preset?: Preset
  /** 'settings' edits a project's defaults: nothing is built, and nothing found in the
   *  project overwrites what is stored — it is offered next to the field instead. */
  purpose?: 'build' | 'settings'
  /** Called with the assembled request instead of starting a build. */
  onSubmit?: (request: TaskCreate) => void
}

/** All state, effects and handlers of the New build page; the steps read it through CreateTaskContext. */
export function useCreateTaskModel(options: ModelOptions = {}) {
  const purpose = options.purpose ?? 'build'
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [currentStep, setCurrentStep] = useState(0)
  // Simple vs Advanced form mode. Simple (default) keeps the advanced
  // collapse panels folded so newcomers only see the core fields; Advanced
  // expands everything at once. Users can still fold/unfold individual
  // panels manually — the mode toggle only sets their initial state.
  const [backendAdvKeys, setBackendAdvKeys] = useState<string[]>([])
  const [dockerAdvKeys, setDockerAdvKeys] = useState<string[]>([])

  // Rebuild state from History or TaskDetail navigation
  const preset = options.preset
  const rebuildState = useMemo(
    () => (preset ? { rebuild: true, ...preset } : (location.state as RebuildState | null)),
    [preset, location.state],
  )
  const isRebuild = rebuildState?.rebuild === true

  // Rebuild carries the original task's advanced values — open the relevant
  // advanced panels so they are visible rather than hidden in a collapsed section.
  useEffect(() => {
    if (!isRebuild || !rebuildState?.config) return
    const c = rebuildState.config
    if (c.nuitka_jobs || c.include_packages || c.extra_dirs || c.data_dirs) setBackendAdvKeys(['backend-advanced'])
    if (c.docker_env_vars || c.docker_custom_commands || c.docker_install_node) setDockerAdvKeys(['docker-advanced'])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRebuild])

  // ── Draft persistence ──────────────────────────────────────────────
  // Extracted to useFormDraft: the rule that the env content must never be
  // written to localStorage is a security property, and it is now pinned by
  // tests rather than by a comment next to a `delete`.
  const {
    savedAt: draftSavedAt,
    scheduleSave: scheduleDraftSave,
    clear: clearDraftStorage,
  } = useFormDraft(form, isRebuild)

  const clearDraft = useCallback(() => {
    clearDraftStorage()
    message.success('Draft cleared')
  }, [clearDraftStorage])

  // Directory selection state
  const [directories, setDirectories] = useState<string[]>([])
  const [selectedDirs, setSelectedDirs] = useState<string[]>([])
  const [selectedDataDirs, setSelectedDataDirs] = useState<string[]>([])
  const [loadingDirs, setLoadingDirs] = useState(false)
  const [dirError, setDirError] = useState<string | null>(null)
  const [currentPath, setCurrentPath] = useState<string>('')

  // Auto project analysis — classifies each scanned directory as
  // source/data/skip and suggests what to bundle. Populated best-effort
  // in local mode (taskApi.analyzeProject) and git mode (scanGitTree's
  // optional `.analysis`). Never blocks the plain directory listing.
  const [analysis, setAnalysis] = useState<ProjectAnalysis | null>(null)
  // Guards the one-time pre-check of recommended dirs so re-scans never
  // clobber the user's later manual edits.
  const analysisPrefilledRef = useRef(false)

  // CPU core count from server
  const [cpuCount, setCpuCount] = useState<number>(0)
  // Compile targets actually available on the server (detected from the
  // per-version Nuitka venvs) — falls back to a static list until loaded
  const [pythonVersions, setPythonVersions] = useState<string[]>(['3.14', '3.13', '3.12'])

  // Watch form values for conditional rendering. preserve: Quick build mounts a
  // field only once it has something to show (project_type appears after the
  // project is read), and without it useWatch reports an unmounted field as
  // undefined: for one render the page said "Could not tell from the files"
  // and hid the backend settings of a project it had just recognised.
  const projectType = Form.useWatch('project_type', { form, preserve: true }) as ProjectType
  const pythonVersion = Form.useWatch('python_version', { form, preserve: true }) as string
  const entryPoint = Form.useWatch('entry_point', { form, preserve: true }) as string
  const dockerEnabled = Form.useWatch('docker_enabled', { form, preserve: true }) as boolean
  const sourceType = Form.useWatch('source_type', { form, preserve: true }) as SourceType | undefined
  const gitUrl = Form.useWatch('git_url', { form, preserve: true }) as string | undefined
  const gitRef = Form.useWatch('git_ref', { form, preserve: true }) as string | undefined

  // A mismatch worth warning about needs BOTH a confident detection and an
  // explicit choice that contradicts it. "auto" is never a mismatch — it is
  // the fix — and a project with no compiled extensions has nothing to
  // contradict, so staying quiet there avoids crying wolf on pure-Python code.
  // Decision logic lives in ./createTask/pythonVersion with tests. The
  // asymmetry it encodes matters: a false alarm teaches people to dismiss the
  // warning, taking the real ones with it.
  const pythonMismatch = useMemo(
    () => findPythonMismatch(analysis?.detected_python, pythonVersion),
    [analysis, pythonVersion],
  )
  const gitRefType = Form.useWatch('git_ref_type', { form, preserve: true }) as 'branch' | 'tag' | undefined
  const frontendDirWatch = Form.useWatch('frontend_dir', { form, preserve: true }) as string | undefined

  // Git refs state
  const [gitRefs, setGitRefs] = useState<GitRefs>({ branches: [], tags: [] })
  const [loadingRefs, setLoadingRefs] = useState(false)
  const [refsFetchedFor, setRefsFetchedFor] = useState<string>('')

  // Git tree scan state (for populating extra_dirs/data_dirs grids in git mode)
  const [scanningTree, setScanningTree] = useState(false)
  const [treeScannedFor, setTreeScannedFor] = useState<string>('')

  // Git frontend preview state (for populating Frontend Settings card
  // auto-detect + env file picker in git mode).
  const [previewingFrontend, setPreviewingFrontend] = useState(false)
  const [frontendPreviewedFor, setFrontendPreviewedFor] = useState<string>('')
  // In git mode, env file content cannot be read from disk on demand —
  // we cache the contents returned by the preview endpoint here so the
  // "Load from project" button becomes an instant local lookup.
  const [gitEnvFilesContent, setGitEnvFilesContent] = useState<Record<string, string>>({})

  // Track the previously seen source_type so we can distinguish
  // "initial render" from "user-initiated mode switch". The ref is
  // set on first observation and never reset, so the dependency
  // useEffect below only runs its reset path on REAL transitions.
  const prevSourceTypeRef = useRef<SourceType | undefined>(undefined)

  // Tour state — shown once per browser via localStorage flag
  const TOUR_STORAGE_KEY = 'bc_tour_createtask_v1'
  const [tourOpen, setTourOpen] = useState(false)
  const sourceModeRef = useRef<HTMLDivElement>(null)
  const gitUrlRef = useRef<HTMLDivElement>(null)
  const refSelectRef = useRef<HTMLDivElement>(null)

  const [loadingEnv, setLoadingEnv] = useState(false)
  const [detectingConfig, setDetectingConfig] = useState(false)
  // What the frontend detection found, offered next to its fields.
  const [frontendDetected, setFrontendDetected] = useState<DetectedFrontendConfig | null>(null)
  const [envFiles, setEnvFiles] = useState<string[]>([])
  const [loadingEnvFiles, setLoadingEnvFiles] = useState(false)

  // PEP 735 dependency-group names parsed from the project's pyproject.toml.
  // Populated from /pyproject-groups (local mode) or the scan-tree response
  // (git mode). The picker is single-select and offers only these names.
  const [depGroups, setDepGroups] = useState<string[]>([])
  const [loadingDepGroups, setLoadingDepGroups] = useState(false)
  const [depGroupsRead, setDepGroupsRead] = useState<DepGroupsRead>('unread')

  // Quick build: a source is all a first build needs. The project's fingerprints
  // (diagnoseRepo locally, scan-tree for Git) fill in the type, entry point and
  // frontend directory; "All settings" opens the full wizard on the same form, so
  // nothing found here is lost. A rebuild already has its settings.
  const [mode, setMode] = useState<'quick' | 'full'>(() => (isRebuild ? 'full' : 'quick'))
  const [repoChecks, setRepoChecks] = useState<RepoDiagnosisCheck[] | null>(null)
  // Why the source could not be read (not allowed, not there…). Kept apart from
  // "nothing recognisable", which it used to be shown as.
  const [repoError, setRepoError] = useState<string | null>(null)
  // Where the version in the form came from, when the project said it.
  const [versionSource, setVersionSource] = useState<string | null>(null)
  const autoNameRef = useRef<string | null>(null)
  const applyGuess = useCallback((checks: RepoDiagnosisCheck[], source: string, version?: DetectedVersion | null): ProjectGuess => {
    setRepoChecks(checks)
    // A fresh build takes the version the code states. A stored config keeps its own:
    // a project's settings have no version at all, and a rebuild's is the one it was.
    if (version && !isRebuild && !form.isFieldTouched('version')) {
      form.setFieldValue('version', version.value)
      setVersionSource(version.source)
    }
    setRepoError(null)
    const guess = guessProject(checks)
    if (mode !== 'quick') return guess
    // Never over something the person set themselves.
    const fill = (name: string, value: unknown) => {
      if (value !== null && value !== undefined && !form.isFieldTouched(name)) form.setFieldValue(name, value)
    }
    fill('project_type', guess.projectType)
    fill('entry_point', guess.entryPoint)
    // A Python project without a usual entry point: leave the field empty for the
    // person to fill, rather than showing the form's main.py under "no main.py".
    if (guess.projectType !== 'frontend_only' && guess.entryPoint === null && !form.isFieldTouched('entry_point')) {
      form.setFieldValue('entry_point', '')
    }
    fill('frontend_dir', guess.frontendDir)
    const name = (form.getFieldValue('project_name') as string | undefined) ?? ''
    if (!name || name === autoNameRef.current) {
      autoNameRef.current = nameFromSource(source)
      form.setFieldValue('project_name', autoNameRef.current)
    }
    return guess
  }, [form, mode, isRebuild])

  const hasBackend = projectType === 'backend_only' || projectType === 'fullstack'
  const showFrontendSettings = projectType === 'frontend_only' || projectType === 'fullstack'

  // Server-configured build workspace root (GIT_WORKSPACE_DIR); empty until fetched.
  const [workspaceDir, setWorkspaceDir] = useState<string>('')

  // Fetch CPU core count on mount
  useEffect(() => {
    taskApi.getSystemInfo().then((info) => {
      setCpuCount(info.cpu_count)
      if (info.python_versions?.length) setPythonVersions(info.python_versions)
      if (info.git_workspace_dir) setWorkspaceDir(info.git_workspace_dir)
    }).catch((e) => console.warn('Could not load system info; using defaults', e))
  }, [])

  // Restore selected directories from rebuild config
  useEffect(() => {
    if (isRebuild && rebuildState?.config) {
      const extraDirs = rebuildState.config.extra_dirs
      if (extraDirs) {
        setSelectedDirs(extraDirs.split(',').map((d) => d.trim()).filter(Boolean))
      }
      const dataDirs = rebuildState.config.data_dirs
      if (dataDirs) {
        setSelectedDataDirs(dataDirs.split(',').map((d) => d.trim()).filter(Boolean))
      }
    }
  }, [isRebuild, rebuildState])

  // Auto-sync docker_base_image when python_version changes.
  // "auto" is NOT a Docker tag — `python:auto-slim` doesn't exist and would make
  // `docker build` fail on pull. A Nuitka standalone binary bundles its own
  // Python runtime, so the base image only supplies system libs; when the user
  // picks auto-detect we can't know the real X.Y here (the backend resolves it),
  // so fall back to a valid default tag instead of interpolating "auto".
  useEffect(() => {
    if (!pythonVersion) return
    const current = form.getFieldValue('docker_base_image') as string || ''
    if (!current || /^python:[\d.]+-slim$/.test(current)) {
      const tag = pythonVersion === 'auto' ? '3.13' : pythonVersion
      form.setFieldValue('docker_base_image', `python:${tag}-slim`)
    }
  }, [pythonVersion, form])

  const getFrontendFullPath = useCallback(() => {
    const path = form.getFieldValue('project_path')
    const frontendDir = form.getFieldValue('frontend_dir') || '.'
    if (!path) return null
    return frontendDir === '.' ? path : `${path}/${frontendDir}`
  }, [form])

  const fetchEnvFiles = useCallback(async () => {
    const fullPath = getFrontendFullPath()
    if (!fullPath) return
    setLoadingEnvFiles(true)
    try {
      const result = await taskApi.listEnvFiles(fullPath)
      setEnvFiles(result.files)
    } catch {
      setEnvFiles([])
    } finally {
      setLoadingEnvFiles(false)
    }
  }, [getFrontendFullPath])

  // Local mode: read PEP 735 dependency-groups from the project's pyproject.toml.
  // A clear-on-fetch keeps a stale selection from a previous path from leaking in.
  const fetchPyprojectGroups = useCallback(async (path: string) => {
    if (!path || !path.trim()) {
      setDepGroups([])
      setDepGroupsRead('unread')
      return
    }
    setLoadingDepGroups(true)
    try {
      const result = await taskApi.listPyprojectGroups(path.trim())
      setDepGroups(result.groups)
      setDepGroupsRead('read')
      // Drop a selected group that no longer exists in the new project.
      const current = form.getFieldValue('dependency_group') as string | undefined
      if (current && !result.groups.includes(current)) {
        form.setFieldValue('dependency_group', undefined)
      }
    } catch {
      setDepGroups([])
      setDepGroupsRead('failed')
    } finally {
      setLoadingDepGroups(false)
    }
  }, [form])

  const handleLoadEnv = async () => {
    const envFilename = form.getFieldValue('frontend_env_filename') || '.env'

    // In git mode, env file contents were already fetched in
    // handlePreviewGitFrontend — look them up from the cache instead of
    // hitting a (nonexistent) local filesystem path.
    if (form.getFieldValue('source_type') === 'git') {
      const cached = gitEnvFilesContent[envFilename]
      if (cached !== undefined) {
        form.setFieldValue('frontend_env_content', cached)
        message.success(`Loaded ${envFilename} from the Git repo`)
      } else {
        message.info(`${envFilename} not found in the Git repo`)
      }
      return
    }

    // Local mode: read from filesystem via the existing API.
    const fullPath = getFrontendFullPath()
    if (!fullPath) {
      message.warning('Enter the project path first')
      return
    }
    setLoadingEnv(true)
    try {
      const result = await taskApi.readEnvFile(fullPath, envFilename)
      form.setFieldValue('frontend_env_content', result.content)
      message.success(`Loaded ${envFilename} from the project`)
    } catch (err: unknown) {
      const error = err as { response?: { status?: number; data?: { detail?: string } } }
      if (error.response?.status === 404) {
        message.info(`${envFilename} not found in ${fullPath}`)
      } else {
        message.error(error.response?.data?.detail || 'Could not load the env file')
      }
    } finally {
      setLoadingEnv(false)
    }
  }

  const detectFrontendConfig = useCallback(async (silent = false) => {
    const path = form.getFieldValue('project_path')
    const frontendDir = form.getFieldValue('frontend_dir') || '.'
    if (!path) {
      if (!silent) message.warning('Enter the project path first')
      return
    }
    const fullPath = frontendDir === '.' ? path : `${path}/${frontendDir}`
    setDetectingConfig(true)
    try {
      const config = await taskApi.detectFrontendConfig(fullPath)
      if (!config.detected) {
        if (!silent) message.info('No frontend config detected in this directory')
        return
      }
      setFrontendDetected(config)
      // An explicit Detect fills the fields. Detection that runs by itself fills only
      // fields nobody set, and never a stored config (a rebuild, a project's settings):
      // it used to replace a rebuild's build command without anyone noticing. There it
      // is offered next to the field instead.
      if (silent && isRebuild) return
      const fill = (name: string, value: string | null | undefined) =>
        value && (!silent || !form.isFieldTouched(name)) ? { [name]: value } : {}
      const updates: Record<string, string> = {
        ...fill('frontend_build_tool', config.build_tool),
        ...fill('frontend_build_command', config.build_command),
        ...fill('frontend_output_dir', config.output_dir),
      }
      if (Object.keys(updates).length > 0) form.setFieldsValue(updates)
      if (!silent) {
        const parts: string[] = []
        if (config.has_vite_config) parts.push('Vite config')
        if (config.build_tool) parts.push(`tool: ${config.build_tool}`)
        if (config.build_command) parts.push(`command: ${config.build_command}`)
        if (config.output_dir) parts.push(`output: ${config.output_dir}`)
        message.success(`Detected ${parts.join(', ')}`)
      }
    } catch (err: unknown) {
      if (!silent) {
        const error = err as { response?: { status?: number; data?: { detail?: string } } }
        if (error.response?.status === 404) {
          message.info('Frontend directory not found')
        } else {
          message.error(error.response?.data?.detail || 'Could not detect the frontend config')
        }
      }
    } finally {
      setDetectingConfig(false)
    }
  }, [form, isRebuild])

  const createMutation = useMutation({
    mutationFn: taskApi.create,
    onSuccess: (task) => {
      message.success('Build started')
      // Draft has been consumed by a successful submit — clear it so the
      // next visit starts clean.
      clearDraftStorage()
      queryClient.invalidateQueries({ queryKey: ['activeTasks'] })
      window.history.replaceState({}, '')
      navigate(`/task/${task.id}`)
    },
    onError: (error: Error) => {
      notification.error({
        message: 'Could not start the build',
        description: error.message || 'Check your settings and try again',
        duration: 6,
      })
    },
  })

  const fetchDirectories = useCallback(async (path: string) => {
    if (!path || path.trim() === '') {
      setDirectories([])
      setDirError(null)
      setAnalysis(null)
      return
    }
    setLoadingDirs(true)
    setDirError(null)
    try {
      const result = await taskApi.listDirectories(path.trim())
      setDirectories(result.directories)
      setCurrentPath(path.trim())
      setSelectedDirs((prev) => prev.filter((d) => result.directories.includes(d)))
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      setDirError(error.response?.data?.detail || 'Could not load the directory list')
      setDirectories([])
    } finally {
      setLoadingDirs(false)
    }
    // Best-effort project analysis — runs after the dir list is settled and
    // never blocks it. On any error we simply clear the analysis so the UI
    // falls back to unlabelled checkboxes.
    try {
      const entry = (form.getFieldValue('entry_point') as string) || 'main.py'
      const result = await taskApi.analyzeProject(path.trim(), entry)
      setAnalysis(result)
    } catch {
      setAnalysis(null)
    }
  }, [form])

  const projectPath = Form.useWatch('project_path', { form, preserve: true })

  useEffect(() => {
    // Local-mode only: auto-scan the server path
    if (sourceType === 'git') return
    const timer = setTimeout(() => {
      if (projectPath && projectPath !== currentPath) {
        fetchDirectories(projectPath)
        const pt = form.getFieldValue('project_type') as ProjectType
        if (pt === 'backend_only' || pt === 'fullstack') {
          fetchPyprojectGroups(projectPath)
        }
        if (pt === 'frontend_only' || pt === 'fullstack') {
          detectFrontendConfig(true)
          fetchEnvFiles()
        }
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [projectPath, currentPath, fetchDirectories, detectFrontendConfig, fetchEnvFiles, fetchPyprojectGroups, form, sourceType])

  // Quick build, local path: fingerprint the folder, then run the detections that
  // depend on the type — the path effect above ran before the type was known.
  useEffect(() => {
    if ((mode !== 'quick' && purpose !== 'settings') || sourceType === 'git') return
    const path = ((projectPath as string | undefined) || '').trim()
    if (!path.startsWith('/')) {
      setRepoChecks(null)
      setRepoError(null)
      return
    }
    const timer = setTimeout(async () => {
      try {
        const { checks, version } = await taskApi.diagnoseRepo(path)
        const guess = applyGuess(checks, path, version)
        if (guess.projectType === 'backend_only' || guess.projectType === 'fullstack') void fetchPyprojectGroups(path)
        if (guess.projectType === 'frontend_only' || guess.projectType === 'fullstack') void detectFrontendConfig(true)
      } catch (err: unknown) {
        const e = err as { response?: { data?: { detail?: string } } }
        setRepoChecks(null)
        setRepoError(e.response?.data?.detail ?? 'The server could not read this folder.')
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [mode, purpose, sourceType, projectPath, applyGuess, fetchPyprojectGroups, detectFrontendConfig])

  // Git mode: debounce-fetch branches/tags when the git_url changes.
  const fetchGitRefs = useCallback(
    async (url: string) => {
      if (!url || !url.trim()) return
      setLoadingRefs(true)
      try {
        const refs = await taskApi.listGitRefs(url.trim())
        setGitRefs(refs)
        setRefsFetchedFor(url.trim())
        // Auto-select a sensible default ref
        // main → master → first, and never over an explicit choice: refs are
        // refetched when the URL is edited, and clobbering the selection would
        // silently build something other than what is shown on screen.
        const preferred = pickDefaultRef(refs, form.getFieldValue('git_ref') as string)
        if (preferred) {
          form.setFieldValue('git_ref', preferred)
          form.setFieldValue('git_ref_type', 'branch')
        }
      } catch (err: unknown) {
        const e = err as { response?: { status?: number; data?: { detail?: string } } }
        setGitRefs({ branches: [], tags: [] })
        notification.error({
          message: 'Could not load branches or tags',
          description:
            e.response?.data?.detail
            ?? 'Check that the URL is correct and that GITLAB_TOKEN is set on the server.',
          btn: (
            <Button size="small" type="primary" onClick={() => { void fetchGitRefs(url) }}>
              Retry
            </Button>
          ),
          duration: 0,
        })
      } finally {
        setLoadingRefs(false)
      }
    },
    [form],
  )

  useEffect(() => {
    if (sourceType !== 'git') return
    const url = (gitUrl || '').trim()
    if (!url || url === refsFetchedFor) return
    const timer = setTimeout(() => { fetchGitRefs(url) }, 500)
    return () => clearTimeout(timer)
  }, [gitUrl, sourceType, refsFetchedFor, fetchGitRefs])

  // Git mode only: scan the remote repo tree to populate the Extra /
  // Data directory pickers. Shares the `directories` state with local
  // mode so the existing checkbox grid just works.
  //
  // Called automatically from a debounced effect when (url, ref, refType)
  // stabilise — see below. Success feedback is handled by the inline status
  // indicator, not by a toast, to keep the UI quiet on every ref change.
  const handleScanGitTree = useCallback(async () => {
    const url = (form.getFieldValue('git_url') as string || '').trim()
    const ref = (form.getFieldValue('git_ref') as string || '').trim()
    const refType = (form.getFieldValue('git_ref_type') as 'branch' | 'tag') || 'branch'
    if (!url || !ref) return
    setScanningTree(true)
    setDirError(null)
    try {
      const result = await taskApi.scanGitTree(url, ref, refType)
      setDirectories(result.directories)
      setAnalysis(result.analysis ?? null)
      setCurrentPath(`git:${url}@${ref}`)
      setTreeScannedFor(`${url}|${refType}|${ref}`)
      // Trim any stale selections that are no longer present in the scan
      setSelectedDirs((prev) => prev.filter((d) => result.directories.includes(d)))
      setSelectedDataDirs((prev) => prev.filter((d) => result.directories.includes(d)))
      // pyproject dependency-groups parsed from the remote repo (git-mode parity)
      setDepGroups(result.dependency_groups)
      setDepGroupsRead('read')
      if (result.checks) applyGuess(result.checks, url, result.version)
      const currentGroup = form.getFieldValue('dependency_group') as string | undefined
      if (currentGroup && !result.dependency_groups.includes(currentGroup)) {
        form.setFieldValue('dependency_group', undefined)
      }
    } catch (err: unknown) {
      setDepGroupsRead('failed')
      const e = err as { response?: { data?: { detail?: string } } }
      setRepoError(e.response?.data?.detail ?? 'The server could not read this repository.')
      notification.error({
        message: 'Could not scan the repo structure',
        description:
          e.response?.data?.detail
          ?? 'Check that the Git URL and branch or tag are correct, and that the server can access this repo.',
        btn: (
          <Button size="small" type="primary" onClick={() => { void handleScanGitTree() }}>
            Retry
          </Button>
        ),
        duration: 0,
      })
    } finally {
      setScanningTree(false)
    }
  }, [form, applyGuess])

  // Auto-scan when the user has filled in URL + ref, debounced so that
  // rapid branch switching doesn't fire multiple requests. Only runs when
  // the project actually has a backend (extra_dirs/data_dirs are backend-only).
  useEffect(() => {
    if (sourceType !== 'git') return
    // Quick build reads the project type from this scan, so it cannot wait for one.
    if (!hasBackend && mode !== 'quick' && purpose !== 'settings') return
    const url = (gitUrl || '').trim()
    const ref = (gitRef || '').trim()
    const refType = gitRefType || 'branch'
    if (!url || !ref) return
    const key = `${url}|${refType}|${ref}`
    if (key === treeScannedFor) return
    const timer = setTimeout(() => { void handleScanGitTree() }, 800)
    return () => clearTimeout(timer)
  }, [sourceType, hasBackend, mode, purpose, gitUrl, gitRef, gitRefType, treeScannedFor, handleScanGitTree])

  // Git mode only: shallow-clone the repo and populate frontend config +
  // env file contents. Runs in parallel with scan_tree above, so fullstack
  // projects trigger both and backend-only projects trigger only scan_tree.
  const handlePreviewGitFrontend = useCallback(async () => {
    const url = (form.getFieldValue('git_url') as string || '').trim()
    const ref = (form.getFieldValue('git_ref') as string || '').trim()
    const refType = (form.getFieldValue('git_ref_type') as 'branch' | 'tag') || 'branch'
    const feDir = ((form.getFieldValue('frontend_dir') as string) || '.').trim()
    if (!url || !ref) return
    setPreviewingFrontend(true)
    try {
      const result = await taskApi.previewGitFrontend(url, ref, refType, feDir)
      // Auto-populate frontend fields from the detected config. Mirrors
      // the local-mode `detectFrontendConfig` auto-apply behaviour.
      const cfg = result.frontend_config
      if (cfg.detected) {
        const updates: Record<string, string> = {}
        if (cfg.build_tool) updates.frontend_build_tool = cfg.build_tool
        if (cfg.build_command) updates.frontend_build_command = cfg.build_command
        if (cfg.output_dir) updates.frontend_output_dir = cfg.output_dir
        if (Object.keys(updates).length > 0) form.setFieldsValue(updates)
      }
      // Env files list + content cache
      const fileNames = Object.keys(result.env_files).sort()
      setEnvFiles(fileNames)
      setGitEnvFilesContent(result.env_files)
      setFrontendPreviewedFor(`${url}|${refType}|${ref}|${feDir}`)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      notification.error({
        message: 'Could not detect the frontend config',
        description:
          e.response?.data?.detail
          ?? 'Check that the Git URL, branch or tag, and frontend directory are correct.',
        btn: (
          <Button size="small" type="primary" onClick={() => { void handlePreviewGitFrontend() }}>
            Retry
          </Button>
        ),
        duration: 0,
      })
    } finally {
      setPreviewingFrontend(false)
    }
  }, [form])

  useEffect(() => {
    if (sourceType !== 'git') return
    if (!showFrontendSettings) return
    const url = (gitUrl || '').trim()
    const ref = (gitRef || '').trim()
    if (!url || !ref) return
    const refType = gitRefType || 'branch'
    const feDir = (frontendDirWatch || '.').trim()
    const key = `${url}|${refType}|${ref}|${feDir}`
    if (key === frontendPreviewedFor) return
    const timer = setTimeout(() => { void handlePreviewGitFrontend() }, 800)
    return () => clearTimeout(timer)
  }, [
    sourceType,
    showFrontendSettings,
    gitUrl,
    gitRef,
    gitRefType,
    frontendDirWatch,
    frontendPreviewedFor,
    handlePreviewGitFrontend,
  ])

  // First-visit Tour — skipped if the user has already seen it.
  useEffect(() => {
    if (isRebuild) return // don't interrupt users returning to rebuild
    if (mode === 'quick') return // the tour points at the full wizard's fields
    if (typeof window === 'undefined') return
    if (!localStorage.getItem(TOUR_STORAGE_KEY)) {
      // Delay slightly so form has rendered and refs can be measured
      const timer = setTimeout(() => setTourOpen(true), 400)
      return () => clearTimeout(timer)
    }
  }, [isRebuild, mode])

  // Reset directory-related state when the user flips between source
  // modes mid-form, so stale selections / listings from the previous
  // mode don't leak into the new one. The ref guard skips the very
  // first observation (which is the form's initial value, not a user
  // action) and the rebuild effect above populates its own state.
  useEffect(() => {
    if (sourceType === undefined) return
    if (prevSourceTypeRef.current === undefined) {
      prevSourceTypeRef.current = sourceType
      return
    }
    if (prevSourceTypeRef.current === sourceType) return
    prevSourceTypeRef.current = sourceType

    // Real user-initiated switch — clear anything that was tied to the
    // previous mode's repo / path.
    setDirectories([])
    setSelectedDirs([])
    setSelectedDataDirs([])
    setCurrentPath('')
    setDirError(null)
    setAnalysis(null)
    analysisPrefilledRef.current = false
    setGitRefs({ branches: [], tags: [] })
    setRefsFetchedFor('')
    setTreeScannedFor('')
    setFrontendPreviewedFor('')
    setGitEnvFilesContent({})
    setEnvFiles([])
    setDepGroups([])
    setDepGroupsRead('unread')
    setRepoChecks(null)
    setRepoError(null)
    form.setFieldValue('dependency_group', undefined)
  }, [sourceType, form])

  // Pre-check the recommended directories on the FIRST analysis only, for a
  // fresh new task (never rebuild — that carries its own selections) and only
  // when the user hasn't manually chosen anything yet. The ref guard means a
  // later re-scan will never overwrite the user's manual edits.
  useEffect(() => {
    if (isRebuild) return
    if (!analysis) return
    if (analysisPrefilledRef.current) return
    if (directories.length === 0) return
    analysisPrefilledRef.current = true
    if (selectedDirs.length === 0) {
      const extra = analysis.suggested_extra_dirs.filter((d) => directories.includes(d))
      if (extra.length > 0) setSelectedDirs(extra)
    }
    if (selectedDataDirs.length === 0) {
      const data = analysis.suggested_data_dirs.filter((d) => directories.includes(d))
      if (data.length > 0) setSelectedDataDirs(data)
    }
  }, [analysis, isRebuild, directories, selectedDirs.length, selectedDataDirs.length])

  // Render the auto-analysis suggestion tags for a directory. Graceful: shows
  // nothing when there's no classification entry for the directory.
  const renderDirTags = useCallback((dir: string) => {
    const info = analysis?.directories.find((d) => d.name === dir)
    if (!info) return null
    const roleTag =
      info.role === 'source' ? (
        <Tag style={{ marginInlineEnd: 4 }}>Code</Tag>
      ) : info.role === 'data' ? (
        <Tag color="green" style={{ marginInlineEnd: 4 }}>Data</Tag>
      ) : (
        <Tag style={{ marginInlineEnd: 4 }}>Skip</Tag>
      )
    return (
      <span className="ml-1 inline-flex items-center align-middle">
        <Tooltip title={info.reason}>{roleTag}</Tooltip>
        {info.imported_by_entry && (
          <Tooltip title={info.reason}>
            <Tag color="gold" style={{ marginInlineEnd: 0 }}>Used by entry point</Tag>
          </Tooltip>
        )}
      </span>
    )
  }, [analysis])

  const closeTour = useCallback(() => {
    setTourOpen(false)
    try { localStorage.setItem(TOUR_STORAGE_KEY, '1') } catch { /* ignore */ }
  }, [])

  const handleManualSubmit = async () => {
    // Assembly lives in ./createTask/buildConfig with per-field tests: every
    // field falls back to a default, so a mistake here does not raise — it
    // silently builds with settings the user never chose.
    const request = assembleTaskCreate({
      values: form.getFieldsValue(true),
      selectedDirs,
      selectedDataDirs,
    })
    if (options.onSubmit) {
      options.onSubmit(request)
      return
    }
    const version = request.config.version ?? ''
    if (version) {
      // Building a version that already passed is allowed, but rarely meant.
      const earlier = await projectApi.sameVersion(request.project_name, version).catch(() => [])
      const passed = earlier.find((b) => b.status === 'completed')
      if (passed) {
        Modal.confirm({
          title: `${request.project_name} ${version} already passed`,
          content: `It was built on ${parseUtc(passed.start_time).toLocaleDateString()} by ${passed.user_name}. Build it again?`,
          okText: 'Build again',
          onOk: () => createMutation.mutate(request),
        })
        return
      }
    }
    createMutation.mutate(request)
  }

  const handleDirToggle = (dir: string, checked: boolean) => {
    if (checked) {
      setSelectedDirs((prev) => [...prev, dir])
    } else {
      setSelectedDirs((prev) => prev.filter((d) => d !== dir))
    }
  }

  const handleSelectAll = () => {
    if (selectedDirs.length === directories.length) {
      setSelectedDirs([])
    } else {
      setSelectedDirs([...directories])
    }
  }

  // ── Step navigation (key-based, dynamic per project type) ──
  // Step definitions and the project-type filter live in ./createTask/steps
  // with tests: a wrongly hidden step takes its required fields with it and
  // the build silently runs on defaults nobody chose.
  const activeStepList = useMemo(() => activeSteps(projectType), [projectType])

  const currentStepKey: StepKey = activeStepList[currentStep]?.key ?? 'basic'
  const currentStepDef: StepDef = activeStepList[currentStep] ?? ALL_STEPS[0]
  const isLastStep = currentStep === activeStepList.length - 1

  // Clamp currentStep when project type changes mid-flow (e.g. switch from
  // fullstack → backend_only after passing the frontend step).
  useEffect(() => {
    const clamped = clampStepIndex(currentStep, activeStepList)
    if (clamped !== currentStep) setCurrentStep(clamped)
  }, [activeStepList, currentStep])

  const validateAndNext = async () => {
    try {
      switch (currentStepKey) {
        case 'basic': {
          const common = ['project_name', 'version', 'project_type', 'source_type']
          const currentSource = (form.getFieldValue('source_type') || 'local') as SourceType
          const sourceSpecific =
            currentSource === 'git' ? ['git_url', 'git_ref'] : ['project_path']
          await form.validateFields([...common, ...sourceSpecific])
          break
        }
        case 'backend':
          await form.validateFields(['python_version', 'entry_point'])
          break
        // frontend / docker / review: no required fields here
      }
      if (currentStep < activeStepList.length - 1) {
        setCurrentStep((s) => s + 1)
      }
    } catch {
      // Validation failed — form will show error messages
    }
  }

  const goBack = () => setCurrentStep((s) => Math.max(0, s - 1))



  return {
    navigate,
    location,
    queryClient,
    rebuildState,
    isRebuild,
    clearDraft,
    analysisPrefilledRef,
    projectType,
    pythonVersion,
    entryPoint,
    dockerEnabled,
    sourceType,
    gitUrl,
    gitRef,
    pythonMismatch,
    gitRefType,
    frontendDirWatch,
    prevSourceTypeRef,
    TOUR_STORAGE_KEY,
    sourceModeRef,
    gitUrlRef,
    refSelectRef,
    hasBackend,
    showFrontendSettings,
    getFrontendFullPath,
    fetchEnvFiles,
    fetchPyprojectGroups,
    handleLoadEnv,
    detectFrontendConfig,
    createMutation,
    fetchDirectories,
    projectPath,
    fetchGitRefs,
    handleScanGitTree,
    handlePreviewGitFrontend,
    renderDirTags,
    closeTour,
    handleManualSubmit,
    handleDirToggle,
    handleSelectAll,
    activeStepList,
    currentStepKey,
    currentStepDef,
    isLastStep,
    validateAndNext,
    goBack,
    form,
    currentStep,
    setCurrentStep,
    backendAdvKeys,
    setBackendAdvKeys,
    dockerAdvKeys,
    setDockerAdvKeys,
    directories,
    setDirectories,
    selectedDirs,
    setSelectedDirs,
    selectedDataDirs,
    setSelectedDataDirs,
    loadingDirs,
    setLoadingDirs,
    dirError,
    setDirError,
    currentPath,
    setCurrentPath,
    analysis,
    setAnalysis,
    cpuCount,
    setCpuCount,
    pythonVersions,
    setPythonVersions,
    gitRefs,
    setGitRefs,
    loadingRefs,
    setLoadingRefs,
    refsFetchedFor,
    setRefsFetchedFor,
    scanningTree,
    setScanningTree,
    treeScannedFor,
    setTreeScannedFor,
    previewingFrontend,
    setPreviewingFrontend,
    frontendPreviewedFor,
    setFrontendPreviewedFor,
    gitEnvFilesContent,
    setGitEnvFilesContent,
    tourOpen,
    setTourOpen,
    loadingEnv,
    setLoadingEnv,
    detectingConfig,
    setDetectingConfig,
    envFiles,
    setEnvFiles,
    loadingEnvFiles,
    setLoadingEnvFiles,
    depGroups,
    setDepGroups,
    loadingDepGroups,
    setLoadingDepGroups,
    depGroupsRead,
    mode,
    setMode,
    repoChecks,
    repoError,
    frontendDetected,
    purpose,
    versionSource,
    workspaceDir,
    setWorkspaceDir,
    draftSavedAt,
    scheduleDraftSave,
    clearDraftStorage,
  }
}

export type CreateTaskModel = ReturnType<typeof useCreateTaskModel>
