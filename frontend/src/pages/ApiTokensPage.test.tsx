import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp } from 'antd'
import type { ApiToken } from '../api/apiTokensApi'

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), revoke: vi.fn() }))
vi.mock('../api/apiTokensApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/apiTokensApi')>()),
  apiTokensApi: api,
}))
const auth = vi.hoisted(() => ({ manage: false }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ hasPermission: (code: string) => code === 'user:manage' && auth.manage }),
}))

import ApiTokensPage from './ApiTokensPage'

// Obviously fake: right shape, never issued by any server.
const FAKE = 'pwt_' + '0'.repeat(43) + 'FAKE00'

const token = (id: number, extra: Partial<ApiToken> = {}): ApiToken => ({
  id, name: `ci-${id}`, prefix: 'pwt_00000000', scopes: ['builds:read'], owner: 'tony',
  created_at: '2026-11-20T00:00:00', expires_at: '2099-01-01T00:00:00', last_used_at: null,
  revoked_at: null, status: 'active', ...extra,
})

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AntApp>
        <ApiTokensPage />
      </AntApp>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  auth.manage = false
  api.list.mockResolvedValue([])
})

describe('API tokens page', () => {
  it('creates a token with the chosen scopes and expiry, and shows it once', async () => {
    api.create.mockResolvedValue({ ...token(5, { name: 'release', scopes: ['builds:read', 'builds:write'] }), token: FAKE })
    show()
    fireEvent.click((await screen.findAllByRole('button', { name: /Create token/ }))[0])
    const dialog = await screen.findByRole('dialog', { name: 'Create an API token' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'release' } })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Start builds/ }))
    fireEvent.click(within(dialog).getByText('90 days'))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create token' }))

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    expect(api.create.mock.calls[0][0]).toEqual({ name: 'release', scopes: ['builds:read', 'builds:write'], expires_in_days: 90 })
    // The closing create dialog keeps the new one out of the accessibility tree in
    // jsdom (no animation end), so look it up by its contents.
    expect(await screen.findByLabelText('New token')).toHaveTextContent(FAKE)
    expect(screen.getByText(/only time it is shown/)).toBeInTheDocument()
    expect(screen.getByText('Copy your new token')).toBeInTheDocument()

    // Closing it (and the token leaving the page) is checked in a real browser: jsdom
    // never ends antd's closing animation, so the dialog's content stays mounted here.
  })

  it('refuses to create without a name or a scope', async () => {
    show()
    fireEvent.click((await screen.findAllByRole('button', { name: /Create token/ }))[0])
    const dialog = await screen.findByRole('dialog', { name: 'Create an API token' })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Read builds/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create token' }))
    expect(await within(dialog).findByText('Give the token a name')).toBeInTheDocument()
    expect(await within(dialog).findByText('Choose at least one scope')).toBeInTheDocument()
    expect(api.create).not.toHaveBeenCalled()
  })

  it('lists active tokens with a Revoke button and ended ones without', async () => {
    api.list.mockResolvedValue([
      token(1, { last_used_at: '2026-11-20T00:00:00' }),
      token(2, { status: 'revoked', revoked_at: '2026-11-19T00:00:00' }),
    ])
    api.revoke.mockResolvedValue(undefined)
    show()
    const activeList = await screen.findByRole('list', { name: 'Active tokens' })
    expect(within(activeList).getByText('ci-1')).toBeInTheDocument()
    const ended = screen.getByRole('list', { name: 'Expired and revoked tokens' })
    expect(within(ended).getByText('ci-2')).toBeInTheDocument()
    expect(within(ended).queryByRole('button', { name: /Revoke/ })).not.toBeInTheDocument()

    fireEvent.click(within(activeList).getByRole('button', { name: 'Revoke ci-1' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(api.revoke).toHaveBeenCalledWith(1, expect.anything()))
  })

  it("offers everyone's tokens only to user:manage", async () => {
    show()
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(false))
    expect(screen.queryByText('Everyone')).not.toBeInTheDocument()
  })

  it("lists everyone's tokens with their owners for user:manage", async () => {
    auth.manage = true
    api.list.mockImplementation(async (everyone: boolean) => (everyone ? [token(3, { owner: 'alice' })] : []))
    show()
    fireEvent.click(await screen.findByText('Everyone'))
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(true))
    expect(await screen.findByText('alice')).toBeInTheDocument()
  })
})
