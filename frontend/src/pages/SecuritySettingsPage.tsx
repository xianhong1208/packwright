import { useState, useEffect } from 'react'
import { Button, message, Modal, Table, Tag, Empty, Popconfirm, Tooltip } from 'antd'
import { CheckCircleIcon, ClockCounterClockwiseIcon, DesktopIcon, DeviceMobileIcon, DeviceTabletIcon, LockIcon, QuestionIcon, SpinnerIcon, TrashIcon, WarningCircleIcon, XCircleIcon } from '../components/ui/icons'
import { authApi } from '../api/authApi'
import type { LoginHistoryItem, Session } from '../api/types'
import { useAuth } from '../contexts/AuthContext'
import { describeDevice } from '../utils/device'
import { parseUtc, timeAgo } from '../utils/time'
import PageHeader from '../components/layout/PageHeader'

/** Sessions listed before "Show all": every sign-in (scripts too) leaves one. */
const SESSIONS_SHOWN = 5

// A grouped settings panel: a titled header row with an icon and optional
// description, then the section body. Keeps every section visually consistent.
/** Sign-ins shown per page; the newest few are what anyone checks. */
const HISTORY_PAGE = 5

function SectionCard({
  icon,
  title,
  description,
  children,
}: {
  icon: React.ReactNode
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <section className="glass-card p-6">
      <div className="flex items-start gap-3 pb-4 mb-5 border-b border-[var(--seam)]">
        <span className="mt-0.5 text-lg text-cyber-400">{icon}</span>
        <div>
          <h2 className="text-lg font-semibold text-[var(--ink)]" style={{ fontFamily: 'var(--font-display)' }}>
            {title}
          </h2>
          {description && <p className="mt-0.5 text-sm text-[var(--ink-muted)]">{description}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

export default function SecuritySettingsPage() {
  const { user, logoutAllDevices } = useAuth()

  // Change Password State
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isChangingPassword, setIsChangingPassword] = useState(false)

  // Security Question State
  const [securityQuestion, setSecurityQuestion] = useState('')
  const [securityAnswer, setSecurityAnswer] = useState('')
  const [isSettingQuestion, setIsSettingQuestion] = useState(false)

  // Login History State
  const [loginHistory, setLoginHistory] = useState<LoginHistoryItem[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)

  // Active Sessions State
  const [sessions, setSessions] = useState<Session[]>([])
  const [showAllSessions, setShowAllSessions] = useState(false)
  const orderedSessions = [...sessions].sort(
    (a, b) => Number(b.is_current) - Number(a.is_current) || Date.parse(b.created_at) - Date.parse(a.created_at),
  )
  const visibleSessions = showAllSessions ? orderedSessions : orderedSessions.slice(0, SESSIONS_SHOWN)
  const [isLoadingSessions, setIsLoadingSessions] = useState(false)

  useEffect(() => {
    loadLoginHistory()
    loadSessions()
  }, [])

  const loadLoginHistory = async (page = 1) => {
    setIsLoadingHistory(true)
    try {
      const limit = HISTORY_PAGE
      const offset = (page - 1) * limit
      const data = await authApi.getLoginHistory(limit, offset)
      setLoginHistory(data.items)
      setHistoryTotal(data.total)
      setHistoryPage(page)
    } catch {
      message.error('Could not load your login history.')
    } finally {
      setIsLoadingHistory(false)
    }
  }

  const loadSessions = async () => {
    setIsLoadingSessions(true)
    try {
      const data = await authApi.getActiveSessions()
      setSessions(data.sessions)
    } catch {
      message.error('Could not load your active sessions.')
    } finally {
      setIsLoadingSessions(false)
    }
  }

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()

    if (newPassword.length < 6) {
      message.error('Your new password must be at least 6 characters.')
      return
    }

    if (newPassword !== confirmPassword) {
      message.error('The passwords do not match. Re-enter them.')
      return
    }

    setIsChangingPassword(true)
    try {
      await authApi.changePassword(currentPassword, newPassword)
      message.success('Your password has been changed.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'Could not change your password.')
    } finally {
      setIsChangingPassword(false)
    }
  }

  const handleSetSecurityQuestion = async (e: React.FormEvent) => {
    e.preventDefault()

    if (securityQuestion.length < 10) {
      message.error('Your security question must be at least 10 characters.')
      return
    }

    if (!securityAnswer.trim()) {
      message.error('Enter an answer.')
      return
    }

    setIsSettingQuestion(true)
    try {
      await authApi.setSecurityQuestion({
        question: securityQuestion,
        answer: securityAnswer,
      })
      message.success('Your security question has been saved.')
      setSecurityQuestion('')
      setSecurityAnswer('')
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'Could not save your security question.')
    } finally {
      setIsSettingQuestion(false)
    }
  }

  const handleRevokeSession = async (sessionId: number) => {
    try {
      await authApi.revokeSession(sessionId)
      message.success('Session revoked.')
      loadSessions()
    } catch {
      message.error('Could not revoke the session.')
    }
  }

  const handleLogoutAllDevices = () => {
    Modal.confirm({
      title: 'Sign out of all devices?',
      icon: <WarningCircleIcon />,
      content: 'This revokes every active session, including this one, and you will need to sign in again.',
      okText: 'Sign out all',
      okType: 'danger',
      onOk: async () => {
        await logoutAllDevices()
        window.location.href = '/login'
      },
    })
  }

  const getDeviceIcon = (deviceType: string | null | undefined) => {
    switch (deviceType) {
      case 'mobile':
        return <DeviceMobileIcon />
      case 'tablet':
        return <DeviceTabletIcon />
      default:
        return <DesktopIcon />
    }
  }

  const historyColumns = [
    {
      title: 'Time',
      dataIndex: 'login_time',
      key: 'login_time',
      render: (time: string) => (
        <Tooltip title={parseUtc(time).toLocaleString()}><span>{timeAgo(time)}</span></Tooltip>
      ),
    },
    {
      title: 'Result',
      dataIndex: 'success',
      key: 'success',
      render: (success: boolean) =>
        success ? (
          <Tag color="green" icon={<CheckCircleIcon />}>
            Signed in
          </Tag>
        ) : (
          <Tag color="red" icon={<XCircleIcon />}>
            Failed
          </Tag>
        ),
    },
    {
      title: 'Device',
      key: 'device',
      render: (_: unknown, record: LoginHistoryItem) => (
        <span className="flex items-center gap-2">
          {getDeviceIcon(record.device_type)}
          <span>{record.browser && record.browser !== 'Unknown' ? `${record.browser}${record.os && record.os !== 'Unknown' ? ` on ${record.os}` : ''}` : 'Script or unknown client'}</span>
        </span>
      ),
    },
    {
      title: 'Address',
      dataIndex: 'ip_address',
      key: 'ip_address',
      render: (ip: string | null) => ip || '-',
    },
  ]

  return (
    <div className="max-w-5xl">
      <PageHeader title="Security" lead="Your password, and every place you're signed in." />

      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-2 items-start">
        {/* Change password */}
        <SectionCard icon={<LockIcon />} title="Change password">
          <form onSubmit={handleChangePassword} className="max-w-md space-y-4">
            <div>
              <label htmlFor="security-current-password" className="block text-sm text-[var(--ink-muted)] mb-2">Current password</label>
              <input
                id="security-current-password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="input-field"
                placeholder="Enter your current password"
                autoComplete="current-password"
              />
            </div>
            <div>
              <label htmlFor="security-new-password" className="block text-sm text-[var(--ink-muted)] mb-2">New password</label>
              <input
                id="security-new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="input-field"
                placeholder="Enter a new password (at least 6 characters)"
                autoComplete="new-password"
              />
            </div>
            <div>
              <label htmlFor="security-confirm-password" className="block text-sm text-[var(--ink-muted)] mb-2">Confirm new password</label>
              <input
                id="security-confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="input-field"
                placeholder="Re-enter your new password"
                autoComplete="new-password"
              />
            </div>
            <button
              type="submit"
              disabled={isChangingPassword}
              className="btn-cyber flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-300"
            >
              {isChangingPassword && <SpinnerIcon />}
              Change password
            </button>
          </form>
        </SectionCard>

        {/* Security question */}
        <SectionCard
          icon={<QuestionIcon />}
          title="Security question"
          description="Used to verify your identity when you reset your password."
        >
          <div className="max-w-md space-y-4">
            {user?.has_security_question && (
              <div className="p-3 rounded-lg bg-matrix-500/10 border border-matrix-500/30 text-matrix-400 text-sm">
                <CheckCircleIcon className="mr-2" />
                You have a security question set. You can update it below.
              </div>
            )}
            <form onSubmit={handleSetSecurityQuestion} className="space-y-4">
              <div>
                <label htmlFor="security-question" className="block text-sm text-[var(--ink-muted)] mb-2">Security question</label>
                <input
                  id="security-question"
                  type="text"
                  value={securityQuestion}
                  onChange={(e) => setSecurityQuestion(e.target.value)}
                  className="input-field"
                  placeholder="e.g. What was the name of your first pet?"
                />
                <p className="text-xs text-[var(--ink-faint)] mt-1">
                  This question is used to verify your identity when you reset your password.
                </p>
              </div>
              <div>
                <label htmlFor="security-answer" className="block text-sm text-[var(--ink-muted)] mb-2">Answer</label>
                <input
                  id="security-answer"
                  type="text"
                  value={securityAnswer}
                  onChange={(e) => setSecurityAnswer(e.target.value)}
                  className="input-field"
                  placeholder="Enter your answer"
                />
                <p className="text-xs text-[var(--ink-faint)] mt-1">
                  Answers are case-insensitive, and leading and trailing spaces are ignored.
                </p>
              </div>
              <button
                type="submit"
                disabled={isSettingQuestion}
                className="btn-cyber flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-300"
              >
                {isSettingQuestion && <SpinnerIcon />}
                {user?.has_security_question ? 'Update security question' : 'Set security question'}
              </button>
            </form>
          </div>
        </SectionCard>

        </div>

        {/* Active sessions */}
        <SectionCard
          icon={<DesktopIcon />}
          title="Active sessions"
          description="Manage the sessions signed in across your devices."
        >
          <div className="space-y-4">
            <div className="flex justify-end">
              <button
                onClick={handleLogoutAllDevices}
                className="text-alert-400 hover:text-alert-500 text-sm transition-colors rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-alert-500/60"
              >
                Sign out of all devices
              </button>
            </div>

            {isLoadingSessions ? (
              <div className="flex justify-center py-8">
                <SpinnerIcon className="text-2xl text-cyber-400" />
              </div>
            ) : sessions.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No active sessions" />
            ) : (
              <>
                <ul className="session-list" aria-label="Signed-in sessions">
                  {visibleSessions.map((session) => (
                    <li key={session.id} className={`session-row ${session.is_current ? 'current' : ''}`}>
                      <DesktopIcon className="text-lg flex-none" style={{ color: 'var(--ink-faint)' }} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold" style={{ color: 'var(--ink)' }} title={session.device_info ?? undefined}>
                            {describeDevice(session.device_info)}
                          </span>
                          {session.is_current && <Tag color="green">This device</Tag>}
                          {session.is_remember_me && <Tag>Remembered</Tag>}
                        </div>
                        <div className="text-sm" style={{ color: 'var(--ink-faint)' }}>
                          {session.ip_address || 'Unknown address'}, signed in {timeAgo(session.created_at)}, expires {parseUtc(session.expires_at).toLocaleDateString()}
                        </div>
                      </div>
                      {!session.is_current && (
                        <Popconfirm
                          title="Sign this session out?"
                          description="That device will have to sign in again."
                          onConfirm={() => handleRevokeSession(session.id)}
                          okText="Sign out"
                          cancelText="Cancel"
                        >
                          <Button size="small" aria-label={`Sign out ${describeDevice(session.device_info)}`} icon={<TrashIcon />} />
                        </Popconfirm>
                      )}
                    </li>
                  ))}
                </ul>
                {sessions.length > SESSIONS_SHOWN && (
                  <button type="button" className="text-sm mt-1" style={{ color: 'var(--color-cyber-400)' }} onClick={() => setShowAllSessions((v) => !v)}>
                    {showAllSessions ? 'Show fewer' : `Show all ${sessions.length} sessions`}
                  </button>
                )}
              </>
            )}
          </div>
        </SectionCard>

        {/* Login history */}
        <SectionCard icon={<ClockCounterClockwiseIcon />} title="Login history">
          <Table
            dataSource={loginHistory}
            columns={historyColumns}
            rowKey="id"
            loading={isLoadingHistory}
            pagination={{
              current: historyPage,
              total: historyTotal,
              pageSize: HISTORY_PAGE,
              onChange: (page) => loadLoginHistory(page),
              showSizeChanger: false,
            }}
            locale={{
              emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No login history yet" />,
            }}
          />
        </SectionCard>
      </div>
    </div>
  )
}
