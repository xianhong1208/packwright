import { Tooltip, message } from 'antd'
import { CheckCircleIcon, FileZipIcon, WarningIcon, XCircleIcon } from '../ui/icons'
import type { BuildResult } from '../../api/types'
import { VERIFY_META } from '../../utils/statusMeta'
import { hasBuildResult } from './stages'

/**
 * Verification, artifact and preflight checks of one build. Shared by the live
 * task page and the history page, which used to carry a copy each and drifted.
 */
export default function BuildResultPanel({ result }: { result: BuildResult | null | undefined }) {
  if (!hasBuildResult(result)) return null
  const verify = result.verify ? VERIFY_META[result.verify.status] : null

  return (
    <div className="glass-card p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-medium" style={{ color: 'var(--ink)' }}>
          Build result
        </h3>
        {verify && (
          <span
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
            style={{ backgroundColor: verify.bg, color: verify.color }}
          >
            {verify.icon}
            {verify.label}
          </span>
        )}
      </div>

      {verify && result.verify?.detail && (
        <div
          className="text-sm mb-4 px-3 py-2 rounded-lg"
          style={{ background: verify.bg, color: verify.color, lineHeight: 1.6 }}
        >
          {result.verify.detail}
        </div>
      )}

      {result.artifact && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div className="rounded-lg p-3 bg-void-950">
            <div className="text-xs mb-1" style={{ color: 'var(--ink-faint)' }}>
              <FileZipIcon className="mr-1" />
              Artifact size
            </div>
            <div className="text-lg font-semibold text-[var(--ink)]">{result.artifact.size_human}</div>
          </div>
          <div className="rounded-lg p-3 bg-void-950">
            <div className="text-xs mb-1" style={{ color: 'var(--ink-faint)' }}>
              File count
            </div>
            <div className="text-lg font-semibold" style={{ color: 'var(--ink)' }}>
              {result.artifact.file_count}
            </div>
          </div>
          {result.artifact.sha256 && (
            <div className="rounded-lg p-3 col-span-2 bg-void-950">
              <div className="text-xs mb-1" style={{ color: 'var(--ink-faint)' }}>
                SHA-256
              </div>
              <Tooltip title="Click to copy the full hash">
                <code
                  className="text-xs font-mono break-all cursor-pointer hover:text-cyber-300"
                  style={{ color: 'var(--ink-muted)' }}
                  onClick={() => {
                    navigator.clipboard?.writeText(result.artifact?.sha256 || '')
                    message.success('SHA-256 copied to clipboard.')
                  }}
                >
                  {result.artifact.sha256.slice(0, 32)}…
                </code>
              </Tooltip>
            </div>
          )}
        </div>
      )}

      {result.preflight && result.preflight.length > 0 && (
        <div>
          <div className="text-xs mb-2" style={{ color: 'var(--ink-faint)' }}>
            Preflight checks
          </div>
          <div className="space-y-1.5">
            {result.preflight.map((c) => (
              <div key={c.label} className="flex items-start gap-2 text-sm">
                <span
                  className={c.passed ? 'text-matrix-400' : c.critical ? 'text-alert-400' : 'text-signal-400'}
                  style={{ marginTop: 2 }}
                >
                  {c.passed ? <CheckCircleIcon /> : c.critical ? <XCircleIcon /> : <WarningIcon />}
                </span>
                <span className="w-28 flex-shrink-0" style={{ color: 'var(--ink)' }}>
                  {c.label}
                </span>
                <span className="text-xs flex-1" style={{ color: 'var(--ink-faint)', lineHeight: 1.6 }}>
                  {c.detail}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.report_file && (
        <div className="text-xs mt-4" style={{ color: 'var(--ink-faint)' }}>
          A build report was generated: <code style={{ color: 'var(--ink-muted)' }}>{result.report_file}</code>{' '}
          (included in the download).
        </div>
      )}
    </div>
  )
}
