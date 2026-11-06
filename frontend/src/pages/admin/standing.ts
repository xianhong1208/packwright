import type { UserListItem } from '../../api/types'

/**
 * Where an account stands. An inactive account that has never signed in is a new
 * registration waiting to be let in; one that has signed in before was switched
 * off. Both are "not active", but an administrator does different things with
 * them, so the page tells them apart.
 */
export function standing(u: Pick<UserListItem, 'is_active' | 'last_login'>): { key: 'active' | 'waiting' | 'disabled'; label: string; color: string } {
  if (u.is_active) return { key: 'active', label: 'Active', color: 'var(--color-matrix-400)' }
  if (!u.last_login) return { key: 'waiting', label: 'Waiting', color: 'var(--color-signal-400)' }
  return { key: 'disabled', label: 'Disabled', color: 'var(--color-alert-400)' }
}
