import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import type { BuildConfig, EffectiveSettings, TaskResponse } from '../../api/types'
import SettingOrigins from './SettingOrigins'
import { formatValue, settingRows } from './settingRows'
import { stageTrack } from '../../pages/dashboard/bench'
import { detectedFields } from '../../pages/createTask/quickPlan'
import { keepSavedValues, withFileValues } from '../../pages/projects/fromFile'

const submitted = {
  project_type: 'backend_only', source_type: 'git', git_url: 'https://example.com/a.git', git_ref: 'main',
  entry_point: 'mine.py', nuitka_jobs: 0, onefile: true, docker_enabled: false, version: '',
} as unknown as BuildConfig

const effective: EffectiveSettings = {
  config: { ...submitted, entry_point: 'src/app.py', docker_enabled: true } as BuildConfig,
  origins: { entry_point: 'file', docker_enabled: 'file', nuitka_jobs: 'override', onefile: 'detected' },
  file: {
    path: 'packwright.toml',
    fields: {
      entry_point: { key: 'python.entry', line: 4, text: 'entry = "src/app.py"', value: 'src/app.py',
        replaced: { origin: 'override', value: 'mine.py' } },
      docker_enabled: { key: 'docker.enabled', line: 7, text: 'enabled = true', value: true },
    },
  },
}

describe('Settings and where they came from', () => {
  it('shows each value with its origin, the file with its line and what it replaced', () => {
    render(<SettingOrigins effective={effective} config={submitted} />)
    const entry = screen.getByText('Entry point').closest('li')!
    expect(within(entry).getByText('src/app.py')).toBeInTheDocument()
    expect(within(entry).getByText('packwright.toml · line 4')).toBeInTheDocument()
    expect(within(entry).getByText(/instead of this build's/)).toBeInTheDocument()
    expect(within(entry).getByText('mine.py')).toBeInTheDocument()
    expect(within(screen.getByText('CPU jobs').closest('li')!).getByText('this build')).toBeInTheDocument()
    expect(within(screen.getByText('Single file').closest('li')!).getByText('detected')).toBeInTheDocument()
    expect(within(screen.getByText('Pack mode').closest('li')!).getByText('project')).toBeInTheDocument()
    // The file turned the image on: the Docker group follows what was built.
    expect(screen.getByText('Docker')).toBeInTheDocument()
    expect(screen.getByText(/2 came from packwright.toml/)).toBeInTheDocument()
  })

  it('says when the file has not been read yet, or there was none', () => {
    const { rerender } = render(<SettingOrigins effective={{ config: null, origins: {}, file: null }} config={submitted} />)
    expect(screen.getByText(/read from the source when the build starts/)).toBeInTheDocument()
    expect(screen.queryByText('Docker')).toBeNull()
    rerender(<SettingOrigins effective={{ config: submitted, origins: {}, file: null }} config={submitted} />)
    expect(screen.getByText(/had no packwright.toml/)).toBeInTheDocument()
  })

  it('lists only the settings that apply and reads values plainly', () => {
    const groups = settingRows(null, { ...submitted, project_type: 'frontend_only' } as BuildConfig).map((g) => g.group)
    expect(groups).toEqual(['Build', 'Frontend'])
    expect(formatValue(true)).toBe('Yes')
    expect(formatValue('')).toBe('—')
    expect(formatValue(['a', 'b'])).toBe('a, b')
    expect(formatValue('A=1\nB=2\nC=3')).toBe('A=1 (+2 more)')
  })

  it('puts the Config stage first and follows the effective type', () => {
    const task = { config: submitted, stage: 'config', effective } as unknown as TaskResponse
    const track = stageTrack(task)
    expect(track.map((s) => s.key)).toEqual(['config', 'preflight', 'compile', 'bundle', 'verify', 'docker'])
    expect(track[0].state).toBe('on')
  })
})

describe('packwright.toml in the console', () => {
  it('reports as detected only what detection filled, nobody changed and the file does not set', () => {
    const touched = (name: string) => name === 'entry_point'
    expect(detectedFields(['entry_point', 'project_type', 'frontend_dir', 'version'], touched, { frontend_dir: 'web' }))
      .toEqual(['project_type', 'version'])
  })

  it('shows the file values and saves the project\'s own', () => {
    const saved = { entry_point: 'main.py', nuitka_jobs: 2 } as unknown as BuildConfig
    const fields = { entry_point: { key: 'python.entry', line: 4, text: '', value: 'src/app.py' } }
    expect(withFileValues(saved, fields).entry_point).toBe('src/app.py')
    const edited = { entry_point: 'src/app.py', nuitka_jobs: 6 } as unknown as BuildConfig
    expect(keepSavedValues(edited, saved, fields)).toEqual({ entry_point: 'main.py', nuitka_jobs: 6 })
    expect(keepSavedValues(edited, saved, null)).toBe(edited)
  })
})
