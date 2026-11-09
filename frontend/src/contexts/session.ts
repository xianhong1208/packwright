/** Fired after this tab signs out, so state owned outside AuthContext (the
 *  react-query cache, the task store) can be dropped. */
export const SIGNED_OUT_EVENT = 'auth:signed-out'

/**
 * True when a failed refresh means the session itself is gone (the server
 * rejected the token), as opposed to the server being unreachable or erroring.
 * Only the former may clear the stored tokens.
 */
export function isSessionRejected(err: unknown): boolean {
  const status = (err as { response?: { status?: number } } | null)?.response?.status
  return status === 400 || status === 401 || status === 403
}

/** How long the session check keeps retrying a 429 before giving up, in seconds. */
export const SESSION_CHECK_MAX_WAIT = 90

/**
 * Seconds to wait before asking again after a 429, from its Retry-After header:
 * at least 1, at most 30 (the limiter's windows are a minute long), 5 when the
 * header is missing or unreadable.
 */
export function retryAfterSeconds(header: string | null): number {
  const seconds = Number.parseInt(header ?? '', 10)
  if (!Number.isFinite(seconds) || seconds < 1) return 5
  return Math.min(seconds, 30)
}
