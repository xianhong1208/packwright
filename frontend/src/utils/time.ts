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

/** "expires in 12 days", "expires tomorrow", "expired 3 days ago". */
export function expiryText(iso: string, now = Date.now()): string {
  const ms = parseUtc(iso).getTime() - now
  if (ms <= 0) return `expired ${timeAgo(iso, now)}`
  const days = Math.floor(ms / 86_400_000)
  if (days === 0) {
    const hours = Math.max(1, Math.floor(ms / 3_600_000))
    return `expires in ${hours} h`
  }
  return days === 1 ? 'expires tomorrow' : `expires in ${days} days`
}

/** A time as the schedule's own zone tells it, e.g. "Mon, 23 Nov 2026, 02:00 GMT+8". */
export function zonedTime(iso: string, zone: string): string {
  const date = parseUtc(iso)
  const options: Intl.DateTimeFormatOptions = {
    weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23', timeZoneName: 'short',
  }
  try {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone: zone }).format(date)
  } catch {
    return new Intl.DateTimeFormat(undefined, options).format(date)
  }
}

/** "in 5 min", "in 3 h", "in 2 days". */
export function timeUntil(iso: string, now = Date.now()): string {
  const s = (parseUtc(iso).getTime() - now) / 1000
  if (s < 60) return 'in under a minute'
  const m = Math.round(s / 60)
  if (m < 60) return `in ${m} min`
  const h = Math.round(m / 60)
  if (h < 48) return `in ${h} h`
  return `in ${Math.round(h / 24)} days`
}
