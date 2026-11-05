import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App as AntApp,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { GithubLogoIcon, GitlabLogoIcon, HardDrivesIcon, PencilSimpleIcon, PlusIcon, TrashIcon } from '../../components/ui/icons'
import PageHeader from '../../components/layout/PageHeader'
import {
  gitCredentialsApi,
  type GitCredential,
  type GitProvider,
} from '../../api/gitCredentialsApi'
import { parseUtc } from '../../utils/time'

const { Text } = Typography

const PROVIDER_META: Record<GitProvider, { label: string; icon: React.ReactNode; defaultHost: string }> = {
  github: { label: 'GitHub', icon: <GithubLogoIcon />, defaultHost: 'github.com' },
  gitlab: { label: 'GitLab', icon: <GitlabLogoIcon />, defaultHost: 'gitlab.com' },
  generic: { label: 'Other (self-hosted)', icon: <HardDrivesIcon />, defaultHost: '' },
}

// Managing Git credentials replaces the old server-side GITLAB_TOKEN env var:
// tokens are entered here, stored encrypted, and picked automatically by the
// clone URL's host when a build runs.
export default function GitCredentialsPage() {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<GitCredential | null>(null)
  const [form] = Form.useForm()

  const { data: credentials = [], isLoading } = useQuery({
    queryKey: ['git-credentials'],
    queryFn: gitCredentialsApi.list,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['git-credentials'] })

  const createMutation = useMutation({
    mutationFn: gitCredentialsApi.create,
    onSuccess: () => {
      message.success('Credential added')
      setModalOpen(false)
      invalidate()
    },
    onError: (e: unknown) => message.error(errorText(e, 'Failed to add credential')),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: { label?: string; token?: string } }) =>
      gitCredentialsApi.update(id, payload),
    onSuccess: () => {
      message.success('Credential updated')
      setModalOpen(false)
      invalidate()
    },
    onError: (e: unknown) => message.error(errorText(e, 'Failed to update credential')),
  })

  const deleteMutation = useMutation({
    mutationFn: gitCredentialsApi.remove,
    onSuccess: () => {
      message.success('Credential deleted')
      invalidate()
    },
    onError: (e: unknown) => message.error(errorText(e, 'Failed to delete credential')),
  })

  const openCreate = () => {
    setEditing(null)
    setModalOpen(true)
  }

  const openEdit = (cred: GitCredential) => {
    setEditing(cred)
    setModalOpen(true)
  }

  // Populate the form only after the modal (and its Form) has mounted. Setting
  // fields straight from the click handler runs before the Form connects, so
  // the values are dropped and the fields render blank — the reason editing
  // showed an empty Provider. Running it in an effect keyed on `modalOpen`
  // guarantees the Form is mounted first.
  useEffect(() => {
    if (!modalOpen) return
    if (editing) {
      form.setFieldsValue({ label: editing.label ?? '', token: '' })
    } else {
      form.setFieldsValue({ provider: 'github', host: '', label: '', token: '' })
    }
  }, [modalOpen, editing, form])

  const handleSubmit = async () => {
    const values = await form.validateFields()
    if (editing) {
      // Only send fields that change; a blank token means "keep the current one".
      const payload: { label?: string; token?: string } = { label: values.label || null }
      if (values.token) payload.token = values.token
      updateMutation.mutate({ id: editing.id, payload })
    } else {
      createMutation.mutate({
        provider: values.provider,
        host: values.host?.trim() || null,
        label: values.label?.trim() || null,
        token: values.token,
      })
    }
  }

  const columns = [
    {
      title: 'Provider',
      dataIndex: 'provider',
      key: 'provider',
      render: (p: GitProvider) => <span className="inline-flex items-center gap-2">{PROVIDER_META[p].icon}{PROVIDER_META[p].label}</span>,
    },
    { title: 'Host', dataIndex: 'host', key: 'host', render: (h: string) => <Text code>{h}</Text> },
    {
      title: 'Label',
      dataIndex: 'label',
      key: 'label',
      render: (l: string | null) => l || <Text type="secondary">—</Text>,
    },
    {
      title: 'Token',
      dataIndex: 'token_hint',
      key: 'token_hint',
      render: (hint: string | null) => (
        <Text type="secondary">••••{hint ?? ''}</Text>
      ),
    },
    {
      title: 'Last used',
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      render: (v: string | null) =>
        v ? parseUtc(v).toLocaleString() : <Text type="secondary">Never</Text>,
    },
    {
      title: '',
      key: 'actions',
      width: 120,
      render: (_: unknown, cred: GitCredential) => (
        <Space size="small">
          <Tooltip title="Edit">
            <Button type="text" size="small" icon={<PencilSimpleIcon />} onClick={() => openEdit(cred)} />
          </Tooltip>
          <Popconfirm
            title="Delete this credential?"
            description="Builds cloning private repos from this host will fail to authenticate."
            okText="Delete"
            okButtonProps={{ danger: true, loading: deleteMutation.isPending }}
            cancelText="Cancel"
            onConfirm={() => deleteMutation.mutate(cred.id)}
          >
            <Button type="text" size="small" danger icon={<TrashIcon />} aria-label="Delete" />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Git credentials"
        lead="Tokens for cloning private repositories. A build uses the one whose host matches its Git URL."
        actions={
          <Button type="primary" icon={<PlusIcon />} onClick={openCreate}>
            Add credential
          </Button>
        }
      />

      <Table
        scroll={{ x: 760 }}
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={credentials}
        pagination={false}
        locale={{ emptyText: (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ color: 'var(--ink-muted)' }}>No credentials yet. Public repositories don't need one.</span>}
          >
            <Button icon={<PlusIcon />} onClick={openCreate}>Add credential</Button>
          </Empty>
        ) }}
      />

      <Modal
        title={editing ? 'Edit credential' : 'Add Git credential'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText={editing ? 'Save' : 'Add'}
        cancelText="Cancel"
        forceRender
      >
        <Form form={form} layout="vertical" className="mt-4">
          {editing ? (
            // Provider and host are the credential's identity (host is the lookup
            // key, provider sets the token-injection format), so they are fixed
            // once created — shown read-only rather than as disabled inputs.
            <div
              className="mb-5 rounded-lg px-4 py-3"
              style={{ background: 'var(--color-void-800)', border: '1px solid var(--seam)' }}
            >
              <div className="flex items-center justify-between">
                <Text type="secondary">Provider</Text>
                <Tag icon={PROVIDER_META[editing.provider].icon} style={{ marginInlineEnd: 0 }}>
                  {PROVIDER_META[editing.provider].label}
                </Tag>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <Text type="secondary">Host</Text>
                <Text code>{editing.host}</Text>
              </div>
            </div>
          ) : (
            <>
              <Form.Item name="provider" label="Provider" rules={[{ required: true }]}>
                <Select
                  onChange={(p: GitProvider) => {
                    // Prefill the cloud default; the user overrides it for a
                    // self-hosted host (e.g. gitlab.example.com).
                    form.setFieldValue('host', PROVIDER_META[p].defaultHost)
                  }}
                  options={(Object.keys(PROVIDER_META) as GitProvider[]).map((p) => ({
                    value: p,
                    label: PROVIDER_META[p].label,
                  }))}
                />
              </Form.Item>
              <Form.Item
                name="host"
                label="Host"
                tooltip="Hostname only — no https:// and no path. For a self-hosted GitLab or GitHub Enterprise, pick the matching provider and enter its hostname, e.g. gitlab.example.com"
                extra="Self-hosted GitLab / GitHub Enterprise: choose the matching provider so the token is injected in the right format, then enter the server hostname here."
                rules={[
                  {
                    validator: (_, value) => {
                      const provider = form.getFieldValue('provider')
                      if (provider === 'generic' && !value?.trim()) {
                        return Promise.reject(new Error('A host is required for self-hosted providers'))
                      }
                      return Promise.resolve()
                    },
                  },
                ]}
              >
                <Input placeholder="e.g. gitlab.example.com — or leave blank for github.com / gitlab.com" />
              </Form.Item>
            </>
          )}
          <Form.Item name="label" label="Label (optional)">
            <Input placeholder="e.g. Personal GitHub" maxLength={128} />
          </Form.Item>
          <Form.Item
            name="token"
            label={editing ? 'New token (leave blank to keep current)' : 'Access token'}
            rules={editing ? [] : [{ required: true, message: 'Enter a token' }]}
            extra="Stored encrypted. It can't be shown again, only replaced."
          >
            <Input.Password
              placeholder={editing ? 'Leave blank to keep the current token' : 'ghp_… or glpat-…'}
              autoComplete="off"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function errorText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}
