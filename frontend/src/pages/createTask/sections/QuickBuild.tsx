import type { ReactNode } from 'react'
import { Button, Form, Input, Radio, Select, Segmented, Switch, type FormInstance } from 'antd'
import { CheckIcon, FolderIcon, LinkIcon, QuestionIcon, RocketLaunchIcon, SlidersIcon, SpinnerIcon, WarningCircleIcon } from '../../../components/ui/icons'
import type { ProjectType } from '../../../api/types'
import { useCreateTask } from '../context'
import { guessProject, outputSentence } from '../quickPlan'
import { activeSteps, type StepKey } from '../steps'
import BuildFlow from '../../../components/build/BuildFlow'

type RowState = 'looking' | 'found' | 'ask' | 'error'

/** A form value, whether or not its field is on screen (see the note at its use). */
function useField<T>(form: FormInstance, name: string): T | undefined {
  return Form.useWatch(name, { form, preserve: true }) as T | undefined
}

/**
 * One line of "what Packwright found". When it turns from looking to found it
 * plays a short reveal (the check pops, the row glows once), so the person sees
 * the form filling itself in rather than values silently appearing.
 */
function Finding({ state, label, children }: { state: RowState; label: string; children: ReactNode }) {
  return (
    <li className="finding" data-state={state}>
      <span className="finding-mark" aria-hidden="true">
        {state === 'looking' ? <SpinnerIcon /> : state === 'found' ? <CheckIcon /> : state === 'error' ? <WarningCircleIcon /> : <QuestionIcon />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="finding-label">{label}</div>
        <div className="finding-value">{children}</div>
      </div>
    </li>
  )
}

const TYPE_OPTIONS: { value: ProjectType; label: string }[] = [
  { value: 'backend_only', label: 'Backend' },
  { value: 'frontend_only', label: 'Frontend' },
  { value: 'fullstack', label: 'Full stack' },
]

const TYPE_SENTENCE: Record<ProjectType, string> = {
  backend_only: 'A Python backend, compiled into a standalone executable.',
  frontend_only: 'A web frontend, built into static files.',
  fullstack: 'A frontend and a Python backend, built together into one executable.',
}

/**
 * New build for someone who just wants it built: a source, and everything else
 * read from the project. "All settings" opens the full wizard on the same form.
 */
export default function QuickBuild() {
  const {
    form,
    sourceType,
    projectType,
    gitRefs,
    loadingRefs,
    scanningTree,
    repoChecks,
    repoError,
    versionSource,
    analysis,
    depGroups,
    loadingDepGroups,
    detectingConfig,
    hasBackend,
    showFrontendSettings,
    createMutation,
    handleManualSubmit,
    setMode,
    setCurrentStep,
    selectedDirs,
    selectedDataDirs,
  } = useCreateTask()

  // preserve: these fields are not rendered here (they live in the full wizard),
  // and without it useWatch reports an unmounted field as undefined — the page
  // said "the project root" while the build used frontend/.
  const entryPoint = useField<string>(form, 'entry_point')
  const frontendDir = useField<string>(form, 'frontend_dir')
  const buildTool = useField<string>(form, 'frontend_build_tool')
  const buildCommand = useField<string>(form, 'frontend_build_command')
  const frontendOut = useField<string>(form, 'frontend_output_dir')
  const projectPath = useField<string>(form, 'project_path')
  const gitUrl = useField<string>(form, 'git_url')
  const packMode = useField<string>(form, 'pack_mode')
  const onefile = useField<boolean>(form, 'onefile')
  const verify = useField<boolean>(form, 'verify_after_build')
  const dockerOn = useField<boolean>(form, 'docker_enabled')

  const hasSource = sourceType === 'git' ? Boolean(gitUrl?.trim()) : Boolean(projectPath?.trim().startsWith('/'))
  const reading = !repoError && (sourceType === 'git' ? loadingRefs || scanningTree : repoChecks === null)
  const guess = repoChecks ? guessProject(repoChecks) : null
  const typeKnown = Boolean(guess?.projectType)
  const python = analysis?.detected_python?.version

  // Open the full wizard at the step that holds a setting.
  const goTo = (step: StepKey) => {
    const at = activeSteps(projectType).findIndex((st) => st.key === step)
    setCurrentStep(Math.max(0, at))
    setMode('full')
  }

  const start = async () => {
    try {
      const sourceFields = sourceType === 'git' ? ['git_url', 'git_ref'] : ['project_path']
      await form.validateFields(['project_name', 'version', ...sourceFields, ...(hasBackend ? ['entry_point'] : [])])
      handleManualSubmit()
    } catch {
      // The fields show what is missing.
    }
  }

  return (
    <div className="max-w-3xl">
      <section className="glass-card p-6 mb-4" aria-labelledby="quick-source">
        <h2 id="quick-source" className="text-[17px] font-semibold m-0 mb-4" style={{ color: 'var(--ink)' }}>Where is the code?</h2>
        <Form.Item name="source_type" className="!mb-4">
          <Radio.Group buttonStyle="solid">
            <Radio.Button value="local"><FolderIcon /> A folder on this server</Radio.Button>
            <Radio.Button value="git"><LinkIcon /> A Git repository</Radio.Button>
          </Radio.Group>
        </Form.Item>
        {sourceType === 'git' ? (
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px]">
            <Form.Item
              name="git_url"
              className="!mb-0"
              rules={[
                { required: true, message: 'Paste the repository URL' },
                { pattern: /^https?:\/\//, message: 'Use the https:// address of the repository' },
              ]}
            >
              <Input size="large" className="input-field" placeholder="https://github.com/you/project.git" aria-label="Repository URL" />
            </Form.Item>
            <Form.Item name="git_ref" className="!mb-0" rules={[{ required: true, message: 'Pick a branch' }]}>
              <Select
                size="large"
                showSearch
                loading={loadingRefs}
                placeholder="Branch"
                aria-label="Branch or tag"
                onChange={(_, option) => {
                  const kind = (option as { kind?: 'branch' | 'tag' } | undefined)?.kind
                  if (kind) form.setFieldValue('git_ref_type', kind)
                }}
                options={[
                  ...gitRefs.branches.map((b) => ({ value: b, label: b, kind: 'branch' as const })),
                  ...gitRefs.tags.map((t) => ({ value: t, label: `${t} (tag)`, kind: 'tag' as const })),
                ]}
              />
            </Form.Item>
          </div>
        ) : (
          <Form.Item
            name="project_path"
            className="!mb-0"
            validateTrigger={['onBlur']}
            rules={[
              { required: true, message: 'Enter the folder that holds the project' },
              { pattern: /^\//, message: 'Enter the full path, starting with /' },
            ]}
          >
            <Input size="large" className="input-field" placeholder="/srv/projects/my-app" aria-label="Project folder" />
          </Form.Item>
        )}
      </section>

      {!hasSource && (
        <section className="glass-card p-6 mb-4" aria-labelledby="quick-next">
          <h2 id="quick-next" className="text-[17px] font-semibold m-0 mb-1" style={{ color: 'var(--ink)' }}>What happens next</h2>
          <p className="m-0 mb-6 text-sm" style={{ color: 'var(--ink-muted)' }}>Packwright reads the project, then takes it through these steps.</p>
          <BuildFlow />
        </section>
      )}

      {hasSource && (
        <section className="glass-card p-6 mb-4" aria-labelledby="quick-found" aria-live="polite">
          <h2 id="quick-found" className="text-[17px] font-semibold m-0 mb-1" style={{ color: 'var(--ink)' }}>What Packwright found</h2>
          <p className="m-0 mb-4 text-sm" style={{ color: 'var(--ink-muted)' }}>
            Read from the project. Anything it gets wrong can be changed here or under All settings.
          </p>
          {repoError ? (
            <ul className="findings">
              <Finding state="error" label={sourceType === 'git' ? 'Could not read the repository' : 'Could not read the folder'}>
                {repoError}
              </Finding>
            </ul>
          ) : (
          <ul className="findings">
            <Finding state={reading ? 'looking' : typeKnown ? 'found' : 'ask'} label="What it is">
              {reading ? (
                'Looking at the project…'
              ) : (
                <>
                  <span>{typeKnown && projectType ? TYPE_SENTENCE[projectType] : 'Could not tell from the files. Which is it?'}</span>
                  <Form.Item name="project_type" className="!mb-0 mt-2">
                    <Segmented options={TYPE_OPTIONS} aria-label="Project type" />
                  </Form.Item>
                </>
              )}
            </Finding>

            {!reading && hasBackend && (
              <Finding state={guess?.entryPoint || entryPoint ? 'found' : 'ask'} label="Starts from">
                {guess?.entryPoint ? (
                  <code>{entryPoint || guess.entryPoint}</code>
                ) : (
                  <>
                    <span>No main.py, app/main.py, src/main.py or run.py. Which file starts the program?</span>
                    <Form.Item name="entry_point" className="!mb-0 mt-2" rules={[{ required: true, message: 'Enter the file that starts it' }]}>
                      <Input className="input-field" placeholder="server.py" aria-label="Entry point" />
                    </Form.Item>
                  </>
                )}
              </Finding>
            )}

            {!reading && hasBackend && (
              <Finding state="found" label="Python">
                {python ? <>Python {python}, as the project's .venv was built with.</> : <>Chosen when the build starts, from the project's .venv.</>}
              </Finding>
            )}

            {!reading && hasBackend && (
              <Finding state={loadingDepGroups ? 'looking' : 'found'} label="Dependencies">
                {loadingDepGroups
                  ? 'Reading pyproject.toml…'
                  : depGroups.length > 0
                    ? `The default ones. pyproject.toml also defines ${depGroups.length} ${depGroups.length === 1 ? 'group' : 'groups'} (${depGroups.join(', ')}); pick one under All settings if you need it.`
                    : 'The default ones from pyproject.toml.'}
              </Finding>
            )}

            {!reading && showFrontendSettings && (
              <Finding state={detectingConfig ? 'looking' : 'found'} label="Frontend">
                {detectingConfig ? (
                  'Reading package.json…'
                ) : (
                  <>
                    In {frontendDir === '.' || !frontendDir ? 'the project root' : <code>{frontendDir}/</code>}:{' '}
                    <code>{buildTool || 'npm'} run {buildCommand || 'build'}</code>, output in <code>{frontendOut || 'dist'}</code>.
                  </>
                )}
              </Finding>
            )}

            {!reading && typeKnown && (
              <Finding state="found" label="You get">
                {outputSentence({ backend: hasBackend, packMode, onefile, verify, docker: dockerOn })}
              </Finding>
            )}
          </ul>
          )}
        </section>
      )}

      {hasSource && !repoError && !reading && <QuickSettings goTo={goTo} selected={selectedDirs.length} data={selectedDataDirs.length} />}

      {hasSource && (
        <section className="glass-card p-6 mb-4" aria-labelledby="quick-name">
          <h2 id="quick-name" className="text-[17px] font-semibold m-0 mb-3" style={{ color: 'var(--ink)' }}>Name and version</h2>
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px]">
            <Form.Item name="project_name" className="!mb-0" rules={[{ required: true, message: 'Give the build a name' }]}
              extra="The project it is filed under. Builds with the same name and source are one project.">
              <Input className="input-field" placeholder="my-app" aria-label="Build name" />
            </Form.Item>
            <Form.Item name="version" className="!mb-0" rules={[{ pattern: /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$/, message: 'Letters, digits, . - _ + only, e.g. 1.2.0 or v2.0.0-rc.1' }]}
              extra={versionSource ? `Read from ${versionSource}.` : 'Optional, e.g. 1.2.0.'}>
              <Input className="input-field" placeholder="1.2.0" aria-label="Version" />
            </Form.Item>
          </div>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3 mt-6">
        <Button
          type="primary"
          size="large"
          icon={<RocketLaunchIcon />}
          loading={createMutation.isPending}
          // Unrecognised projects need the type picked; the form's default is a guess nobody made.
          disabled={!hasSource || reading || Boolean(repoError) || (!typeKnown && !form.isFieldTouched('project_type'))}
          onClick={start}
          style={{ height: 44, minWidth: 164 }}
        >
          Start build
        </Button>
        <Button size="large" icon={<SlidersIcon />} onClick={() => setMode('full')} style={{ height: 44 }}>
          All settings
        </Button>
      </div>
    </div>
  )
}

/** A setting changed here, with what each choice means. */
function Choice({ label, help, children }: { label: string; help: ReactNode; children: ReactNode }) {
  return (
    <div className="quick-choice">
      <div className="min-w-0">
        <div className="font-semibold" style={{ color: 'var(--ink)' }}>{label}</div>
        <div className="text-sm" style={{ color: 'var(--ink-muted)' }}>{help}</div>
      </div>
      <div className="flex-none">{children}</div>
    </div>
  )
}

/**
 * The settings people change most, changed in place, and every other one listed
 * with the value it will use and a way to it in the full wizard.
 */
function QuickSettings({ goTo, selected, data }: { goTo: (step: StepKey) => void; selected: number; data: number }) {
  const { form, hasBackend, showFrontendSettings, dockerEnabled } = useCreateTask()
  const packMode = useField<string>(form, 'pack_mode')
  const onefile = useField<boolean>(form, 'onefile')
  const python = useField<string>(form, 'python_version')
  const jobs = useField<number>(form, 'nuitka_jobs')
  const group = useField<string>(form, 'dependency_group')
  const envFile = useField<string>(form, 'frontend_env_content')
  const baseImage = useField<string>(form, 'docker_base_image')
  const port = useField<number>(form, 'docker_expose_port')

  const others: { name: string; value: string; step: StepKey }[] = [
    ...(hasBackend
      ? [
          { name: 'Python version', value: !python || python === 'auto' ? 'Automatic' : python, step: 'backend' as StepKey },
          { name: 'CPU jobs', value: jobs ? String(jobs) : 'Automatic', step: 'backend' as StepKey },
          { name: 'Dependency group', value: group || 'None (default dependencies)', step: 'backend' as StepKey },
          { name: 'Source code to bundle', value: selected ? `${selected} selected` : 'None', step: 'backend' as StepKey },
          { name: 'Data directories', value: data ? `${data} selected` : 'None', step: 'backend' as StepKey },
        ]
      : []),
    ...(showFrontendSettings
      ? [{ name: 'Frontend environment (.env)', value: envFile?.trim() ? 'Loaded' : 'None', step: 'frontend' as StepKey }]
      : []),
    ...(dockerEnabled
      ? [{ name: 'Docker image', value: `${baseImage || 'python:3.13-slim'}, port ${port || 8000}`, step: 'docker' as StepKey }]
      : []),
  ]

  return (
    <section className="glass-card p-6 mb-4" aria-labelledby="quick-settings">
      <h2 id="quick-settings" className="text-[17px] font-semibold m-0 mb-1" style={{ color: 'var(--ink)' }}>Settings</h2>
      <p className="m-0 mb-4 text-sm" style={{ color: 'var(--ink-muted)' }}>The usual choices are already made. Change them here, or open any other setting below.</p>

      <div className="quick-choices">
        {hasBackend && (
          <Choice
            label="Packing"
            help={packMode === 'full'
              ? 'Everything compiled into the program. Slow: a large project can take hours.'
              : 'Libraries copied beside the program in libs/. Builds in minutes.'}
          >
            <Form.Item name="pack_mode" className="!mb-0">
              <Segmented options={[{ value: 'external', label: 'External' }, { value: 'full', label: 'Full' }]} aria-label="Packing" />
            </Form.Item>
          </Choice>
        )}
        {hasBackend && (
          <Choice
            label="Output"
            help={onefile === false ? 'A folder holding the program and what it needs.' : 'A single executable file.'}
          >
            <Form.Item name="onefile" className="!mb-0">
              <Segmented options={[{ value: true, label: 'One file' }, { value: false, label: 'A folder' }]} aria-label="Output" />
            </Form.Item>
          </Choice>
        )}
        {hasBackend && (
          <Choice label="Check it starts" help="Run the program once after building; a missing module fails the build here.">
            <Form.Item name="verify_after_build" valuePropName="checked" className="!mb-0">
              <Switch aria-label="Check it starts" />
            </Form.Item>
          </Choice>
        )}
        <Choice label="Docker image" help="Also wrap the result in a Docker image you can download.">
          <Form.Item name="docker_enabled" valuePropName="checked" className="!mb-0">
            <Switch aria-label="Docker image" />
          </Form.Item>
        </Choice>
      </div>

      {others.length > 0 && (
        <dl className="quick-others">
          {others.map((o) => (
            <div key={o.name} className="quick-other">
              <dt>{o.name}</dt>
              <dd>{o.value}</dd>
              <button type="button" className="quick-change" onClick={() => goTo(o.step)} aria-label={`Change ${o.name}`}>Change</button>
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}
