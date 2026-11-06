import { Form, Button, Tour, type TourProps } from 'antd'
import { ArrowLeftIcon, ArrowRightIcon, CheckIcon, LightningIcon, RocketLaunchIcon } from '../components/ui/icons'
import { useCreateTaskModel } from './createTask/useCreateTaskModel'
import { CreateTaskContext } from './createTask/context'
import BasicsStep from './createTask/sections/BasicsStep'
import BackendStep from './createTask/sections/BackendStep'
import FrontendStep from './createTask/sections/FrontendStep'
import DockerStep from './createTask/sections/DockerStep'
import ReviewStep from './createTask/sections/ReviewStep'
import QuickBuild from './createTask/sections/QuickBuild'
import { initialValues } from './createTask/initialValues'

export default function CreateTask() {
  const model = useCreateTaskModel()
  const {
    rebuildState,
    isRebuild,
    clearDraft,
    sourceModeRef,
    gitUrlRef,
    refSelectRef,
    createMutation,
    closeTour,
    handleManualSubmit,
    activeStepList,
    currentStepKey,
    currentStepDef,
    isLastStep,
    validateAndNext,
    goBack,
    form,
    currentStep,
    setCurrentStep,
    tourOpen,
    draftSavedAt,
    scheduleDraftSave,
    mode,
    setMode,
  } = model

  return (
    <CreateTaskContext.Provider value={model}>
      <div className="max-w-5xl">
        {/* Page header — title + subtitle, form-mode toggle on the right, hairline seam under it */}
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h1 className="page-title">
              {isRebuild ? 'Rebuild' : 'New build'}
            </h1>
            <p className="page-lead">
              {isRebuild
                ? `Rebuilding "${rebuildState?.projectName}"`
                : mode === 'quick'
                  ? 'Point it at your code. Packwright works out the rest.'
                  : 'Every setting, one step at a time.'}
            </p>
            {!isRebuild && draftSavedAt && (
              <div className="mt-2 flex items-center gap-3 text-xs" style={{ color: 'var(--ink-faint)' }}>
                <span>Draft saved automatically. It restores when you come back.</span>
                <button
                  type="button"
                  onClick={clearDraft}
                  className="text-cyber-400 hover:text-cyber-300"
                >
                  Clear draft
                </button>
              </div>
            )}
          </div>
          {!isRebuild && mode === 'full' && (
            <Button icon={<LightningIcon />} onClick={() => setMode('quick')}>Quick build</Button>
          )}
        </div>

        <Form
            form={form}
            layout="vertical"
            onValuesChange={scheduleDraftSave}
            onFinish={() => { /* disabled — use manual submit only */ }}
            initialValues={initialValues(isRebuild && rebuildState ? rebuildState : null)}
        >
        {mode === 'quick' ? (
          <QuickBuild />
        ) : (
        <>
        {/* Mobile step progress — slim indicator that replaces the rail below lg */}
        <div className="lg:hidden mb-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold" style={{ fontFamily: 'var(--font-display)', color: 'var(--ink)' }}>
              {currentStepDef.title}
            </span>
            <span className="text-xs font-mono" style={{ color: 'var(--ink-faint)' }}>
              {currentStep + 1} / {activeStepList.length}
            </span>
          </div>
          <div
            className="flex gap-1.5"
            role="progressbar"
            aria-valuenow={currentStep + 1}
            aria-valuemin={1}
            aria-valuemax={activeStepList.length}
          >
            {activeStepList.map((s, i) => (
              <div
                key={s.key}
                className="h-1 flex-1 rounded-full transition-colors duration-150"
                style={{ background: i <= currentStep ? 'var(--color-cyber-500)' : 'var(--color-void-700)' }}
              />
            ))}
          </div>
        </div>

        {/* Two-column workspace: sticky step rail + focused content pane */}
        <div className="lg:grid lg:grid-cols-[232px_minmax(0,1fr)] lg:gap-8 lg:items-start">
          {/* ── Left: vertical step rail (sticky, desktop only) ── */}
          <aside className="hidden lg:block">
            <nav aria-label="Build steps" className="sticky top-6">
              <ol className="space-y-1">
                {activeStepList.map((s, i) => {
                  const done = i < currentStep
                  const active = i === currentStep
                  const clickable = i <= currentStep
                  return (
                    <li key={s.key}>
                      <button
                        type="button"
                        disabled={!clickable}
                        aria-current={active ? 'step' : undefined}
                        onClick={() => { if (clickable) setCurrentStep(i) }}
                        className={`w-full flex items-start gap-3 rounded-lg py-2.5 pl-3 pr-2 text-left border-l-2 transition-colors duration-150 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyber-500 ${
                          active
                            ? 'bg-cyber-500/10 border-cyber-500'
                            : clickable
                            ? 'border-transparent cursor-pointer hover:bg-[color-mix(in srgb, var(--ink) 4%, transparent)]'
                            : 'border-transparent cursor-default'
                        }`}
                      >
                        <span
                          className="mt-0.5 flex-shrink-0 flex items-center justify-center rounded-full text-xs font-mono font-medium"
                          style={{
                            width: 24,
                            height: 24,
                            background: active
                              ? 'var(--color-cyber-500)'
                              : done
                              ? 'color-mix(in srgb, var(--color-matrix-500) 14%, transparent)'
                              : 'transparent',
                            border: active
                              ? '1px solid var(--color-cyber-400)'
                              : done
                              ? '1px solid color-mix(in srgb, var(--color-matrix-500) 40%, transparent)'
                              : '1px solid var(--color-void-600)',
                            color: active ? 'var(--color-void-950)' : done ? 'var(--color-matrix-400)' : 'var(--ink-faint)',
                          }}
                        >
                          {done ? <CheckIcon /> : i + 1}
                        </span>
                        <span className="min-w-0">
                          <span
                            className="block text-sm font-semibold leading-tight"
                            style={{
                              fontFamily: 'var(--font-display)',
                              color: active ? 'var(--ink)' : done ? 'var(--ink-muted)' : 'var(--ink-faint)',
                            }}
                          >
                            {s.title}
                          </span>
                          <span className="block text-xs mt-0.5 leading-snug" style={{ color: 'var(--ink-faint)' }}>
                            {s.short}
                          </span>
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ol>
            </nav>
          </aside>

          {/* ── Right: content pane ── */}
          <div className="min-w-0">
            {/* Focal step header — one dominant title + a muted description */}
            <div className="mb-6">
              <h2 className="text-2xl font-semibold" style={{ fontFamily: 'var(--font-display)', color: 'var(--ink)' }}>
                {currentStepDef.title}
              </h2>
              <p className="mt-1.5 text-sm" style={{ color: 'var(--ink-muted)', lineHeight: 1.65, maxWidth: '62ch' }}>
                {currentStepDef.description}
              </p>
            </div>


            {/* ════════════════════════════════════════════
                Step: Basic Info — project name, type, source
                ════════════════════════════════════════════ */}
            <div style={{ display: currentStepKey === 'basic' ? 'block' : 'none' }}>
              <BasicsStep />
            </div>
            {/* ════ end Step: basic ════ */}

            {/* ════════════════════════════════════════════
                Step: Backend — Nuitka settings (only when hasBackend)
                ════════════════════════════════════════════ */}
            <div style={{ display: currentStepKey === 'backend' ? 'block' : 'none' }}>
              <BackendStep />
            </div>
            {/* ════ end Step: backend ════ */}

            {/* ════════════════════════════════════════════
                Step: Frontend (only when showFrontendSettings)
                ════════════════════════════════════════════ */}
            <div style={{ display: currentStepKey === 'frontend' ? 'block' : 'none' }}>
              <FrontendStep />
            </div>
            {/* ════ end Step: frontend ════ */}

            {/* ════════════════════════════════════════════
                Step: Docker — output decision + image settings
                ════════════════════════════════════════════ */}
            <div style={{ display: currentStepKey === 'docker' ? 'block' : 'none' }}>
              <DockerStep />
            </div>

            {/* ════════════════════════════════════════════
                Step: Review — confirmation summary
                ════════════════════════════════════════════ */}
            <div style={{ display: currentStepKey === 'review' ? 'block' : 'none' }}>
              <ReviewStep />
            </div>

            {/* ════════════════════════════════════════════
                Sticky footer action bar — Back (ghost) + exactly one primary
                ════════════════════════════════════════════ */}
            <div
              className="sticky bottom-0 z-10 mt-8 py-4 flex items-center justify-between gap-4 border-t border-[var(--seam)]"
              style={{ background: 'var(--color-void-950)' }}
            >
              <div className="min-w-0 truncate text-xs" style={{ color: 'var(--ink-faint)' }}>
                {!isLastStep && activeStepList[currentStep + 1] ? (
                  <>
                    Next: <span className="text-cyber-400">{activeStepList[currentStep + 1].title}</span>
                  </>
                ) : null}
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                {currentStep > 0 && (
                  <Button
                    htmlType="button"
                    size="large"
                    icon={<ArrowLeftIcon />}
                    onClick={goBack}
                    style={{ height: 44 }}
                  >
                    Back
                  </Button>
                )}
                {!isLastStep ? (
                  <Button
                    type="primary"
                    htmlType="button"
                    size="large"
                    onClick={validateAndNext}
                    className="btn-cyber"
                    style={{ height: 44, minWidth: 148 }}
                  >
                    Next <ArrowRightIcon />
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    htmlType="button"
                    loading={createMutation.isPending}
                    disabled={createMutation.isPending}
                    size="large"
                    icon={<RocketLaunchIcon />}
                    className="btn-cyber"
                    style={{ height: 44, minWidth: 164 }}
                    onClick={handleManualSubmit}
                  >
                    {isRebuild ? 'Start rebuild' : 'Start build'}
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>

        </>
        )}
        </Form>

        {/* First-visit tour */}
        <Tour
          open={tourOpen}
          onClose={closeTour}
          steps={
            [
              {
                title: 'Choose a source',
                description:
                  'Use a folder that already exists on the server, or paste the HTTPS URL of a Git repository (GitHub, GitLab or your own server) and let the server clone it.',
                target: () => sourceModeRef.current,
                // Above, so the bubble does not cover the path field right below.
                placement: 'top',
              },
              {
                title: 'Enter the Git URL',
                description:
                  'Paste the repository\'s HTTPS URL and the server lists its branches and tags. For a private repository, add an access token under Git credentials; never put one in the URL.',
                target: () => gitUrlRef.current,
              },
              {
                title: 'Pick a branch or tag',
                description:
                  'A branch keeps moving over time; a tag points at a fixed version. You can also type a name that isn\'t in the list.',
                target: () => refSelectRef.current,
              },
            ] as TourProps['steps']
          }
        />
      </div>
    </CreateTaskContext.Provider>
  )
}
