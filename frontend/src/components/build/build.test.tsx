import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { BuildResult } from '../../api/types'
import BuildResultPanel from './BuildResultPanel'
import FailureReport from './FailureReport'

const base: BuildResult = {
  preflight: [],
  artifact: null,
  verify: null,
  report_file: null,
  duration_seconds: null,
  diagnosis: [],
}

describe('BuildResultPanel', () => {
  it('renders nothing for a result that only carries a duration', () => {
    // Docker and frontend builds record just their duration on failure; the history
    // page's copy of this panel showed an empty "Build result" card for them.
    const { container } = render(<BuildResultPanel result={{ ...base, duration_seconds: 12 }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the artifact and the verification verdict', () => {
    render(
      <BuildResultPanel
        result={{
          ...base,
          artifact: { path: '/x', size_bytes: 1, size_human: '37.8 MB', file_count: 1, sha256: 'a'.repeat(64) },
          verify: { status: 'pass', detail: 'Binary exited cleanly', exit_code: 0 },
        }}
      />,
    )
    expect(screen.getByText('37.8 MB')).toBeInTheDocument()
    expect(screen.getByText('Binary exited cleanly')).toBeInTheDocument()
    expect(screen.getByText('SHA-256')).toBeInTheDocument()
  })
})

describe('FailureReport', () => {
  it('names the failed stage in plain words, including frontend and docker', () => {
    const { rerender } = render(<FailureReport result={{ ...base, failed_stage: 'frontend' }} />)
    expect(screen.getByText(/Frontend \(installing dependencies/)).toBeInTheDocument()
    rerender(<FailureReport result={{ ...base, failed_stage: 'docker' }} />)
    expect(screen.getByText(/Docker \(building and exporting/)).toBeInTheDocument()
  })

  it('offers the one-click fix only when the page can apply it, with its overrides', () => {
    const result = {
      ...base,
      diagnosis: [
        { problem: 'ABI mismatch', suggestion: 'Use auto-detect', evidence: '', action: { label: 'Rebuild with auto-detect', overrides: { python_version: 'auto' } } },
      ],
    }
    const { rerender } = render(<FailureReport result={result} />)
    expect(screen.queryByRole('button', { name: 'Rebuild with auto-detect' })).toBeNull()

    const apply = vi.fn()
    rerender(<FailureReport result={result} onApplyFix={apply} />)
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild with auto-detect' }))
    expect(apply).toHaveBeenCalledWith({ python_version: 'auto' })
  })

  it('prefers the error lines stored with the record over the live log', () => {
    const { rerender } = render(
      <FailureReport result={{ ...base, error_lines: ['stored: boom'] }} logs={['Error: from live log']} />,
    )
    expect(screen.getByText('stored: boom')).toBeInTheDocument()
    expect(screen.queryByText('Error: from live log')).toBeNull()

    rerender(<FailureReport result={base} logs={['compiling', 'Error: from live log']} />)
    expect(screen.getByText('Error: from live log')).toBeInTheDocument()
  })
})
