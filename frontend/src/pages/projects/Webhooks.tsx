import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button, Input, Modal, Popconfirm, Segmented, Switch, Tooltip, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectApi } from '../../api/client'
import type { CreatedProjectHook, HookDelivery, HookProvider, ProjectHook } from '../../api/types'
import {
  ArrowsClockwiseIcon, CheckIcon, CopyIcon, GitBranchIcon, GithubLogoIcon, GitlabLogoIcon, KeyIcon, PencilSimpleIcon,
  PlusIcon, TrashIcon, WarningIcon, WebhooksLogoIcon,
} from '../../components/ui/icons'
import { getErrorDetail } from '../../utils/errors'
import { parseUtc, timeAgo } from '../../utils/time'

const PROVIDERS: Record<HookProvider, { label: string; icon: ReactNode; steps: string[] }> = {
  github: {
    label: 'GitHub',
    icon: <GithubLogoIcon />,
    steps: [
      'In the repository: Settings, Webhooks, Add webhook.',
      'Payload URL: the URL above. Content type: application/json. Secret: the secret above.',
      'Which events: "Just the push event" (it covers branches and tags). Add webhook.',
    ],
  },
  gitlab: {
    label: 'GitLab',
    icon: <GitlabLogoIcon />,
    steps: [
      'In the project: Settings, Webhooks, Add new webhook.',
      'URL: the URL above. Secret token: the secret above.',
      'Trigger: Push events and Tag push events. Add webhook.',
      'GitLab 19 and later can also sign deliveries: choose Generate signing token there, then paste it here with "Signing token".',
    ],
  },
  gitea: {
    label: 'Gitea',
    icon: <GitBranchIcon />,
    steps: [
      'In the repository: Settings, Webhooks, Add webhook, Gitea (Forgejo works the same).',
      'Target URL: the URL above. HTTP method: POST. POST content type: application/json. Secret: the secret above.',
      'Trigger on: Push events. Add webhook.',
    ],
  },
  generic: {
    label: 'Any script',
    icon: <WebhooksLogoIcon />,
    steps: [
      'POST to the URL with the token in a header: Authorization: Bearer <token>, or X-Packwright-Token: <token>.',
      'An empty body builds the project\'s own branch. {"ref": "main"} or {"ref": "refs/tags/v1.2.0", "commit": "<full id>"} names one.',
      'A sender that can only call a URL may add ?token=<token>, but the token then ends up in proxy and server logs.',
    ],
  },
}

const listOf = (patterns: string[]) => patterns.join('\n')

/**
 * Incoming webhooks: a push to the project's repository starts a build of the
 * pushed commit. Changes save at once; a secret is shown only when it is made.
 */
export default function Webhooks({ projectId, canEdit, fromGit, defaultBranch }: {
  projectId: number; canEdit: boolean; fromGit: boolean; defaultBranch: string
}) {
  const key = ['hooks', projectId]
  const queryClient = useQueryClient()
  const { data: list = [] } = useQuery({ queryKey: key, queryFn: () => projectApi.hooks(projectId) })
  const [created, setCreated] = useState<CreatedProjectHook | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })
  const shown = (hook: CreatedProjectHook) => { setCreated(hook); refresh() }

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-sm" style={{ color: 'var(--ink-muted)' }}>
        A push to the repository builds exactly the pushed commit, as the person who set the webhook up. Only
        branches and tags matching the webhook's patterns build; pings, deletions and commits marked{' '}
        <code>[skip ci]</code> are answered and ignored. Changes here are saved at once.
      </p>
      {!fromGit && (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>
          This project builds from a folder. Webhooks need a project that builds from a Git URL.
        </p>
      )}
      {fromGit && list.length === 0 && (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>No webhooks yet.</p>
      )}
      {list.map((h) => (
        <HookCard key={h.id} projectId={projectId} hook={h} onChange={refresh} onSecret={shown} />
      ))}
      {fromGit && (canEdit ? (
        <AddHook projectId={projectId} defaultBranch={defaultBranch} onAdded={shown} />
      ) : (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-faint)' }}>Only the project's creator or a project manager can change these.</p>
      ))}
      <SecretModal hook={created} onClose={() => setCreated(null)} />
    </div>
  )
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
    } catch {
      message.error('Copy failed: select it and copy it by hand')
    }
  }
  return (
    <Button size="small" icon={copied ? <CheckIcon /> : <CopyIcon />} onClick={copy} aria-label={`Copy ${label}`}>
      {copied ? 'Copied' : 'Copy'}
    </Button>
  )
}

function SecretModal({ hook, onClose }: { hook: CreatedProjectHook | null; onClose: () => void }) {
  const provider = hook ? PROVIDERS[hook.provider] : null
  return (
    <Modal
      title={hook ? `Set up the ${provider!.label} webhook` : ''}
      open={hook !== null}
      onCancel={onClose}
      footer={<Button type="primary" onClick={onClose}>Done</Button>}
      maskClosable={false}
      // Closed means gone: the secret must not stay in the page, hidden.
      destroyOnHidden
    >
      {hook && (
        <div className="mt-3">
          <p className="token-once">
            <WarningIcon /> The {hook.provider === 'generic' ? 'token' : 'secret'} is shown only now. Paste it where
            the steps below say, then close this.
          </p>
          <div className="hook-field-label">Payload URL</div>
          <div className="token-reveal">
            <code aria-label="Payload URL">{hook.url}</code>
            <CopyButton value={hook.url} label="payload URL" />
          </div>
          <div className="hook-field-label">{hook.provider === 'generic' ? 'Token' : 'Secret'}</div>
          <div className="token-reveal">
            <code aria-label="Webhook secret">{hook.secret}</code>
            <CopyButton value={hook.secret} label="secret" />
          </div>
          <ol className="hook-steps">
            {provider!.steps.map((s) => <li key={s}>{s}</li>)}
          </ol>
          {hook.provider === 'generic' && (
            <pre className="token-example">{`curl -X POST -H "Authorization: Bearer $PACKWRIGHT_HOOK_TOKEN" \\\n  -H "Content-Type: application/json" -d '{"ref": "main"}' \\\n  ${hook.url}`}</pre>
          )}
        </div>
      )}
    </Modal>
  )
}

type Mutations = ReturnType<typeof useHookMutations>

function useHookMutations(projectId: number, hook: ProjectHook, onChange: () => void, onSecret: (h: CreatedProjectHook) => void) {
  const failed = (fallback: string) => (err: unknown) => message.error(getErrorDetail(err, fallback))
  return {
    update: useMutation({
      mutationFn: (body: { branches?: string; tags?: string; enabled?: boolean; take_over?: boolean }) =>
        projectApi.updateHook(projectId, hook.id, body),
      onSuccess: onChange,
      onError: failed('Could not save the webhook'),
    }),
    rotate: useMutation({
      mutationFn: () => projectApi.rotateHook(projectId, hook.id),
      onSuccess: onSecret,
      onError: failed('Could not make a new secret'),
    }),
    signing: useMutation({
      mutationFn: (key: string | null) => projectApi.setHookSigningKey(projectId, hook.id, key),
      onSuccess: onChange,
      onError: failed('Could not save the signing token'),
    }),
    remove: useMutation({
      mutationFn: () => projectApi.removeHook(projectId, hook.id),
      onSuccess: onChange,
      onError: failed('Could not delete the webhook'),
    }),
  }
}

function HookCard({ projectId, hook, onChange, onSecret }: {
  projectId: number; hook: ProjectHook; onChange: () => void; onSecret: (h: CreatedProjectHook) => void
}) {
  const m = useHookMutations(projectId, hook, onChange, onSecret)
  const [editing, setEditing] = useState(false)
  const [signing, setSigning] = useState<string | null>(null)
  const [showDeliveries, setShowDeliveries] = useState(false)
  const provider = PROVIDERS[hook.provider]
  const name = `${provider.label} webhook`

  return (
    <section className="glass-card p-4" aria-label={name} data-enabled={hook.enabled}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-semibold inline-flex items-center gap-2" style={{ color: 'var(--ink)' }}>
            {provider.icon} {provider.label}
            {!hook.enabled && <span className="hook-state">off</span>}
          </div>
          <div className="hook-url">
            <code>{hook.url}</code>
            <CopyButton value={hook.url} label={`${name} URL`} />
          </div>
        </div>
        <label className="inline-flex items-center gap-2 text-sm" style={{ color: 'var(--ink-muted)' }}>
          <Switch size="small" checked={hook.enabled} disabled={!hook.can_edit} loading={m.update.isPending}
            aria-label={`${name} on`} onChange={(v) => m.update.mutate({ enabled: v })} />
          On
        </label>
      </div>

      {hook.disabled_reason && (
        <div className="hook-disabled" role="status">
          <WarningIcon />
          <span>
            Turned off: {hook.disabled_reason}.{' '}
            {hook.can_edit && (
              <Button size="small" type="link" className="p-0 h-auto"
                onClick={() => m.update.mutate({ enabled: true, take_over: true })}>
                Take it over and turn it on
              </Button>
            )}
          </span>
        </div>
      )}

      <dl className="hook-facts">
        <div><dt>Branches</dt><dd>{hook.branches.length ? hook.branches.map((p) => <code key={p}>{p}</code>) : 'none'}</dd></div>
        <div><dt>Tags</dt><dd>{hook.tags.length ? hook.tags.map((p) => <code key={p}>{p}</code>) : 'none'}</dd></div>
        <div><dt>Builds as</dt><dd>{hook.created_by}</dd></div>
        <div>
          <dt>Last delivery</dt>
          <dd>{hook.last_delivery_at
            ? <Tooltip title={parseUtc(hook.last_delivery_at).toLocaleString()}><span>{timeAgo(hook.last_delivery_at)}</span></Tooltip>
            : 'none yet'}</dd>
        </div>
        {hook.provider === 'gitlab' && (
          <div><dt>Signing token</dt><dd>{hook.has_signing_key ? 'set: deliveries must be signed' : 'not set'}</dd></div>
        )}
      </dl>

      {editing && <EditPatterns hook={hook} m={m} onDone={() => setEditing(false)} />}
      {signing !== null && (
        <div className="flex flex-wrap gap-2 mt-3">
          <Input.Password className="input-field flex-1 min-w-[220px]" size="small" value={signing} placeholder="whsec_…"
            aria-label="GitLab signing token" autoComplete="off" onChange={(e) => setSigning(e.target.value)} />
          <Button size="small" type="primary" disabled={!signing.trim()} loading={m.signing.isPending}
            onClick={() => m.signing.mutate(signing, { onSuccess: () => setSigning(null) })}>Save</Button>
          <Button size="small" onClick={() => setSigning(null)}>Cancel</Button>
        </div>
      )}

      <div className="flex flex-wrap gap-2 mt-3">
        <Button size="small" onClick={() => setShowDeliveries((v) => !v)} aria-expanded={showDeliveries}>
          {showDeliveries ? 'Hide deliveries' : 'Deliveries'}
        </Button>
        {hook.can_edit && (
          <>
            <Button size="small" icon={<PencilSimpleIcon />} onClick={() => setEditing(true)} disabled={editing}>Branches and tags</Button>
            <Popconfirm title="Make a new secret?" description="The old one stops working at once; paste the new one into the forge."
              okText="New secret" onConfirm={() => m.rotate.mutate()}>
              <Button size="small" icon={<ArrowsClockwiseIcon />} loading={m.rotate.isPending}>New secret</Button>
            </Popconfirm>
            {hook.provider === 'gitlab' && (hook.has_signing_key ? (
              <Popconfirm title="Remove the signing token?" description="The secret token alone is accepted again."
                okText="Remove" onConfirm={() => m.signing.mutate(null)}>
                <Button size="small" icon={<KeyIcon />}>Remove signing token</Button>
              </Popconfirm>
            ) : (
              <Button size="small" icon={<KeyIcon />} onClick={() => setSigning('')} disabled={signing !== null}>Signing token</Button>
            ))}
            <Popconfirm title="Delete this webhook?" description="Deliveries to its URL are refused from now on."
              okText="Delete" okButtonProps={{ danger: true }} onConfirm={() => m.remove.mutate()}>
              <Button size="small" danger icon={<TrashIcon />} loading={m.remove.isPending}>Delete</Button>
            </Popconfirm>
          </>
        )}
      </div>
      {showDeliveries && <Deliveries projectId={projectId} hookId={hook.id} />}
    </section>
  )
}

function EditPatterns({ hook, m, onDone }: { hook: ProjectHook; m: Mutations; onDone: () => void }) {
  const [branches, setBranches] = useState(listOf(hook.branches))
  const [tags, setTags] = useState(listOf(hook.tags))
  return (
    <div className="hook-patterns mt-3">
      <PatternFields branches={branches} tags={tags} setBranches={setBranches} setTags={setTags} />
      <div className="flex gap-2 mt-2">
        <Button size="small" type="primary" loading={m.update.isPending}
          onClick={() => m.update.mutate({ branches, tags }, { onSuccess: onDone })}>Save</Button>
        <Button size="small" onClick={onDone}>Cancel</Button>
      </div>
    </div>
  )
}

function PatternFields({ branches, tags, setBranches, setTags }: {
  branches: string; tags: string; setBranches: (v: string) => void; setTags: (v: string) => void
}) {
  return (
    <div className="hook-pattern-grid">
      <label>
        <span className="hook-field-label">Branches that build</span>
        <Input.TextArea className="input-field" rows={2} value={branches} placeholder="main"
          aria-label="Branch patterns" onChange={(e) => setBranches(e.target.value)} />
      </label>
      <label>
        <span className="hook-field-label">Tags that build</span>
        <Input.TextArea className="input-field" rows={2} value={tags} placeholder="v*"
          aria-label="Tag patterns" onChange={(e) => setTags(e.target.value)} />
      </label>
      <p className="m-0 text-[13px]" style={{ color: 'var(--ink-faint)', gridColumn: '1 / -1' }}>
        One pattern per line; <code>*</code> matches anything, also across <code>/</code> (<code>release/*</code>).
        Leave a box empty to build none of that kind.
      </p>
    </div>
  )
}

function AddHook({ projectId, defaultBranch, onAdded }: {
  projectId: number; defaultBranch: string; onAdded: (h: CreatedProjectHook) => void
}) {
  const [provider, setProvider] = useState<HookProvider>('github')
  const [branches, setBranches] = useState(defaultBranch || 'main')
  const [tags, setTags] = useState('v*')
  const add = useMutation({
    mutationFn: () => projectApi.addHook(projectId, { provider, branches, tags }),
    onSuccess: onAdded,
    onError: (err) => message.error(getErrorDetail(err, 'Could not add the webhook')),
  })
  return (
    <section className="glass-card p-4" aria-labelledby="add-hook">
      <h3 id="add-hook" className="text-[15px] font-semibold m-0 mb-3 flex items-center gap-2" style={{ color: 'var(--ink)' }}>
        <PlusIcon /> Add a webhook
      </h3>
      <Segmented<HookProvider>
        className="hook-providers"
        value={provider}
        onChange={setProvider}
        aria-label="Where pushes come from"
        options={(Object.keys(PROVIDERS) as HookProvider[]).map((k) => ({
          value: k,
          label: <span className="inline-flex items-center gap-1.5">{PROVIDERS[k].icon}{PROVIDERS[k].label}</span>,
        }))}
      />
      <div className="mt-3">
        <PatternFields branches={branches} tags={tags} setBranches={setBranches} setTags={setTags} />
      </div>
      <div className="flex justify-end mt-3">
        <Button type="primary" loading={add.isPending} onClick={() => add.mutate()}>Add webhook</Button>
      </div>
    </section>
  )
}

const RESULT_TEXT: Record<HookDelivery['result'], string> = { built: 'Built', ignored: 'Ignored', rejected: 'Rejected' }

function shortRef(ref: string | null): string {
  if (!ref) return ''
  return ref.replace(/^refs\/heads\//, '').replace(/^refs\/tags\//, 'tag ')
}

function Deliveries({ projectId, hookId }: { projectId: number; hookId: number }) {
  const { data = [], isLoading } = useQuery({
    queryKey: ['hook-deliveries', hookId],
    queryFn: () => projectApi.hookDeliveries(projectId, hookId),
    refetchInterval: 10_000,
  })
  if (isLoading) return <p className="text-sm mt-3 mb-0" style={{ color: 'var(--ink-faint)' }}>Loading deliveries…</p>
  if (data.length === 0) {
    return <p className="text-sm mt-3 mb-0" style={{ color: 'var(--ink-faint)' }}>Nothing received yet. The newest 50 deliveries are kept.</p>
  }
  return (
    <ul className="hook-deliveries" aria-label="Deliveries">
      {data.map((d) => (
        <li key={d.id} data-result={d.result}>
          <span className="hook-result">{RESULT_TEXT[d.result]}</span>
          <div className="min-w-0">
            <div className="hook-delivery-what">
              <Tooltip title={parseUtc(d.received_at).toLocaleString()}><span>{timeAgo(d.received_at)}</span></Tooltip>
              {d.event && <span>{d.event}</span>}
              {d.ref && <code>{shortRef(d.ref)}</code>}
              {d.commit_sha && <code>{d.commit_sha.slice(0, 12)}</code>}
            </div>
            <div className="hook-delivery-why">
              {d.task_id
                ? <Link to={`/history/${d.task_id}`}>{d.result === 'built' ? 'Build' : 'Same as build'} {d.task_id.slice(0, 8)}</Link>
                : null}
              {d.reason && <span>{d.task_id ? ' · ' : ''}{d.reason}</span>}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}
