import type { ReactNode } from 'react'
import { AppstoreOutlined, CloudServerOutlined, DesktopOutlined } from '@ant-design/icons'
import type { ProjectType } from '../api/types'

/**
 * How each project type is named and coloured everywhere in the console. There
 * used to be four copies (task page, history list and detail, New build review)
 * with different labels, icons and colours — one of them a CSS keyword `blue`
 * (#0000ff), which is unreadable on the dark theme.
 */
export const PROJECT_TYPE_META: Record<ProjectType, { label: string; icon: ReactNode; tag: string; text: string }> = {
  // Neutral on purpose: colour is kept for status (running, passed, failed),
  // and a type label that competes with it only adds noise. The icon tells
  // the types apart.
  backend_only: { label: 'Backend', icon: <CloudServerOutlined />, tag: 'default', text: 'var(--ink-muted)' },
  frontend_only: { label: 'Frontend', icon: <DesktopOutlined />, tag: 'default', text: 'var(--ink-muted)' },
  fullstack: { label: 'Full stack', icon: <AppstoreOutlined />, tag: 'default', text: 'var(--ink-muted)' },
}
