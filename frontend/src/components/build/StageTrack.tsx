import { CheckIcon, ProhibitIcon, XCircleIcon } from '../ui/icons'
import { STAGE_LABELS, type TrackState } from './stages'

/**
 * Where a build is, as a track: done stages are filled in, the running one
 * pulses and the rail out of it moves, a failed one is marked where it failed.
 * When the stage advances, the rail behind it fills in, so progress is seen
 * happening rather than read off a percentage.
 */
export default function StageTrack({ items }: { items: { key: string; label: string; state: TrackState }[] }) {
  const current = items.find((s) => s.state === 'on' || s.state === 'failed' || s.state === 'stopped')
  // "Compile (Nuitka running)" → "Nuitka running"
  const detail = current ? (STAGE_LABELS[current.key] ?? '').match(/\(([^)]+)\)/)?.[1] : undefined
  return (
    <div>
      <ol className="stage-track" aria-label="Build stages">
        {items.map((s, i) => (
          <li key={s.key} className="stage" data-state={s.state} aria-current={s.state === 'on' ? 'step' : undefined}>
            <span className="stage-node" aria-hidden="true">
              {s.state === 'done' ? <CheckIcon /> : s.state === 'failed' ? <XCircleIcon /> : s.state === 'stopped' ? <ProhibitIcon /> : null}
            </span>
            <span className="stage-name">{s.label}</span>
            {i < items.length - 1 && <span className="stage-rail" data-state={s.state} aria-hidden="true" />}
          </li>
        ))}
      </ol>
      {current && detail && (
        <p className="stage-caption" data-state={current.state}>
          {current.state === 'on' ? 'Now: ' : current.state === 'failed' ? 'Failed while: ' : 'Stopped while: '}
          {detail}
        </p>
      )}
    </div>
  )
}
