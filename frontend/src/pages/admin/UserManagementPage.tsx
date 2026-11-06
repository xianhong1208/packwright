import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Input, Select, message, Empty, Modal, Button, Tooltip, Popconfirm, Pagination, Spin } from 'antd'
import { ArrowsClockwiseIcon, CheckIcon, CrownIcon, KeyIcon, MagnifyingGlassIcon, ProhibitIcon } from '../../components/ui/icons'
import { userApi } from '../../api/userApi'
import type { UserListItem, Role } from '../../api/types'
import { useAuth } from '../../contexts/AuthContext'
import PageHeader from '../../components/layout/PageHeader'
import { parseUtc, timeAgo } from '../../utils/time'
import { standing } from './standing'

const PAGE_SIZE = 20

type StatusFilter = 'all' | 'active' | 'inactive'

function Initial({ name, admin }: { name: string; admin: boolean }) {
  return (
    <span className="user-initial" data-admin={admin || undefined} aria-hidden="true">
      {name.slice(0, 1).toUpperCase()}
    </span>
  )
}

export default function UserManagementPage() {
  const { hasPermission, user: me } = useAuth()
  const canManage = hasPermission('user:manage')
  const canReset = hasPermission('user:reset_password')

  const [users, setUsers] = useState<UserListItem[]>([])
  const [waiting, setWaiting] = useState<UserListItem[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [counts, setCounts] = useState<Record<StatusFilter, number>>({ all: 0, active: 0, inactive: 0 })
  const [isLoading, setIsLoading] = useState(false)

  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [filterRole, setFilterRole] = useState<number | undefined>(undefined)
  const [page, setPage] = useState(1)

  useEffect(() => {
    userApi.getRoles().then(setRoles).catch(() => { /* roles only label the list */ })
  }, [])

  const loadUsers = useCallback(async () => {
    setIsLoading(true)
    const common = { search: search || undefined, role_id: filterRole }
    const isActive = status === 'all' ? undefined : status === 'active'
    try {
      const [list, all, active, inactive, notActive] = await Promise.all([
        userApi.getUsers({ ...common, is_active: isActive, skip: (page - 1) * PAGE_SIZE, limit: PAGE_SIZE }),
        userApi.getUsersCount(common),
        userApi.getUsersCount({ ...common, is_active: true }),
        userApi.getUsersCount({ ...common, is_active: false }),
        userApi.getUsers({ is_active: false, limit: 100 }),
      ])
      setUsers(list)
      setCounts({ all: all.count, active: active.count, inactive: inactive.count })
      setWaiting(notActive.filter((u) => standing(u).key === 'waiting'))
    } catch {
      message.error('Could not load the users')
    } finally {
      setIsLoading(false)
    }
  }, [search, filterRole, status, page])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  const handleStatusChange = async (userId: number, isActive: boolean) => {
    try {
      await userApi.updateUserStatus(userId, isActive)
      message.success(isActive ? 'Activated' : 'Deactivated')
      void loadUsers()
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'Could not change the status')
    }
  }

  const handleRoleChange = async (userId: number, roleId: number) => {
    try {
      await userApi.updateUserRole(userId, roleId)
      message.success('Role changed')
      void loadUsers()
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'Could not change the role')
    }
  }

  const handleResetPassword = (userId: number, username: string) => {
    let newPassword = ''
    Modal.confirm({
      title: `Set a new password for ${username}`,
      content: (
        <div className="mt-4">
          <Input.Password
            placeholder="At least 6 characters"
            aria-label="New password"
            onChange={(e) => {
              newPassword = e.target.value
            }}
          />
        </div>
      ),
      okText: 'Set password',
      onOk: async () => {
        if (newPassword.length < 6) {
          message.error('The password needs at least 6 characters')
          throw new Error('Validation error')
        }
        await userApi.resetUserPassword(userId, newPassword)
        message.success('Password set')
      },
    })
  }

  const filter = (patch: () => void) => {
    patch()
    setPage(1)
  }

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Users"
        lead="Who can sign in, and with which role."
        actions={
          <Tooltip title="Reload">
            <Button aria-label="Reload users" icon={<ArrowsClockwiseIcon />} onClick={() => void loadUsers()} />
          </Tooltip>
        }
      />

      {canManage && waiting.length > 0 && (
        <section className="waiting-card" aria-labelledby="waiting-title">
          <h2 id="waiting-title" className="text-[17px] font-semibold m-0" style={{ color: 'var(--ink)' }}>
            {waiting.length === 1 ? '1 account is' : `${waiting.length} accounts are`} waiting to be let in
          </h2>
          <p className="m-0 mt-1 mb-3 text-sm" style={{ color: 'var(--ink-muted)' }}>
            New registrations cannot sign in until someone activates them.
          </p>
          <ul className="waiting-list">
            {waiting.map((u) => (
              <li key={u.id}>
                <Initial name={u.username} admin={false} />
                <div className="min-w-0 flex-1">
                  <Link to={`/admin/users/${u.id}`} className="build-name">{u.username}</Link>
                  <div className="build-meta">
                    {u.email && <span>{u.email}</span>}
                    <Tooltip title={parseUtc(u.created_at).toLocaleString()}><span>registered {timeAgo(u.created_at)}</span></Tooltip>
                  </div>
                </div>
                <Button type="primary" icon={<CheckIcon />} onClick={() => handleStatusChange(u.id, true)}>Activate</Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Input
          allowClear
          prefix={<MagnifyingGlassIcon />}
          placeholder="Search by name or email"
          aria-label="Search users"
          value={search}
          onChange={(e) => filter(() => setSearch(e.target.value))}
          className="!w-full sm:!w-72"
        />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Status">
          {([['all', 'All'], ['active', 'Active'], ['inactive', 'Not active']] as const).map(([key, label]) => (
            <button key={key} type="button" className="chip" aria-pressed={status === key} onClick={() => filter(() => setStatus(key))}>
              {label} <span className="chip-count">{counts[key]}</span>
            </button>
          ))}
        </div>
        <Select
          allowClear
          placeholder="Any role"
          aria-label="Role"
          value={filterRole}
          onChange={(value) => filter(() => setFilterRole(value))}
          style={{ width: 160 }}
          className="sm:ml-auto"
          options={roles.map((role) => ({ value: role.id, label: role.display_name }))}
        />
      </div>

      {isLoading && users.length === 0 ? (
        <div className="py-16 text-center"><Spin /></div>
      ) : users.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} className="py-10" description={<span style={{ color: 'var(--ink-muted)' }}>No one matches these filters.</span>} />
      ) : (
        <ul className="build-list" aria-label="Users">
          {users.map((u) => {
            const s = standing(u)
            const self = u.id === me?.id
            const admin = u.role?.name === 'admin'
            return (
              <li key={u.id} className="build-row user-row">
                <Initial name={u.username} admin={admin} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 min-w-0">
                    <Link to={`/admin/users/${u.id}`} className="build-name truncate">{u.username}</Link>
                    {self && <span className="text-xs" style={{ color: 'var(--ink-faint)' }}>you</span>}
                  </div>
                  <div className="build-meta">
                    <span>{u.email || 'No email'}</span>
                    <span>
                      {u.last_login
                        ? <Tooltip title={parseUtc(u.last_login).toLocaleString()}><span>signed in {timeAgo(u.last_login)}</span></Tooltip>
                        : 'never signed in'}
                    </span>
                  </div>
                </div>
                <div className="user-side">
                <div className="user-role">
                  {canManage && !self ? (
                    <Select
                      size="small"
                      value={u.role?.id}
                      onChange={(value) => handleRoleChange(u.id, value)}
                      style={{ width: 140 }}
                      aria-label={`Role of ${u.username}`}
                      options={roles.map((role) => ({ value: role.id, label: role.display_name }))}
                    />
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-sm" style={{ color: 'var(--ink-muted)' }}>
                      {admin && <CrownIcon style={{ color: 'var(--color-cyber-400)' }} />}
                      {u.role?.display_name ?? 'No role'}
                    </span>
                  )}
                </div>
                <span className="user-standing" style={{ color: s.color }}>{s.label}</span>
                </div>
                <div className="flex gap-1.5 flex-none">
                  {canReset && (
                    <Tooltip title="Set a new password">
                      <Button aria-label={`Set a new password for ${u.username}`} icon={<KeyIcon />} onClick={() => handleResetPassword(u.id, u.username)} />
                    </Tooltip>
                  )}
                  {canManage && !self && (u.is_active ? (
                    <Popconfirm
                      title={`Deactivate ${u.username}?`}
                      description="They are signed out and can't sign in until reactivated."
                      okText="Deactivate"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleStatusChange(u.id, false)}
                    >
                      <Tooltip title="Deactivate">
                        <Button aria-label={`Deactivate ${u.username}`} danger icon={<ProhibitIcon />} />
                      </Tooltip>
                    </Popconfirm>
                  ) : (
                    <Tooltip title="Activate">
                      <Button aria-label={`Activate ${u.username}`} icon={<CheckIcon />} onClick={() => handleStatusChange(u.id, true)} />
                    </Tooltip>
                  ))}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {counts[status] > PAGE_SIZE && (
        <div className="flex justify-end mt-4">
          <Pagination current={page} pageSize={PAGE_SIZE} total={counts[status]} onChange={setPage} showSizeChanger={false} />
        </div>
      )}
    </div>
  )
}
