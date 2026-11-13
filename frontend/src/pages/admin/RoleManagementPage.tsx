import { useState, useEffect, useCallback } from 'react'
import { Button, Modal, Form, Input, Select, Checkbox, message, Empty, Tooltip, Spin } from 'antd'
import { ArrowsClockwiseIcon, LockIcon, PencilSimpleIcon, PlusIcon, ShieldCheckIcon, TrashIcon, UsersIcon } from '../../components/ui/icons'
import { userApi } from '../../api/userApi'
import type { Role, RoleCreate, RoleUpdate, PermissionCategory } from '../../api/types'
import { useAuth } from '../../contexts/AuthContext'
import PageHeader from '../../components/layout/PageHeader'

export default function RoleManagementPage() {
  const { hasPermission } = useAuth()
  const canManage = hasPermission('role:manage')

  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<PermissionCategory[]>([])
  const [isLoading, setIsLoading] = useState(false)
  // Users per role; only for someone who may list users.
  const [memberCounts, setMemberCounts] = useState<Record<number, number>>({})
  const canSeeUsers = hasPermission('user:view')

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [form] = Form.useForm()


  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [rolesData, permsData] = await Promise.all([
        userApi.getRoles(),
        userApi.getPermissions(),
      ])
      setRoles(rolesData)
      setPermissions(permsData)
      if (canSeeUsers) {
        const counts = await Promise.all(rolesData.map((r) => userApi.getUsersCount({ role_id: r.id }).then((c) => [r.id, c.count] as const)))
        setMemberCounts(Object.fromEntries(counts))
      }
    } catch {
      message.error('Failed to load data')
    } finally {
      setIsLoading(false)
    }
  }, [canSeeUsers])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleCreate = () => {
    setEditingRole(null)
    form.resetFields()
    setIsModalOpen(true)
  }

  const handleEdit = (role: Role) => {
    setEditingRole(role)
    form.setFieldsValue({
      name: role.name,
      display_name: role.display_name,
      description: role.description,
      parent_role_id: role.parent_role_id || undefined,
      permission_codes: role.permissions.map(p => p.code),
    })
    setIsModalOpen(true)
  }

  const handleDelete = (role: Role) => {
    Modal.confirm({
      title: `Delete role "${role.display_name}"?`,
      content: 'This action cannot be undone. Users with this role will need to be reassigned.',
      okText: 'Delete',
      okButtonProps: { danger: true },
      className: 'dark-modal',
      onOk: async () => {
        try {
          await userApi.deleteRole(role.id)
          message.success('Role deleted')
          loadData()
        } catch (err) {
          message.error(err instanceof Error ? err.message : 'Failed to delete role')
        }
      },
    })
  }

  const handleSubmit = async (values: {
    name: string
    display_name: string
    description?: string
    parent_role_id?: number
    permission_codes: string[]
  }) => {
    try {
      if (editingRole) {
        const updateData: RoleUpdate = {
          display_name: values.display_name,
          description: values.description,
          // Always sent: null removes the parent (a cleared Select gives undefined),
          // while leaving the field out would keep it.
          parent_role_id: values.parent_role_id ?? null,
          permission_codes: values.permission_codes,
        }
        await userApi.updateRole(editingRole.id, updateData)
        message.success('Role updated')
      } else {
        const createData: RoleCreate = {
          name: values.name,
          display_name: values.display_name,
          description: values.description,
          parent_role_id: values.parent_role_id,
          permission_codes: values.permission_codes || [],
        }
        await userApi.createRole(createData)
        message.success('Role created')
      }
      setIsModalOpen(false)
      loadData()
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'Operation failed')
    }
  }

  // Permission code → category, for grouping a role's permissions on its card.
  const categoryOf = new Map(permissions.flatMap((c) => c.permissions.map((p) => [p.code, c.category] as const)))
  const grouped = (role: Role) => {
    const groups = new Map<string, typeof role.permissions>()
    for (const p of role.permissions) {
      const cat = categoryOf.get(p.code) ?? p.category ?? 'Other'
      groups.set(cat, [...(groups.get(cat) ?? []), p])
    }
    return [...groups.entries()]
  }

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Roles"
        lead="What each role is allowed to do. A role can inherit another's permissions."
        actions={
          <>
            <Tooltip title="Reload">
              <Button aria-label="Reload roles" icon={<ArrowsClockwiseIcon />} onClick={loadData} />
            </Tooltip>
            {canManage && (
              <Button type="primary" icon={<PlusIcon />} onClick={handleCreate}>
                Add role
              </Button>
            )}
          </>
        }
      />

      {isLoading && roles.length === 0 ? (
        <div className="py-16 text-center"><Spin /></div>
      ) : roles.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span style={{ color: 'var(--ink-muted)' }}>No roles yet.</span>} />
      ) : (
        <div className="role-grid">
          {roles.map((role) => {
            const full = role.permissions.some((p) => p.code === '*:*')
            const parent = role.parent_role_id ? roles.find((r) => r.id === role.parent_role_id) : null
            const members = memberCounts[role.id]
            return (
              <article key={role.id} className="role-card" aria-labelledby={`role-${role.id}`}>
                <header className="role-head">
                  <span className="role-mark" data-system={role.is_system || undefined} aria-hidden="true">
                    {role.is_system ? <LockIcon /> : <UsersIcon />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 id={`role-${role.id}`} className="role-name">
                      {role.display_name}
                      {role.is_system && <span className="role-tag">Built in</span>}
                      {!role.is_active && <span className="role-tag" data-off>Disabled</span>}
                    </h2>
                    <code className="role-code">{role.name}</code>
                  </div>
                  {canManage && (
                    <div className="flex gap-1.5 flex-none">
                      <Tooltip title="Edit">
                        <Button aria-label={`Edit ${role.display_name}`} icon={<PencilSimpleIcon />} onClick={() => handleEdit(role)} />
                      </Tooltip>
                      {!role.is_system && (
                        <Tooltip title="Delete">
                          <Button aria-label={`Delete ${role.display_name}`} danger icon={<TrashIcon />} onClick={() => handleDelete(role)} />
                        </Tooltip>
                      )}
                    </div>
                  )}
                </header>

                {role.description && <p className="role-desc">{role.description}</p>}

                <div className="build-meta mb-3">
                  {members !== undefined && <span>{members === 1 ? '1 user' : `${members} users`}</span>}
                  {parent && <span>Inherits from {parent.display_name}</span>}
                  <span>{full ? 'Every permission' : `${role.permissions.length} ${role.permissions.length === 1 ? 'permission' : 'permissions'}`}</span>
                </div>

                {full ? (
                  <p className="role-full"><ShieldCheckIcon /> Can do everything, including managing users and roles.</p>
                ) : role.permissions.length === 0 ? (
                  <p className="role-desc m-0">No permissions of its own{parent ? `; it has what ${parent.display_name} has.` : '.'}</p>
                ) : (
                  <dl className="role-perms">
                    {grouped(role).map(([category, perms]) => (
                      <div key={category} className="role-perm-group">
                        <dt>{category.charAt(0).toUpperCase() + category.slice(1)}</dt>
                        <dd>
                          {perms.map((p) => (
                            <Tooltip key={p.code} title={p.code}>
                              <span className="role-perm">{p.name || p.code}</span>
                            </Tooltip>
                          ))}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </article>
            )
          })}
        </div>
      )}

      {/* Create/Edit Modal */}
      <Modal
        title={editingRole ? `Edit role: ${editingRole.display_name}` : 'Create role'}
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        width={700}
        className="dark-modal"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          className="mt-4"
        >
          <div className="grid grid-cols-2 gap-4">
            <Form.Item
              name="name"
              label="Role name (ID)"
              rules={[
                { required: true, message: 'Enter a role name' },
                { pattern: /^[a-z][a-z0-9_]*$/, message: 'Lowercase letters, numbers, and underscores only' },
              ]}
            >
              <Input
                placeholder="e.g. moderator"
                disabled={!!editingRole}
              />
            </Form.Item>

            <Form.Item
              name="display_name"
              label="Display name"
              rules={[{ required: true, message: 'Enter a display name' }]}
            >
              <Input placeholder="e.g. Moderator" />
            </Form.Item>
          </div>

          <Form.Item
            name="description"
            label="Description"
          >
            <Input.TextArea
              placeholder="Role description..."
              rows={2}
            />
          </Form.Item>

          <Form.Item
            name="parent_role_id"
            label="Parent role (inherits its permissions)"
          >
            <Select
              placeholder="No parent role"
              allowClear
              options={roles
                .filter(r => r.id !== editingRole?.id)
                .map(r => ({ value: r.id, label: r.display_name }))}
            />
          </Form.Item>

          <Form.Item
            name="permission_codes"
            label="Permissions"
          >
            <div className="max-h-64 overflow-y-auto rounded-lg p-4" style={{ border: '1px solid var(--color-void-700)' }}>
              {permissions.map(category => (
                <div key={category.category} className="mb-4">
                  <h4 className="text-sm font-medium mb-2 capitalize" style={{ color: 'var(--ink-muted)' }}>
                    {category.category}
                  </h4>
                  <Form.Item name="permission_codes" noStyle>
                    <Checkbox.Group className="flex flex-wrap gap-2">
                      {category.permissions.map(perm => (
                        <Checkbox key={perm.code} value={perm.code}>
                          <Tooltip title={perm.description}>
                            <span style={{ color: 'var(--ink-muted)' }}>{perm.name}</span>
                          </Tooltip>
                        </Checkbox>
                      ))}
                    </Checkbox.Group>
                  </Form.Item>
                </div>
              ))}
            </div>
          </Form.Item>

          <div className="flex justify-end gap-2 mt-6">
            <Button onClick={() => setIsModalOpen(false)}>
              Cancel
            </Button>
            <Button type="primary" htmlType="submit">
              {editingRole ? 'Update' : 'Create'}
            </Button>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
