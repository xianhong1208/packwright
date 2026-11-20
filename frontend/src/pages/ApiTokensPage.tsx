import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App as AntApp, Button, Checkbox, Form, Input, Modal, Popconfirm, Segmented, Spin, Tooltip } from 'antd'
import { CheckIcon, CopyIcon, PlusIcon, TerminalWindowIcon, WarningIcon } from '../components/ui/icons'
import PageHeader from '../components/layout/PageHeader'
import { useAuth } from '../contexts/AuthContext'
import {
  apiTokensApi,
  EXPIRY_PRESETS,
  TOKEN_SCOPES,
  type ApiToken,
  type CreatedApiToken,
  type TokenScope,
} from '../api/apiTokensApi'
import { expiryText, parseUtc, timeAgo } from '../utils/time'

const SCOPE_LABEL = Object.fromEntries(TOKEN_SCOPES.map((s) => [s.value, s.label])) as Record<TokenScope, string>

interface CreateValues {
  name: string
  scopes: TokenScope[]
  expires_in_days: number
}

/**
 * Personal API tokens: scripts and CI start builds, follow them and download
 * results with one of these instead of a password. A token can do what its
 * scopes allow and what its owner's role allows now, never more.
 */
export default function ApiTokensPage() {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = useAuth()
  const canSeeEveryone = hasPermission('user:manage')
  const [everyone, setEveryone] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [created, setCreated] = useState<CreatedApiToken | null>(null)
  const [copied, setCopied] = useState(false)
  const [form] = Form.useForm<CreateValues>()

  const showEveryone = canSeeEveryone && everyone
  const { data: tokens = [], isLoading } = useQuery({
    queryKey: ['api-tokens', showEveryone],
    queryFn: () => apiTokensApi.list(showEveryone),
  })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['api-tokens'] })

  const createMutation = useMutation({
    mutationFn: apiTokensApi.create,
    onSuccess: (token) => {
      setCreateOpen(false)
      setCopied(false)
      setCreated(token)
      form.resetFields()
      invalidate()
    },
    onError: (e: unknown) => message.error(errorText(e, 'Could not create the token')),
  })

  const revokeMutation = useMutation({
    mutationFn: apiTokensApi.revoke,
    onSuccess: () => {
      message.success('Token revoked')
      invalidate()
    },
    onError: (e: unknown) => message.error(errorText(e, 'Could not revoke the token')),
  })

  const openCreate = () => {
    form.setFieldsValue({ name: '', scopes: ['builds:read'], expires_in_days: 30 })
    setCreateOpen(true)
  }

  const copy = async () => {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.token)
      setCopied(true)
    } catch {
      message.error('Copy failed: select the token and copy it by hand')
    }
  }

  const active = tokens.filter((t) => t.status === 'active')
  const ended = tokens.filter((t) => t.status !== 'active')

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="API tokens"
        lead="Scripts and CI use a token instead of a password to start builds, follow them and download results. A token can do only what its scopes allow and what its owner's role allows."
        actions={
          <Button type="primary" icon={<PlusIcon />} onClick={openCreate}>
            Create token
          </Button>
        }
      />

      {canSeeEveryone && (
        <div className="mb-4">
          <Segmented
            aria-label="Whose tokens"
            value={everyone ? 'everyone' : 'mine'}
            onChange={(v) => setEveryone(v === 'everyone')}
            options={[{ value: 'mine', label: 'My tokens' }, { value: 'everyone', label: 'Everyone' }]}
          />
        </div>
      )}

      {isLoading ? (
        <div className="py-16 text-center"><Spin /></div>
      ) : tokens.length === 0 ? (
        <section className="glass-card p-6 sm:p-8" aria-labelledby="no-tokens">
          <h2 id="no-tokens" className="text-[17px] font-semibold m-0" style={{ color: 'var(--ink)' }}>
            {showEveryone ? 'Nobody has a token yet' : 'No tokens yet'}
          </h2>
          <p className="mt-1 mb-5 text-sm" style={{ color: 'var(--ink-muted)', maxWidth: '62ch' }}>
            Create one for each script or CI job, with only the scopes it needs, and send it as{' '}
            <code className="token-code">Authorization: Bearer pwt_…</code>. You can revoke it here at any time.
          </p>
          <Button type="primary" icon={<PlusIcon />} onClick={openCreate}>Create token</Button>
        </section>
      ) : (
        <>
          <TokenList
            label={showEveryone ? 'Active tokens, everyone' : 'Active tokens'}
            tokens={active}
            showOwner={showEveryone}
            onRevoke={(t) => revokeMutation.mutate(t.id)}
            revoking={revokeMutation.isPending}
          />
          {active.length === 0 && (
            <p className="text-sm" style={{ color: 'var(--ink-muted)' }}>No active tokens.</p>
          )}
          {ended.length > 0 && (
            <>
              <h2 className="token-section-title">Expired and revoked</h2>
              <TokenList label="Expired and revoked tokens" tokens={ended} showOwner={showEveryone} />
            </>
          )}
        </>
      )}

      <Modal
        title="Create an API token"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          try {
            createMutation.mutate(await form.validateFields())
          } catch {
            // The form shows what is missing next to each field.
          }
        }}
        confirmLoading={createMutation.isPending}
        okText="Create token"
        cancelText="Cancel"
        forceRender
      >
        <Form form={form} layout="vertical" className="mt-4" requiredMark={false}>
          <Form.Item
            name="name"
            label="Name"
            extra="What uses it, so you know which one to revoke."
            rules={[{ required: true, whitespace: true, message: 'Give the token a name' }]}
          >
            <Input placeholder="e.g. release workflow" maxLength={100} autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="scopes"
            label="Scopes"
            rules={[{ required: true, type: 'array', min: 1, message: 'Choose at least one scope' }]}
          >
            <Checkbox.Group className="token-scopes">
              {TOKEN_SCOPES.map((s) => (
                <Checkbox key={s.value} value={s.value}>
                  <span className="token-scope-name">{s.label}</span>
                  <code className="token-code">{s.value}</code>
                  <span className="token-scope-desc">{s.description}</span>
                </Checkbox>
              ))}
            </Checkbox.Group>
          </Form.Item>
          <Form.Item name="expires_in_days" label="Expires after" rules={[{ required: true }]}>
            <Segmented
              aria-label="Expires after"
              options={EXPIRY_PRESETS.map((d) => ({ value: d, label: d === 365 ? '1 year' : `${d} days` }))}
            />
          </Form.Item>
          <p className="text-xs m-0" style={{ color: 'var(--ink-faint)' }}>
            Tokens never reach user, role, credential or token settings, whatever your role.
          </p>
        </Form>
      </Modal>

      <Modal
        title="Copy your new token"
        open={created !== null}
        onCancel={() => setCreated(null)}
        footer={<Button type="primary" onClick={() => setCreated(null)}>Done</Button>}
        maskClosable={false}
        // Closed means gone: the token must not stay in the page, hidden.
        destroyOnHidden
      >
        {created && (
          <div className="mt-3">
            <p className="token-once">
              <WarningIcon /> This is the only time it is shown. Store it in your CI's secrets now.
            </p>
            <div className="token-reveal">
              <code aria-label="New token">{created.token}</code>
              <Button icon={copied ? <CheckIcon /> : <CopyIcon />} onClick={copy}>
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <p className="mt-4 mb-1 text-sm" style={{ color: 'var(--ink-muted)' }}>Try it:</p>
            <pre className="token-example">{`curl -H "Authorization: Bearer $PACKWRIGHT_TOKEN" \\\n  ${window.location.origin}/api/history`}</pre>
          </div>
        )}
      </Modal>
    </div>
  )
}

function TokenList({
  label,
  tokens,
  showOwner,
  onRevoke,
  revoking,
}: {
  label: string
  tokens: ApiToken[]
  showOwner: boolean
  onRevoke?: (t: ApiToken) => void
  revoking?: boolean
}) {
  if (tokens.length === 0) return null
  return (
    <ul className="cred-list mb-6" aria-label={label}>
      {tokens.map((t) => (
        <li key={t.id} className="cred-card token-card" data-status={t.status}>
          <span className="cred-mark" aria-hidden="true"><TerminalWindowIcon /></span>
          <div className="min-w-0 flex-1">
            <div className="build-name truncate">{t.name}</div>
            <div className="build-meta">
              <code>{t.prefix}…</code>
              {showOwner && <span>{t.owner}</span>}
              <Tooltip title={parseUtc(t.created_at).toLocaleString()}><span>created {timeAgo(t.created_at)}</span></Tooltip>
              {t.status === 'revoked' && t.revoked_at ? (
                <span className="token-ended">revoked {timeAgo(t.revoked_at)}</span>
              ) : (
                <Tooltip title={parseUtc(t.expires_at).toLocaleString()}>
                  <span className={t.status === 'expired' ? 'token-ended' : undefined}>{expiryText(t.expires_at)}</span>
                </Tooltip>
              )}
              <span>
                {t.last_used_at
                  ? <Tooltip title={parseUtc(t.last_used_at).toLocaleString()}><span>used {timeAgo(t.last_used_at)}</span></Tooltip>
                  : 'never used'}
              </span>
            </div>
            <ul className="token-scope-list" aria-label="Scopes">
              {t.scopes.map((s) => (
                <li key={s}><code>{s}</code> {SCOPE_LABEL[s] ?? ''}</li>
              ))}
            </ul>
          </div>
          {onRevoke && (
            <Popconfirm
              title="Revoke this token?"
              description="Anything still using it gets 401 from now on."
              okText="Revoke"
              okButtonProps={{ danger: true, loading: revoking }}
              cancelText="Cancel"
              onConfirm={() => onRevoke(t)}
            >
              <Button danger className="token-revoke" aria-label={`Revoke ${t.name}`}>Revoke</Button>
            </Popconfirm>
          )}
        </li>
      ))}
    </ul>
  )
}

function errorText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg
  return fallback
}
