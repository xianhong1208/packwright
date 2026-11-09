// The same rules as app/services/git_credentials.normalize_host, so the form says
// what is wrong before the request is sent. A credential is found by the clone
// URL's host name, so a scheme, a path or a port in it never matches anything.
const LABEL = '[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?'
const HOSTNAME = new RegExp(`^${LABEL}(?:\\.${LABEL})*$`)
const IPV4 = /^(?:\d{1,3}\.){3}\d{1,3}$/

/** Why `value` cannot be a credential's host, or null when it can (or is blank). */
export function hostProblem(value: string | undefined | null): string | null {
  const host = (value ?? '').trim().toLowerCase().replace(/\.$/, '')
  if (!host) return null
  if (host.includes('://') || host.includes('/')) {
    return 'Enter the host name only, without https:// or a path (for example gitlab.example.com)'
  }
  if (IPV4.test(host) || host.replace(/^\[|\]$/g, '').includes('::')) return null
  if (host === 'localhost' || host.endsWith('.localhost')) {
    return 'localhost cannot be a Git host: Git URLs pointing at it are refused'
  }
  if (host.includes(':')) return 'Enter the host name without a port'
  if (host.length > 253 || !HOSTNAME.test(host)) return 'Not a valid host name'
  return null
}
