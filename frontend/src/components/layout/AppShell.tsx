import { Suspense, useEffect, useMemo, useState, type ComponentType } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Button, Drawer, Dropdown, Input, Modal, Spin, Tooltip } from 'antd'
import { ClockCounterClockwiseIcon, ClockIcon, GaugeIcon, GearIcon, HouseIcon, KeyIcon, ListIcon, MagnifyingGlassIcon, PlusIcon, ShieldCheckIcon, SignOutIcon, UsersIcon } from '../ui/icons'
import type { IconProps } from '../ui/icons'
import Mark from '../ui/Mark'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../contexts/AuthContext'
import { useTaskStore } from '../../store/taskStore'
import { useIdleTimeout } from '../../hooks/useIdleTimeout'
import { taskApi } from '../../api/client'
import { STATUS_META } from '../../utils/statusMeta'

interface NavItem {
  path: string
  label: string
  Icon: ComponentType<IconProps>
  /** Any of these permissions shows the item; none listed = everyone. */
  permission?: string[]
  match?: (pathname: string) => boolean
}

const MAIN_NAV: NavItem[] = [
  { path: '/', label: 'On the bench', Icon: HouseIcon },
  { path: '/create', label: 'New build', Icon: PlusIcon },
  { path: '/history', label: 'Builds', Icon: ClockCounterClockwiseIcon, match: (p) => p.startsWith('/history') || p.startsWith('/task') },
  { path: '/monitor', label: 'Machine', Icon: GaugeIcon },
]
const ADMIN_NAV: NavItem[] = [
  { path: '/admin/users', label: 'People', Icon: UsersIcon, permission: ['user:view'], match: (p) => p.startsWith('/admin/users') },
  { path: '/admin/roles', label: 'Roles', Icon: ShieldCheckIcon, permission: ['role:view'] },
  { path: '/settings/git-credentials', label: 'Git credentials', Icon: KeyIcon, permission: ['user:manage'] },
]

const isActive = (item: NavItem, pathname: string) =>
  item.match ? item.match(pathname) : pathname === item.path

/**
 * The console frame: a narrow tool rail on the left (labels in tooltips), a top
 * bar with the quick-jump search and the one primary action, and the page.
 * Below the lg breakpoint the rail becomes a labelled drawer.
 */
export default function AppShell() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { user, logout, hasAnyPermission } = useAuth()
  const tasks = useTaskStore((s) => s.tasks)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const running = Array.from(tasks.values()).filter((t) => t.status === 'pending' || t.status === 'running').length

  const allowed = (item: NavItem) => !item.permission || hasAnyPermission(...item.permission)
  const adminNav = ADMIN_NAV.filter(allowed)

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }
  const { showWarning, remainingSeconds, resetTimer } = useIdleTimeout({ onLogout: handleLogout, enabled: true })

  // The version the *server* reports, so a stale frontend next to an upgraded
  // backend is visible instead of silently showing the old number.
  const { data: serverVersion } = useQuery({
    queryKey: ['serverVersion'],
    queryFn: async () => {
      const res = await fetch('/health')
      return res.ok ? ((await res.json()).version as string | undefined) ?? null : null
    },
    staleTime: Infinity,
  })

  // Ctrl/Cmd+K opens the quick jump from anywhere in the console.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const go = (path: string) => {
    navigate(path)
    setDrawerOpen(false)
    setPaletteOpen(false)
  }

  const railButton = (item: NavItem) => (
    <Tooltip key={item.path} title={item.label} placement="right">
      <button
        type="button"
        onClick={() => go(item.path)}
        aria-label={item.label}
        aria-current={isActive(item, pathname) ? 'page' : undefined}
        className={`rail-tool ${isActive(item, pathname) ? 'active' : ''}`}
      >
        <item.Icon weight={isActive(item, pathname) ? 'duotone' : 'regular'} />
        {item.path === '/' && running > 0 && <span className="rail-dot" aria-label={`${running} running`} />}
      </button>
    </Tooltip>
  )

  const drawerLink = (item: NavItem) => (
    <button
      key={item.path}
      type="button"
      onClick={() => go(item.path)}
      aria-current={isActive(item, pathname) ? 'page' : undefined}
      className={`nav-item w-full ${isActive(item, pathname) ? 'active' : ''}`}
    >
      <span className="text-lg"><item.Icon weight={isActive(item, pathname) ? 'duotone' : 'regular'} /></span>
      <span className="flex-1 text-left">{item.label}</span>
      {item.path === '/' && running > 0 && <span className="text-xs text-teal-400">{running} running</span>}
    </button>
  )

  const accountMenu = {
    items: [
      { key: 'who', label: <span className="text-[var(--ink-muted)]">{user?.username}, {user?.role?.display_name ?? 'User'}</span>, disabled: true },
      { type: 'divider' as const },
      { key: 'security', icon: <GearIcon />, label: 'Security', onClick: () => go('/settings/security') },
      { key: 'logout', icon: <SignOutIcon />, label: 'Sign out', danger: true, onClick: handleLogout },
    ],
  }

  return (
    <div className="min-h-screen flex">
      {/* Tool rail (desktop) */}
      <nav className="app-rail hidden lg:flex" aria-label="Main">
        <Tooltip title={serverVersion ? `Packwright ${serverVersion}` : 'Packwright'} placement="right">
          <button type="button" className="rail-logo" onClick={() => go('/')} aria-label="Packwright home">
            <Mark size={24} />
          </button>
        </Tooltip>
        {MAIN_NAV.map(railButton)}
        {adminNav.length > 0 && <span className="rail-sep" aria-hidden="true" />}
        {adminNav.map(railButton)}
        <span className="flex-1" />
        <Dropdown menu={accountMenu} placement="topLeft" trigger={['click']}>
          <button type="button" className="rail-avatar" aria-label={`Account: ${user?.username ?? ''}`}>
            {user?.username?.charAt(0).toUpperCase()}
          </button>
        </Dropdown>
      </nav>

      <div className="flex-1 min-w-0 flex flex-col">
        {/* Top bar */}
        <header className="app-topbar">
          <button type="button" className="lg:hidden rail-tool" onClick={() => setDrawerOpen(true)} aria-label="Open navigation">
            <ListIcon />
          </button>
          <button type="button" className="quick-jump" onClick={() => setPaletteOpen(true)}>
            <MagnifyingGlassIcon />
            <span className="flex-1 text-left truncate">Find a build or a page</span>
            <kbd className="hidden sm:inline">Ctrl K</kbd>
          </button>
          <Button type="primary" icon={<PlusIcon />} onClick={() => go('/create')}>
            <span className="hidden sm:inline">New build</span>
          </Button>
        </header>

        <main className="flex-1 overflow-auto px-4 sm:px-8 pt-6 pb-12">
          <div className="mx-auto w-full max-w-[1400px]">
            <Suspense fallback={<div className="min-h-[60vh] flex items-center justify-center"><Spin size="large" /></div>}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>

      {/* Navigation drawer (phone / narrow): the rail with its labels */}
      <Drawer
        placement="left"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={264}
        title="Packwright"
        rootClassName="lg:hidden"
      >
        <div className="space-y-1">{MAIN_NAV.map(drawerLink)}</div>
        {adminNav.length > 0 && <div className="mt-4 pt-4 border-t border-[var(--seam)] space-y-1">{adminNav.map(drawerLink)}</div>}
        <div className="mt-4 pt-4 border-t border-[var(--seam)] space-y-1">
          {drawerLink({ path: '/settings/security', label: 'Security', Icon: GearIcon, match: (p) => p === '/settings/security' })}
          <button type="button" onClick={handleLogout} className="nav-item w-full text-alert-400">
            <span className="text-lg"><SignOutIcon /></span>
            <span className="flex-1 text-left">Sign out {user?.username}</span>
          </button>
        </div>
      </Drawer>

      <QuickJump open={paletteOpen} onClose={() => setPaletteOpen(false)} onGo={go} pages={[...MAIN_NAV, ...adminNav]} />

      {/* Idle timeout warning */}
      <Modal
        open={showWarning}
        title={<span className="flex items-center gap-2"><ClockIcon className="text-signal-400" />You are about to be signed out</span>}
        okText="Stay signed in"
        cancelText="Sign out now"
        onOk={resetTimer}
        onCancel={handleLogout}
        closable={false}
        maskClosable={false}
      >
        <div className="py-4 text-center">
          <div className={`text-4xl font-mono font-bold mb-3 ${remainingSeconds <= 60 ? 'text-alert-400' : 'text-signal-400'}`}>
            {Math.floor(remainingSeconds / 60)}:{(remainingSeconds % 60).toString().padStart(2, '0')}
          </div>
          <p style={{ color: 'var(--ink-muted)' }}>You have been inactive, so this session will end for security.</p>
        </div>
      </Modal>
    </div>
  )
}

/** Ctrl+K: jump to a page or one of the recent builds by typing part of its name. */
function QuickJump({
  open,
  onClose,
  onGo,
  pages,
}: {
  open: boolean
  onClose: () => void
  onGo: (path: string) => void
  pages: NavItem[]
}) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const { data: builds = [] } = useQuery({
    queryKey: ['quickJumpBuilds'],
    queryFn: () => taskApi.getHistory({ limit: 50 }),
    enabled: open,
    staleTime: 30_000,
  })

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const pageHits = pages
      .filter((p) => !q || p.label.toLowerCase().includes(q))
      .map((p) => ({ key: `page:${p.path}`, path: p.path, title: p.label, hint: 'Page', icon: <p.Icon /> }))
    const seen = new Set<string>()
    const buildHits = builds
      .filter((b) => (!q || b.project_name.toLowerCase().includes(q)) && !seen.has(b.project_name) && seen.add(b.project_name))
      .slice(0, 8)
      .map((b) => ({
        key: `build:${b.task_id}`,
        path: `/history/${b.task_id}`,
        title: b.project_name,
        hint: STATUS_META[b.status]?.label ?? b.status,
        icon: STATUS_META[b.status]?.icon,
      }))
    return [...pageHits, ...buildHits]
  }, [query, builds, pages])

  const close = () => {
    setQuery('')
    setCursor(0)
    onClose()
  }

  return (
    <Modal open={open} onCancel={close} footer={null} closable={false} width={560} destroyOnHidden title={null}>
      <Input
        autoFocus
        size="large"
        prefix={<MagnifyingGlassIcon />}
        placeholder="Type a build or page name"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setCursor(0)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, results.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
          if (e.key === 'Enter' && results[cursor]) { onGo(results[cursor].path); close() }
        }}
        aria-label="Find a build or a page"
      />
      <ul className="mt-3 max-h-[50vh] overflow-auto" role="listbox" aria-label="Results">
        {results.length === 0 && <li className="px-3 py-6 text-center" style={{ color: 'var(--ink-faint)' }}>Nothing matches “{query}”</li>}
        {results.map((r, i) => (
          <li key={r.key} role="option" aria-selected={i === cursor}>
            <button
              type="button"
              onMouseEnter={() => setCursor(i)}
              onClick={() => { onGo(r.path); close() }}
              className={`quick-jump-row ${i === cursor ? 'active' : ''}`}
            >
              <span className="text-base">{r.icon}</span>
              <span className="flex-1 text-left truncate">{r.title}</span>
              <span className="text-xs" style={{ color: 'var(--ink-faint)' }}>{r.hint}</span>
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  )
}
