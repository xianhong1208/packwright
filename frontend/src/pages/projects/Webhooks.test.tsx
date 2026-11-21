import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ProjectHook } from '../../api/types'

const api = vi.hoisted(() => ({
  hooks: vi.fn(), addHook: vi.fn(), updateHook: vi.fn(), rotateHook: vi.fn(),
  setHookSigningKey: vi.fn(), removeHook: vi.fn(), hookDeliveries: vi.fn(),
}))
vi.mock('../../api/client', () => ({ projectApi: api }))

import Webhooks from './Webhooks'

const hook: ProjectHook = {
  id: 4, provider: 'github', path: '/api/hooks/github/abc', url: 'http://pw.example/api/hooks/github/abc',
  branches: ['main'], tags: ['v*'], enabled: true, disabled_reason: null, has_signing_key: false,
  created_by: 'tony', created_at: '2026-11-21T00:00:00', secret_rotated_at: null, last_delivery_at: null, can_edit: true,
}

function show(props: Partial<{ canEdit: boolean; fromGit: boolean }> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Webhooks projectId={3} canEdit={props.canEdit ?? true} fromGit={props.fromGit ?? true} defaultBranch="develop" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  api.hooks.mockResolvedValue([hook])
})

describe('Project webhooks', () => {
  it('lists a hook with its URL, patterns and who it builds as, never a secret', async () => {
    show()
    const card = await screen.findByRole('region', { name: 'GitHub webhook' })
    expect(within(card).getByText(hook.url)).toBeInTheDocument()
    expect(within(card).getByText('main')).toBeInTheDocument()
    expect(within(card).getByText('v*')).toBeInTheDocument()
    expect(within(card).getByText('tony')).toBeInTheDocument()
    expect(card).not.toHaveTextContent(/secret:/i)
    expect(screen.getByRole('switch', { name: 'GitHub webhook on' })).toBeChecked()
  })

  it('creates a hook with the project branch prefilled and shows the secret once', async () => {
    api.addHook.mockResolvedValue({ ...hook, id: 5, provider: 'gitlab', secret: 's3cr3t-value' })
    show()
    expect(await screen.findByRole('textbox', { name: 'Branch patterns' })).toHaveValue('develop')
    fireEvent.click(screen.getByText('GitLab'))
    fireEvent.click(screen.getByRole('button', { name: 'Add webhook' }))
    await waitFor(() => expect(api.addHook).toHaveBeenCalledWith(3, { provider: 'gitlab', branches: 'develop', tags: 'v*' }))
    expect(await screen.findByLabelText('Webhook secret')).toHaveTextContent('s3cr3t-value')
    expect(screen.getByText(/Tag push events/)).toBeInTheDocument()
  })

  it('shows why Packwright turned a hook off and offers to take it over', async () => {
    api.hooks.mockResolvedValue([{ ...hook, enabled: false, disabled_reason: "tony's account is deactivated" }])
    api.updateHook.mockResolvedValue(hook)
    show()
    expect(await screen.findByText(/Turned off: tony's account is deactivated/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Take it over and turn it on' }))
    await waitFor(() => expect(api.updateHook).toHaveBeenCalledWith(3, 4, { enabled: true, take_over: true }))
  })

  it('lists deliveries with what came of each', async () => {
    api.hookDeliveries.mockResolvedValue([
      { id: 2, received_at: '2026-11-21T01:00:00', delivery_id: 'd2', event: 'push', ref: 'refs/heads/main',
        commit_sha: 'ab'.repeat(20), result: 'built', reason: null, task_id: '1234abcd-0000' },
      { id: 1, received_at: '2026-11-21T00:59:00', delivery_id: 'd1', event: 'ping', ref: null,
        commit_sha: null, result: 'ignored', reason: 'ping: the hook is connected', task_id: null },
    ])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Deliveries' }))
    const list = await screen.findByRole('list', { name: 'Deliveries' })
    expect(list).toHaveTextContent('Built')
    expect(list).toHaveTextContent('abababababab')
    expect(screen.getByRole('link', { name: /Build 1234abcd/ })).toHaveAttribute('href', '/history/1234abcd-0000')
    expect(list).toHaveTextContent('ping: the hook is connected')
  })

  it('a folder project cannot have webhooks; someone else sees but cannot change them', async () => {
    api.hooks.mockResolvedValue([])
    show({ fromGit: false })
    expect(await screen.findByText(/Webhooks need a project that builds from a Git URL/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add webhook' })).not.toBeInTheDocument()
  })
})
