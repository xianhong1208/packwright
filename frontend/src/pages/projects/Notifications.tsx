import { useState, type ReactNode } from 'react'
import { Button, Input, Popconfirm, Segmented, Switch, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectApi } from '../../api/client'
import type { NotificationKind, ProjectNotification } from '../../api/types'
import { DiscordLogoIcon, PaperPlaneTiltIcon, PlusIcon, SlackLogoIcon, TrashIcon, WebhooksLogoIcon } from '../../components/ui/icons'
import { getErrorDetail } from '../../utils/errors'
import { timeAgo } from '../../utils/time'

const KINDS: Record<NotificationKind, { label: string; icon: ReactNode; placeholder: string; how: string }> = {
  discord: {
    label: 'Discord',
    icon: <DiscordLogoIcon />,
    placeholder: 'https://discord.com/api/webhooks/…',
    how: 'In Discord: channel settings, Integrations, Webhooks, New Webhook, Copy Webhook URL.',
  },
  slack: {
    label: 'Slack',
    icon: <SlackLogoIcon />,
    placeholder: 'https://hooks.slack.com/services/…',
    how: 'In Slack: add an Incoming Webhook to a Slack app for the channel and copy its URL.',
  },
  webhook: {
    label: 'Webhook',
    icon: <WebhooksLogoIcon />,
    placeholder: 'https://example.com/hooks/packwright',
    how: 'Packwright POSTs JSON: event, project, version, build_id, status, triggered_by, duration_seconds, diagnosis, url.',
  },
}

/**
 * Where this project's build results are sent. Changes save at once: this tab
 * is not part of the settings form, and a webhook URL is never sent back here.
 */
export default function Notifications({ projectId, canEdit }: { projectId: number; canEdit: boolean }) {
  const key = ['notifications', projectId]
  const queryClient = useQueryClient()
  const { data: list = [] } = useQuery({ queryKey: key, queryFn: () => projectApi.notifications(projectId) })
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })
  const failed = (fallback: string) => (err: unknown) => message.error(getErrorDetail(err, fallback))

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-sm" style={{ color: 'var(--ink-muted)' }}>
        A message goes to each of these as soon as a build of this project passes or fails. Messages link to the
        build when the server's <code>PUBLIC_URL</code> is set. Changes here are saved at once.
      </p>
      {list.length === 0 && (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>No notifications yet.</p>
      )}
      {list.map((n) => (
        <Destination key={n.id} projectId={projectId} n={n} canEdit={canEdit} onChange={refresh} onError={failed} />
      ))}
      {canEdit ? (
        <AddDestination projectId={projectId} onAdded={refresh} onError={failed} />
      ) : (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>Only the project's creator or a project manager can change these.</p>
      )}
    </div>
  )
}

type ErrorHandler = (fallback: string) => (err: unknown) => void

function Destination({ projectId, n, canEdit, onChange, onError }: {
  projectId: number; n: ProjectNotification; canEdit: boolean; onChange: () => void; onError: ErrorHandler
}) {
  const [newUrl, setNewUrl] = useState<string | null>(null)
  const update = useMutation({
    mutationFn: (body: { url?: string; on_failed?: boolean; on_passed?: boolean }) =>
      projectApi.updateNotification(projectId, n.id, body),
    onSuccess: () => { setNewUrl(null); onChange() },
    onError: onError('Could not save the notification'),
  })
  const test = useMutation({
    mutationFn: () => projectApi.testNotification(projectId, n.id),
    onSuccess: (r) => {
      if (r.ok) message.success(`Test message sent to ${KINDS[n.kind].label}.`)
      else message.error(r.error ?? 'The test message was not delivered.')
      onChange()
    },
    onError: onError('Could not send the test message'),
  })
  const remove = useMutation({
    mutationFn: () => projectApi.removeNotification(projectId, n.id),
    onSuccess: onChange,
    onError: onError('Could not remove the notification'),
  })
  const kind = KINDS[n.kind]

  return (
    <section className="glass-card p-4" aria-label={`${kind.label} notification`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold inline-flex items-center gap-2" style={{ color: 'var(--ink)' }}>
            {kind.icon} {kind.label}
          </div>
          <div className="text-sm break-all" style={{ color: 'var(--ink-muted)' }}><code>{n.url_hint}</code></div>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-sm" style={{ color: 'var(--ink-muted)' }}>
          <label className="inline-flex items-center gap-2">
            <Switch size="small" checked={n.on_failed} disabled={!canEdit} loading={update.isPending}
              aria-label={`Send to ${kind.label} when a build fails`} onChange={(v) => update.mutate({ on_failed: v })} />
            Failed
          </label>
          <label className="inline-flex items-center gap-2">
            <Switch size="small" checked={n.on_passed} disabled={!canEdit} loading={update.isPending}
              aria-label={`Send to ${kind.label} when a build passes`} onChange={(v) => update.mutate({ on_passed: v })} />
            Passed
          </label>
        </div>
      </div>

      <div className="text-[13px] mt-2" style={{ color: n.last_ok === false ? 'var(--color-alert-400)' : 'var(--ink-faint)' }}>
        {n.last_sent_at === null
          ? 'Nothing sent yet.'
          : n.last_ok
            ? `Last message delivered ${timeAgo(n.last_sent_at)}.`
            : `Last message not delivered (${timeAgo(n.last_sent_at)}): ${n.last_error}`}
      </div>

      {canEdit && (newUrl === null ? (
        <div className="flex flex-wrap gap-2 mt-3">
          <Button size="small" icon={<PaperPlaneTiltIcon />} loading={test.isPending} onClick={() => test.mutate()}>Send test</Button>
          <Button size="small" onClick={() => setNewUrl('')}>Change URL</Button>
          <Popconfirm title="Remove this notification?" okText="Remove" onConfirm={() => remove.mutate()}>
            <Button size="small" danger icon={<TrashIcon />} loading={remove.isPending}>Remove</Button>
          </Popconfirm>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2 mt-3">
          <Input className="input-field flex-1 min-w-[220px]" size="small" value={newUrl} placeholder={kind.placeholder}
            aria-label="New webhook URL" onChange={(e) => setNewUrl(e.target.value)} />
          <Button size="small" type="primary" disabled={!newUrl.trim()} loading={update.isPending}
            onClick={() => update.mutate({ url: newUrl })}>Save URL</Button>
          <Button size="small" onClick={() => setNewUrl(null)}>Cancel</Button>
        </div>
      ))}
    </section>
  )
}

function AddDestination({ projectId, onAdded, onError }: { projectId: number; onAdded: () => void; onError: ErrorHandler }) {
  const [kind, setKind] = useState<NotificationKind>('discord')
  const [url, setUrl] = useState('')
  const [onFailed, setOnFailed] = useState(true)
  const [onPassed, setOnPassed] = useState(true)
  const add = useMutation({
    mutationFn: () => projectApi.addNotification(projectId, { kind, url, on_failed: onFailed, on_passed: onPassed }),
    onSuccess: () => {
      setUrl('')
      message.success('Notification added. Send a test to check it arrives.')
      onAdded()
    },
    onError: onError('Could not add the notification'),
  })

  return (
    <section className="glass-card p-4" aria-labelledby="add-notification">
      <h3 id="add-notification" className="text-[15px] font-semibold m-0 mb-3 inline-flex items-center gap-2" style={{ color: 'var(--ink)' }}>
        <PlusIcon /> Add a notification
      </h3>
      <Segmented<NotificationKind>
        value={kind}
        onChange={setKind}
        aria-label="Where to send"
        options={(Object.keys(KINDS) as NotificationKind[]).map((k) => ({
          value: k,
          label: <span className="inline-flex items-center gap-1.5">{KINDS[k].icon}{KINDS[k].label}</span>,
        }))}
      />
      <Input className="input-field mt-3" value={url} placeholder={KINDS[kind].placeholder} aria-label="Webhook URL"
        onChange={(e) => setUrl(e.target.value)} />
      <p className="m-0 mt-1 text-[13px]" style={{ color: 'var(--ink-faint)' }}>{KINDS[kind].how}</p>
      <div className="flex flex-wrap items-center justify-between gap-3 mt-3">
        <div className="flex flex-wrap items-center gap-4 text-sm" style={{ color: 'var(--ink-muted)' }}>
          <label className="inline-flex items-center gap-2">
            <Switch size="small" checked={onFailed} onChange={setOnFailed} aria-label="New notification: when a build fails" /> When a build fails
          </label>
          <label className="inline-flex items-center gap-2">
            <Switch size="small" checked={onPassed} onChange={setOnPassed} aria-label="New notification: when a build passes" /> When a build passes
          </label>
        </div>
        <Button type="primary" disabled={!url.trim()} loading={add.isPending} onClick={() => add.mutate()}>Add</Button>
      </div>
    </section>
  )
}
