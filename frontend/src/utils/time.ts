// Reading the server's timestamps. They are UTC, and most carry no zone.

/** Server timestamps are UTC; one without a zone is read as UTC, not local time. */
export function parseUtc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso.replace(' ', 'T')}Z`)
}

/** "3 min ago", "yesterday", or the date once it is a month old. */
export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - parseUtc(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.floor(h / 24)
  if (d === 1) return 'yesterday'
  if (d < 30) return `${d} days ago`
  return parseUtc(iso).toLocaleDateString()
}
