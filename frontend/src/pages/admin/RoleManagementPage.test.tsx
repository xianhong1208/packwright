import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import type { Role } from '../../api/types'

const api = vi.hoisted(() => ({
  getRoles: vi.fn(), getPermissions: vi.fn(), getUsersCount: vi.fn(), updateRole: vi.fn(),
  createRole: vi.fn(), deleteRole: vi.fn(),
}))
vi.mock('../../api/userApi', () => ({ userApi: api }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ hasPermission: () => true }) }))

import RoleManagementPage from './RoleManagementPage'

const role = (id: number, name: string, extra: Partial<Role> = {}): Role => ({
  id, name, display_name: name.charAt(0).toUpperCase() + name.slice(1), description: null,
  created_at: '2026-11-13T00:00:00', permissions: [], parent_role_id: null, is_system: false, is_active: true,
  ...extra,
})

const base = role(2, 'reviewer', { permissions: [{ id: 1, code: 'task:create', name: 'Create builds', description: '', category: 'tasks' }] })
const child = role(3, 'intern', { parent_role_id: 2 })

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  api.getRoles.mockResolvedValue([base, child])
  api.getPermissions.mockResolvedValue([])
  api.getUsersCount.mockResolvedValue({ count: 0 })
  api.updateRole.mockResolvedValue(child)
})

async function openEdit() {
  render(<RoleManagementPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Intern' }))
  return screen.findByRole('dialog')
}

describe('Roles dialog parent role', () => {
  it('sends null when the parent is removed, so the API clears it', async () => {
    const dialog = await openEdit()
    // The Select shows the current parent; its clear icon empties it.
    expect(within(dialog).getByTitle('Reviewer')).toBeInTheDocument()
    const clear = dialog.querySelector('.ant-select-clear')
    expect(clear).not.toBeNull()
    fireEvent.mouseDown(clear!)
    fireEvent.click(clear!)
    await waitFor(() => expect(within(dialog).queryByTitle('Reviewer')).not.toBeInTheDocument())
    fireEvent.click(within(dialog).getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(api.updateRole).toHaveBeenCalledTimes(1))
    const [id, payload] = api.updateRole.mock.calls[0]
    expect(id).toBe(3)
    expect(payload).toHaveProperty('parent_role_id', null)
  })

  it('sends the parent unchanged when it is left alone', async () => {
    const dialog = await openEdit()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(api.updateRole).toHaveBeenCalledWith(3, expect.objectContaining({ parent_role_id: 2 })))
  })
})
