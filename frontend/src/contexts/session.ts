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
