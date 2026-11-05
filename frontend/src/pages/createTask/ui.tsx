// Presentational pieces shared by the New build steps. They used to be defined inside
// the page's render function, which gave them a new identity on every render.
// ── Section panel header (flat, hairline seam under the title) ──
export const SectionHeader = ({ icon, title, tone = 'cyber', action }: { icon: React.ReactNode; title: string; tone?: 'cyber' | 'matrix' | 'signal'; action?: React.ReactNode }) => (
  <div className="flex items-center justify-between mb-4 pb-3 border-b border-[var(--seam)]">
    <span className={`text-sm font-semibold flex items-center gap-2 text-${tone}-400`} style={{ fontFamily: 'var(--font-display)' }}>
      {icon}
      {title}
    </span>
    {action}
  </div>
)

// ── Summary row for confirmation page ──
export const SummaryRow = ({ label, value, mono, highlight }: { label: string; value: React.ReactNode; mono?: boolean; highlight?: boolean }) => (
  <div className="flex py-1.5 border-b border-[var(--seam)]">
    <span className="text-sm w-36 flex-shrink-0" style={{ color: 'var(--ink-faint)' }}>{label}</span>
    <span
      className={`text-sm ${highlight ? 'text-matrix-400 font-medium' : ''} ${mono ? 'font-mono' : ''}`}
      style={highlight ? undefined : { color: 'var(--ink)' }}
    >
      {value || '—'}
    </span>
  </div>
)
