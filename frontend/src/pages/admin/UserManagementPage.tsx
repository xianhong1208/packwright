import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Table, Tag, Input, Select, message, Empty, Modal, Button, Tooltip, Popconfirm } from 'antd'
import {
  UserOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ReloadOutlined,
  CrownOutlined,
  KeyOutlined,
  StopOutlined,
  CheckOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { userApi } from '../../api/userApi'
import type { UserListItem, Role } from '../../api/types'
import { useAuth } from '../../contexts/AuthContext'
import PageHeader from '../../components/layout/PageHeader'
import { parseUtc, timeAgo } from '../../utils/time'

export default function UserManagementPage() {
  const { hasPermission, user: me } = useAuth()

  const [users, setUsers] = useState<UserListItem[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)

  // Filters
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<boolean | undefined>(undefined)
  const [filterRole, setFilterRole] = useState<number | undefined>(undefined)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10)

  useEffect(() => {
    loadRoles()
  }, [])

  useEffect(() => {
    loadUsers()
  }, [search, filterStatus, filterRole, page])

  const loadRoles = async () => {
    try {
      const data = await userApi.getRoles()
      setRoles(data)
    } catch {
      // Ignore - roles are optional for display
    }
  }

  const loadUsers = async () => {
    setIsLoading(true)
    try {
      const [usersData, countData] = await Promise.all([
        userApi.getUsers({
          skip: (page - 1) * pageSize,
          limit: pageSize,
          search: search || undefined,
          is_active: filterStatus,
          role_id: filterRole,
        }),
        userApi.getUsersCount({
          search: search || undefined,
          is_active: filterStatus,
          role_id: filterRole,
        }),
      ])
      setUsers(usersData)
      setTotal(countData.count)
    } catch {
      message.error('Failed to load users')
    } finally {
      setIsLoading(false)
    }
  }

  const handleStatusChange = async (userId: number, isActive: boolean) => {
    try {
      await userApi.updateUserStatus(userId, isActive)
      message.success(`User ${isActive ? 'activated' : 'deactivated'}`)
      loadUsers()
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'Failed to update status')
    }
  }

  const handleRoleChange = async (userId: number, roleId: number) => {
    try {
      await userApi.updateUserRole(userId, roleId)
      message.success('Role updated')
      loadUsers()
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'Failed to update role')
    }
  }

  const handleResetPassword = (userId: number, username: string) => {
    let newPassword = ''

    Modal.confirm({
      title: `Reset password for ${username}?`,
      content: (
        <div className="mt-4">
          <p className="mb-2" style={{ color: 'var(--ink-muted)' }}>Enter a new password:</p>
          <Input.Password
            placeholder="New password (at least 6 characters)"
            onChange={(e) => {
              newPassword = e.target.value
            }}
          />
        </div>
      ),
      okText: 'Reset password',
      onOk: async () => {
        if (newPassword.length < 6) {
          message.error('Password must be at least 6 characters')
          throw new Error('Validation error')
        }
        await userApi.resetUserPassword(userId, newPassword)
        message.success('Password reset successfully')
      },
    })
  }

  const columns: ColumnsType<UserListItem> = [
    {
      title: 'User',
      key: 'user',
      render: (_, record) => (
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center"
            style={{ background: 'var(--color-void-700)' }}
          >
            <UserOutlined style={{ color: 'var(--ink-muted)' }} />
          </div>
          <div>
            <Link
              to={`/admin/users/${record.id}`}
              style={{ color: 'var(--ink)', fontWeight: 600 }}
              className="hover:!text-cyber-300 transition-colors"
            >
              {record.username}
            </Link>
            {record.email && (
              <p className="text-xs" style={{ color: 'var(--ink-faint)' }}>{record.email}</p>
            )}
          </div>
        </div>
      ),
    },
    {
      title: 'Role',
      key: 'role',
      render: (_, record) => {
        if (!hasPermission('user:manage')) {
          return record.role ? (
            <Tag color={record.role.name === 'admin' ? 'gold' : undefined}>
              {record.role.name === 'admin' && <CrownOutlined className="mr-1" />}
              {record.role.display_name}
            </Tag>
          ) : (
            <Tag>No role</Tag>
          )
        }

        return (
          <Select
            value={record.role?.id}
            onChange={(value) => handleRoleChange(record.id, value)}
            style={{ width: 120 }}
            size="small"
          >
            {roles.map((role) => (
              <Select.Option key={role.id} value={role.id}>
                {role.display_name}
              </Select.Option>
            ))}
          </Select>
        )
      },
    },
    {
      title: 'Status',
      key: 'status',
      render: (_, record) => (
        <Tag
          color={record.is_active ? 'green' : 'red'}
          icon={record.is_active ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        >
          {record.is_active ? 'Active' : 'Inactive'}
        </Tag>
      ),
    },
    {
      title: 'Last login',
      dataIndex: 'last_login',
      key: 'last_login',
      render: (time: string | null) =>
        time ? (
          <Tooltip title={parseUtc(time).toLocaleString()}><span>{timeAgo(time)}</span></Tooltip>
        ) : (
          <span style={{ color: 'var(--ink-faint)' }}>Never</span>
        ),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (time: string) => parseUtc(time).toLocaleDateString(),
    },
    {
      title: 'Actions',
      key: 'actions',
      align: 'right',
      render: (_, record) => (
        <div className="flex justify-end gap-1.5">
          {hasPermission('user:reset_password') && (
            <Tooltip title="Set a new password">
              <Button aria-label={`Set a new password for ${record.username}`} icon={<KeyOutlined />} onClick={() => handleResetPassword(record.id, record.username)} />
            </Tooltip>
          )}
          {hasPermission('user:manage') && record.id !== me?.id && (record.is_active ? (
            <Popconfirm
              title={`Deactivate ${record.username}?`}
              description="They are signed out and can't sign in until reactivated."
              okText="Deactivate"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleStatusChange(record.id, false)}
            >
              <Tooltip title="Deactivate">
                <Button aria-label={`Deactivate ${record.username}`} danger icon={<StopOutlined />} />
              </Tooltip>
            </Popconfirm>
          ) : (
            <Tooltip title="Activate">
              <Button aria-label={`Activate ${record.username}`} icon={<CheckOutlined />} onClick={() => handleStatusChange(record.id, true)} />
            </Tooltip>
          ))}
        </div>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title="People"
        lead="Who can sign in, and with which role. New accounts wait here to be activated."
        actions={
          <Tooltip title="Reload">
            <Button aria-label="Reload people" icon={<ReloadOutlined />} onClick={loadUsers} />
          </Tooltip>
        }
      />

      <div className="flex flex-wrap gap-3 mb-4">
        <Input
          placeholder="Search by name or email"
          aria-label="Search people"
          prefix={<SearchOutlined style={{ color: 'var(--ink-faint)' }} />}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
          className="!w-full sm:!w-72"
          allowClear
        />
        <Select
          placeholder="Any status"
          aria-label="Status"
          value={filterStatus}
          onChange={(value) => {
            setFilterStatus(value)
            setPage(1)
          }}
          style={{ width: 150 }}
          allowClear
          options={[{ value: true, label: 'Active' }, { value: false, label: 'Waiting or disabled' }]}
        />
        <Select
          placeholder="Any role"
          aria-label="Role"
          value={filterRole}
          onChange={(value) => {
            setFilterRole(value)
            setPage(1)
          }}
          style={{ width: 150 }}
          allowClear
          options={roles.map((role) => ({ value: role.id, label: role.display_name }))}
        />
      </div>

      {/* Users table */}
      <Table
        scroll={{ x: 760 }}
        dataSource={users}
        columns={columns}
        rowKey="id"
        loading={{
          spinning: isLoading,
          indicator: <LoadingOutlined className="text-cyber-400" />,
        }}
        pagination={{
          current: page,
          total: total,
          pageSize: pageSize,
          onChange: setPage,
          showSizeChanger: false,
          showTotal: (total) => `${total} ${total === 1 ? 'user' : 'users'}`,
        }}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No one matches these filters" />,
        }}
      />
    </div>
  )
}
