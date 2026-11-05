import { lazy, Suspense } from 'react'
import { ConfigProvider, Empty, Spin, App as AntApp, theme as antdTheme } from 'antd'
import enUS from 'antd/locale/en_US'
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Route-level code-splitting: lazy-load heavy page components so they are
// fetched on demand instead of shipping in the single initial JS chunk.
const Dashboard = lazy(() => import('./pages/Dashboard'))
const CreateTask = lazy(() => import('./pages/CreateTask'))
const History = lazy(() => import('./pages/History'))
const TaskDetail = lazy(() => import('./pages/TaskDetail'))
const HistoryDetail = lazy(() => import('./pages/HistoryDetail'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const ForgotPasswordPage = lazy(() => import('./pages/ForgotPasswordPage'))
const SecuritySettingsPage = lazy(() => import('./pages/SecuritySettingsPage'))
const UserManagementPage = lazy(() => import('./pages/admin/UserManagementPage'))
const UserDetailPage = lazy(() => import('./pages/admin/UserDetailPage'))
const RoleManagementPage = lazy(() => import('./pages/admin/RoleManagementPage'))
const GitCredentialsPage = lazy(() => import('./pages/admin/GitCredentialsPage'))
const MonitoringPage = lazy(() => import('./pages/MonitoringPage'))
import { useTaskStore } from './store/taskStore'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { SIGNED_OUT_EVENT } from './contexts/session'
import AppShell from './components/layout/AppShell'

/** 429 is the one status where retrying is guaranteed to make things worse.
 *
 * The limiter counts the retry too, so a client that retries on 429 pushes
 * itself further past the limit and stays there: every query on the page
 * fails, each one retries, and the window never gets a chance to drain. What
 * the user sees is an application that has stopped working rather than one
 * asking them to slow down. Everything else keeps its single retry.
 */
const isRateLimited = (error: unknown): boolean =>
  (error as { response?: { status?: number } })?.response?.status === 429

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => !isRateLimited(error) && failureCount < 1,
    },
    mutations: {
      retry: false,
    },
  },
})

// Sign-out must not leave the previous user's data on screen: the query cache
// (history, users, stats) and the task store would otherwise be shown to
// whoever signs in next in this tab.
window.addEventListener(SIGNED_OUT_EVENT, () => {
  queryClient.clear()
  useTaskStore.getState().setTasks([])
})

// Protected route wrapper
function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spin size="large" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

// Permission-protected route wrapper
function PermissionRoute({ permission, children }: { permission: string | string[]; children: React.ReactNode }) {
  const { hasAnyPermission } = useAuth()

  const permissions = Array.isArray(permission) ? permission : [permission]
  const hasAccess = hasAnyPermission(...permissions)

  if (!hasAccess) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* locale alongside theme: without it antd's built-in strings stay
          English while everything around them is Chinese — Tour's
          "Next"/"Finish", Table pagination, Select's "No Data", Modal's
          "OK"/"Cancel", Empty's "No data". Theme gets noticed during
          development because it is always visible; these only surface in
          particular component states, so they survive to production. */}
      <ConfigProvider
        locale={enUS}
        // antd's default empty picture is a light illustration that glares on the dark theme.
        renderEmpty={() => <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        theme={{
          // The console is dark. With antd's default (light) algorithm every
          // token not overridden below was derived for a white page: invisible
          // placeholders, white tags, near-black pagination arrows. The dark
          // algorithm derives those from the seeds below instead.
          algorithm: antdTheme.darkAlgorithm,
          token: {
            // Workbench theme: brass primary on warm graphite. Keep in step with
            // the CSS tokens in index.css (antd computes its colours in JS, so
            // it cannot read the CSS variables).
            colorPrimary: '#d4a72c',
            colorInfo: '#4fb3ad',
            colorSuccess: '#79b866',
            colorWarning: '#c9a96e',
            colorError: '#e0674f',
            colorLink: '#e0b94a',
            borderRadius: 10,
            fontFamily: "'Familjen Grotesk', system-ui, sans-serif",
            fontFamilyCode: "'Spline Sans Mono', monospace",
            colorBgContainer: '#262220',
            colorBgElevated: '#2f2a26',
            colorBgLayout: '#1d1a17',
            colorBgSpotlight: '#3d3631',
            colorText: '#efe8dc',
            colorTextSecondary: '#b8ad9d',
            colorTextTertiary: '#8f8577',
            colorTextPlaceholder: '#8f8577',
            colorBorder: '#4b433c',
            colorBorderSecondary: '#3d3631',
          },
          components: {
            Button: { primaryColor: '#1d1a17', fontWeight: 600 },
            Modal: { contentBg: '#2f2a26', headerBg: 'transparent', titleColor: '#efe8dc' },
            Form: { labelColor: '#b8ad9d' },
            Input: { colorBgContainer: '#1d1a17', colorBorder: '#3d3631' },
            InputNumber: { colorBgContainer: '#1d1a17', colorBorder: '#3d3631' },
            Select: { colorBgContainer: '#1d1a17', colorBorder: '#3d3631', optionSelectedBg: 'rgba(212, 167, 44, 0.18)' },
            Drawer: { colorBgElevated: '#262220' },
            Tooltip: { colorBgSpotlight: '#3d3631' },
          },
        }}
      >
        <AntApp component={false}>
          <AuthProvider>
          <BrowserRouter>
            <Suspense
              fallback={
                <div className="min-h-screen flex items-center justify-center">
                  <Spin size="large" />
                </div>
              }
            >
            <Routes>
              {/* Public routes */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />

              {/* Protected routes */}
              <Route element={<ProtectedRoute />}>
                <Route path="/" element={<AppShell />}>
                  <Route index element={<Dashboard />} />
                  <Route path="create" element={<CreateTask />} />
                  <Route path="history" element={<History />} />
                  <Route path="history/:taskId" element={<HistoryDetail />} />
                  <Route path="task/:taskId" element={<TaskDetail />} />
                  <Route path="settings/security" element={<SecuritySettingsPage />} />
                  <Route path="monitor" element={<MonitoringPage />} />

                  {/* Admin routes */}
                  <Route
                    path="admin/users"
                    element={
                      <PermissionRoute permission="user:view">
                        <UserManagementPage />
                      </PermissionRoute>
                    }
                  />
                  <Route
                    path="admin/users/:userId"
                    element={
                      <PermissionRoute permission="user:view">
                        <UserDetailPage />
                      </PermissionRoute>
                    }
                  />
                  <Route
                    path="admin/roles"
                    element={
                      <PermissionRoute permission="role:view">
                        <RoleManagementPage />
                      </PermissionRoute>
                    }
                  />
                  <Route
                    path="settings/git-credentials"
                    element={
                      <PermissionRoute permission="user:manage">
                        <GitCredentialsPage />
                      </PermissionRoute>
                    }
                  />
                </Route>
              </Route>
            </Routes>
            </Suspense>
          </BrowserRouter>
          </AuthProvider>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
