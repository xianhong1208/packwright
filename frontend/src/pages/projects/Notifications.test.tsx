import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ProjectNotification } from '../../api/types'

const api = vi.hoisted(() => ({
  notifications: vi.fn(), addNotification: vi.fn(), updateNotification: vi.fn(),
  removeNotification: vi.fn(), testNotification: vi.fn(),
}))
vi.mock('../../api/client', () => ({ projectApi: api }))

import Notifications from './Notifications'

const slack: ProjectNotification = {
  id: 7, kind: 'slack', url_hint: 'hooks.slack.com …TAIL', on_failed: true, on_passed: false,
  created_by: 'tony', created_at: '2026-11-06T00:00:00', last_sent_at: null, last_ok: null, last_error: null,
}

function show(canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Notifications projectId={3} canEdit={canEdit} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  api.notifications.mockResolvedValue([slack])
})

describe('Project notifications', () => {
  it('lists a destination by its hint, with what it is sent', async () => {
    show()
    expect(await screen.findByText('hooks.slack.com …TAIL')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Send to Slack when a build fails' })).toBeChecked()
    expect(screen.getByRole('switch', { name: 'Send to Slack when a build passes' })).not.toBeChecked()
    expect(screen.getByRole('switch', { name: 'New notification: when a build passes' })).toBeChecked()
    expect(screen.getByText('Nothing sent yet.')).toBeInTheDocument()
  })

  it('saves a switch as soon as it changes', async () => {
    api.updateNotification.mockResolvedValue({ ...slack, on_passed: true })
    show()
    fireEvent.click(await screen.findByRole('switch', { name: 'Send to Slack when a build passes' }))
    await waitFor(() => expect(api.updateNotification).toHaveBeenCalledWith(3, 7, { on_passed: true }))
  })

  it('adds a destination of the chosen kind, both outcomes on by default', async () => {
    api.addNotification.mockResolvedValue({ ...slack, id: 8, kind: 'discord' })
    show()
    await screen.findByText('hooks.slack.com …TAIL')
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Webhook URL'), { target: { value: 'https://discord.com/api/webhooks/1/x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(api.addNotification).toHaveBeenCalledWith(3, {
      kind: 'discord', url: 'https://discord.com/api/webhooks/1/x', on_failed: true, on_passed: true,
    }))
  })

  it('says why the last message did not arrive', async () => {
    api.notifications.mockResolvedValue([{ ...slack, last_sent_at: '2026-11-06T00:00:00', last_ok: false, last_error: 'hooks.slack.com answered HTTP 404' }])
    show()
    expect(await screen.findByText(/Last message not delivered .*: hooks.slack.com answered HTTP 404/)).toBeInTheDocument()
  })

  it('sends a test message on request', async () => {
    api.testNotification.mockResolvedValue({ ok: true, error: null })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /Send test/ }))
    await waitFor(() => expect(api.testNotification).toHaveBeenCalledWith(3, 7))
  })

  it('replaces the URL without ever showing the old one', async () => {
    api.updateNotification.mockResolvedValue(slack)
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Change URL' }))
    const input = screen.getByLabelText('New webhook URL')
    expect(input).toHaveValue('')
    fireEvent.change(input, { target: { value: 'https://hooks.slack.com/services/T9/B9/new' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save URL' }))
    await waitFor(() => expect(api.updateNotification).toHaveBeenCalledWith(3, 7, { url: 'https://hooks.slack.com/services/T9/B9/new' }))
  })

  it('is read-only for someone who may not change the project', async () => {
    show(false)
    await screen.findByText('hooks.slack.com …TAIL')
    expect(screen.getByRole('switch', { name: 'Send to Slack when a build fails' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Send test/ })).toBeNull()
    expect(screen.queryByText('Add a notification')).toBeNull()
    expect(screen.getByText(/Only the project's creator or a project manager/)).toBeInTheDocument()
  })
})
