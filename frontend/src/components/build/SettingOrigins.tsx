import { Tooltip } from 'antd'
import type { BuildConfig, EffectiveSettings } from '../../api/types'
import { ORIGIN_LABELS, formatValue, settingRows } from './settingRows'

/**
 * Every setting a build was made with and where it came from: the repository's
 * packwright.toml (with its line), this build's own change, the project's
 * settings, or what the console detected. The file wins over the others.
 */
export default function SettingOrigins({ effective, config }: { effective?: EffectiveSettings | null; config: BuildConfig }) {
  const groups = settingRows(effective, config)
  const read = Boolean(effective?.config)
  const file = effective?.file
  return (
    <section className="glass-card p-5 mb-6" aria-labelledby="setting-origins-title">
      <h3 id="setting-origins-title" className="text-sm font-medium mb-1" style={{ color: 'var(--ink-muted)' }}>
        Settings and where they came from
      </h3>
      <p className="text-xs mb-4" style={{ color: 'var(--ink-faint)' }}>
        {!read
          ? 'packwright.toml is read from the source when the build starts; until then these are the settings it was filed with.'
          : file
            ? `${Object.keys(file.fields).length} came from packwright.toml in the source, which wins over this build's changes and the project's settings.`
            : 'The source had no packwright.toml: these are the settings the build was filed with.'}
      </p>
      <div className="origin-groups">
        {groups.map(({ group, rows }) => (
          <div key={group} className="origin-group">
            <h4>{group}</h4>
            <ul className="origin-list">
              {rows.map((row) => (
                <li key={row.field} data-field={row.field}>
                  <span className="origin-label">{row.label}</span>
                  <span className="origin-value">
                    <code>{row.value}</code>
                    {row.file?.replaced && (
                      <span className="origin-replaced">
                        instead of {ORIGIN_LABELS[row.file.replaced.origin] === 'this build' ? "this build's" : "the project's"}{' '}
                        <code>{formatValue(row.file.replaced.value)}</code>
                      </span>
                    )}
                  </span>
                  {row.file ? (
                    <Tooltip
                      title={
                        <div>
                          <div>packwright.toml{row.file.line ? `, line ${row.file.line}` : ''}:</div>
                          <code style={{ overflowWrap: 'anywhere' }}>{row.file.text || row.file.key}</code>
                        </div>
                      }
                    >
                      <span className="origin-badge" data-origin="file" tabIndex={0}>
                        packwright.toml{row.file.line ? ` · line ${row.file.line}` : ''}
                      </span>
                    </Tooltip>
                  ) : (
                    <span className="origin-badge" data-origin={row.origin}>{ORIGIN_LABELS[row.origin]}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  )
}
