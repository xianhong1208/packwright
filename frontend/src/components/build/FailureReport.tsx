import { Button } from 'antd'
import { CloseCircleOutlined, WarningOutlined } from '@ant-design/icons'
import type { BuildResult } from '../../api/types'
import { extractErrorLines } from '../../utils/diagnose'
import { STAGE_LABELS } from './stages'

interface FailureReportProps {
  result: BuildResult | null | undefined
  /** The live log when it is still in memory; used only when the server stored no error lines. */
  logs?: string[]
  statusMsg?: string | null
  /** Where the full log is on this page, for the "no diagnosis" hint. */
  logHint?: string
  /** Rebuild with a diagnosis' suggested config change. Omit to hide those buttons. */
  onApplyFix?: (overrides: Record<string, unknown>) => void
}

/**
 * Why a build failed: the stage, the automatic diagnosis (with a one-click fix
 * when the platform can apply it) and the key error lines. Shared by the live
 * task page and the history page — the history copy had drifted and no longer
 * showed the failed stage, on exactly the page used to look back at a failure.
 */
export default function FailureReport({ result, logs = [], statusMsg, logHint, onApplyFix }: FailureReportProps) {
  // Server-selected lines persist past log eviction; the live log is the
  // fallback for a task that has just finished.
  const errLines = result?.error_lines?.length ? result.error_lines : extractErrorLines(logs)

  return (
    <div className="glass-card p-5 mb-6 border-l-2 border-alert-500 bg-alert-500/5">
      <div className="flex items-center gap-2 mb-3">
        <CloseCircleOutlined className="text-alert-400" />
        <h3 className="text-base font-medium text-alert-400">Build failed</h3>
      </div>
      {statusMsg && (
        <p className="text-sm mb-3" style={{ color: 'var(--ink-muted)' }}>
          {statusMsg}
        </p>
      )}

      {/* Name the stage before the details. Someone who cannot read a stack
          trace can still act on "it failed while installing dependencies". */}
      {result?.failed_stage && (
        <div className="text-xs mb-3" style={{ color: 'var(--ink-faint)' }}>
          Failed stage:
          <span className="text-alert-400 ml-1">{STAGE_LABELS[result.failed_stage] ?? result.failed_stage}</span>
        </div>
      )}

      {result?.diagnosis && result.diagnosis.length > 0 ? (
        <div className="space-y-3 mb-3">
          {result.diagnosis.map((d, i) => (
            <div key={i} className="rounded-lg p-3 bg-void-950">
              <div className="text-sm text-alert-400 font-medium mb-1 flex items-start gap-1.5"><WarningOutlined className="mt-[3px]" />{d.problem}</div>
              <div className="text-sm text-[var(--ink)]">Suggested fix: {d.suggestion}</div>
              {d.evidence && (
                <code className="block text-xs mt-1.5 font-mono break-all" style={{ color: 'var(--ink-faint)' }}>
                  {d.evidence}
                </code>
              )}
              {/* The fix, when the platform can apply it: rebuild with the corrected
                  setting instead of re-entering the whole form from memory. */}
              {d.action && onApplyFix && (
                <Button size="small" type="primary" className="mt-2" onClick={() => onApplyFix(d.action!.overrides)}>
                  {d.action.label}
                </Button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs mb-3" style={{ color: 'var(--ink-faint)' }}>
          We couldn't identify the cause automatically. Check the key error lines below
          {logHint ? ` and ${logHint}` : ''}.
        </p>
      )}

      {errLines.length > 0 && (
        <div>
          <div className="text-xs mb-1.5" style={{ color: 'var(--ink-faint)' }}>
            Key error lines
          </div>
          <div className="rounded-lg p-3 font-mono text-xs space-y-1 bg-void-950">
            {errLines.map((l, i) => (
              <div key={i} className="text-alert-400 break-all">
                {l}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
