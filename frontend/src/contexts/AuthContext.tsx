import { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import type { User, TokenResponse } from '../api/types'
import { refreshTokens, TOKENS_REFRESHED_EVENT } from '../api/client'
import { clearFormDraft } from '../hooks/useFormDraft'
import { SESSION_CHECK_MAX_WAIT, SIGNED_OUT_EVENT, isSessionRejected, retryAfterSeconds } from './session'

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  permissions: Set<string>
  login: (username: string, password: string, rememberMe?: boolean) => Promise<void>
  register: (username: string, password: string) => Promise<{ pendingApproval: boolean }>
  logout: () => Promise<void>
  logoutAllDevices: () => Promise<void>
  refreshToken: () => Promise<boolean>
  hasPermission: (code: string) => boolean
  hasAnyPermission: (...codes: string[]) => boolean
  error: string | null
  /** Set while the session check waits out a rate limit, for the loading screen. */
  notice: string | null
}

const AuthContext = createContext<AuthContextType | null>(null)

const API_BASE = '/auth'

// Token storage keys
const ACCESS_TOKEN_KEY = 'access_token'
const REFRESH_TOKEN_KEY = 'refresh_token'
const TOKEN_EXPIRY_KEY = 'token_expiry'

// Token management utilities
const tokenManager = {
  getAccessToken: () => sessionStorage.getItem(ACCESS_TOKEN_KEY) || localStorage.getItem(ACCESS_TOKEN_KEY),
  getRefreshToken: () =>
    sessionStorage.getItem(REFRESH_TOKEN_KEY) || localStorage.getItem(REFRESH_TOKEN_KEY),

  setTokens: (accessToken: string, refreshToken: string | null, expiresIn: number, rememberMe: boolean) => {
    const expiry = Date.now() + expiresIn * 1000

    // Both tokens honor rememberMe: without it, everything lives in
    // sessionStorage and dies with the browser session. A long-lived
    // refresh token left in localStorage would defeat "don't remember me".
    const storage = rememberMe ? localStorage : sessionStorage

    storage.setItem(ACCESS_TOKEN_KEY, accessToken)
    if (refreshToken) {
      storage.setItem(REFRESH_TOKEN_KEY, refreshToken)
    }
    storage.setItem(TOKEN_EXPIRY_KEY, expiry.toString())
  },

  clearTokens: () => {
    for (const storage of [localStorage, sessionStorage]) {
      storage.removeItem(ACCESS_TOKEN_KEY)
      storage.removeItem(REFRESH_TOKEN_KEY)
      storage.removeItem(TOKEN_EXPIRY_KEY)
    }
  },

  isTokenExpiring: () => {
    const expiry =
      sessionStorage.getItem(TOKEN_EXPIRY_KEY) || localStorage.getItem(TOKEN_EXPIRY_KEY)
    if (!expiry) return true
    // Consider token expiring if less than 2 minutes left
    return Date.now() > parseInt(expiry) - 2 * 60 * 1000
  },
}

// Export for use in API client
export { tokenManager }

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [permissions, setPermissions] = useState<Set<string>>(new Set())
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const refreshTimeoutRef = useRef<number | null>(null)

  // Schedule token refresh before expiry
  const scheduleTokenRefresh = useCallback((expiresIn: number) => {
    if (refreshTimeoutRef.current) {
      clearTimeout(refreshTimeoutRef.current)
    }

    // Refresh 2 minutes before expiry
    const refreshTime = Math.max((expiresIn - 120) * 1000, 10000)

    refreshTimeoutRef.current = window.setTimeout(async () => {
      if (tokenManager.getRefreshToken()) {
        await refreshTokenInternal()
      }
    }, refreshTime)
  }, [])

  // Rotation happens in api/client's refreshTokens, which is shared with the
  // 401 interceptor. This used to be a second implementation with its own
  // in-progress flag: the backend revokes the refresh token it is handed, so
  // whichever of the two finished second presented a token that had just been
  // revoked, took a 401, and logged the user out while their new token sat in
  // storage. Storage writes and the expiry timer are handled there and by the
  // TOKENS_REFRESHED_EVENT listener below; all that is left here is what the
  // provider itself owns — the user state when the session is really gone.
  const refreshTokenInternal = async (): Promise<boolean> => {
    if (!tokenManager.getRefreshToken()) return false

    try {
      await refreshTokens()
      return true
    } catch (err) {
      // Only a rejected token ends the session. A network error or a 5xx (the
      // backend restarting) used to clear the tokens too, so reloading during
      // a deploy destroyed every remember-me session.
      if (isSessionRejected(err)) {
        tokenManager.clearTokens()
        setUser(null)
        setPermissions(new Set())
      } else {
        setError('Cannot reach the server. Your session is kept; reload once it is back.')
      }
      return false
    }
  }

  // A refresh started by the 401 interceptor moves the expiry, and the timer
  // was armed against the old one. Re-arming here is what keeps a single
  // rotation per token: otherwise the timer fires against a value that has
  // already been replaced.
  useEffect(() => {
    const onRefreshed = (event: Event) => {
      const { expiresIn } = (event as CustomEvent<{ expiresIn: number }>).detail
      scheduleTokenRefresh(expiresIn)
    }
    window.addEventListener(TOKENS_REFRESHED_EVENT, onRefreshed)
    return () => window.removeEventListener(TOKENS_REFRESHED_EVENT, onRefreshed)
  }, [scheduleTokenRefresh])

  // Check session on mount
  useEffect(() => {
    checkSession()

    return () => {
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current)
      }
    }
  }, [])

  const checkSession = async () => {
    const token = tokenManager.getAccessToken()
    if (!token) {
      setIsLoading(false)
      return
    }

    // Try to refresh if token is expiring
    if (tokenManager.isTokenExpiring()) {
      const refreshed = await refreshTokenInternal()
      if (!refreshed) {
        setIsLoading(false)
        return
      }
    }

    try {
      const fetchMe = () =>
        fetch(`${API_BASE}/me`, {
          headers: {
            Authorization: `Bearer ${tokenManager.getAccessToken()}`,
          },
        })
      let res = await fetchMe()
      // A 429 says nothing about the session. It used to fall through to
      // "Cannot reach the server", leaving no user, so the protected routes sent
      // a signed-in person to the sign-in page. Wait out the limit and ask again.
      let waited = 0
      while (res.status === 429 && waited < SESSION_CHECK_MAX_WAIT) {
        const seconds = retryAfterSeconds(res.headers.get('Retry-After'))
        setNotice(`Packwright is busy (too many requests from this address). Checking your session again in ${seconds} s…`)
        await new Promise((resolve) => setTimeout(resolve, seconds * 1000))
        waited += seconds
        res = await fetchMe()
      }
      setNotice(null)

      if (res.ok) {
        const userData: User = await res.json()
        setUser(userData)

        // Decode JWT to get permissions
        const accessToken = tokenManager.getAccessToken()
        if (accessToken) {
          try {
            const payload = JSON.parse(atob(accessToken.split('.')[1]))
            setPermissions(new Set(payload.permissions || []))
            scheduleTokenRefresh(payload.exp - Math.floor(Date.now() / 1000))
          } catch {
            // Token decode failed, permissions will be empty
          }
        }
      } else if (res.status === 401 || res.status === 403) {
        tokenManager.clearTokens()
      } else if (res.status === 429) {
        setError('Too many requests from this address. Your session is kept; reload in a minute.')
      } else {
        setError('Cannot reach the server. Your session is kept; reload once it is back.')
      }
    } catch {
      // Network failure: the server is down, not the session.
      setError('Cannot reach the server. Your session is kept; reload once it is back.')
    } finally {
      setIsLoading(false)
    }
  }

  const login = async (username: string, password: string, rememberMe = false) => {
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, remember_me: rememberMe }),
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Login failed')
      }

      const data: TokenResponse = await res.json()
      // Clear any tokens left by a prior session (e.g. a previous
      // "remember me" login) so the storage location unambiguously
      // reflects THIS login's rememberMe choice.
      tokenManager.clearTokens()
      tokenManager.setTokens(data.access_token, data.refresh_token || null, data.expires_in, rememberMe)
      setUser(data.user)
      setPermissions(new Set(data.permissions))
      scheduleTokenRefresh(data.expires_in)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed'
      setError(message)
      throw err
    }
  }

  const register = async (username: string, password: string): Promise<{ pendingApproval: boolean }> => {
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Registration failed')
      }

      const data = await res.json()

      // Non-first user: pending admin approval
      if (data.pending_approval) {
        return { pendingApproval: true }
      }

      // First user: auto-login
      tokenManager.clearTokens()
      tokenManager.setTokens(data.access_token, data.refresh_token || null, data.expires_in, false)
      setUser(data.user)
      setPermissions(new Set(data.permissions))
      scheduleTokenRefresh(data.expires_in)
      return { pendingApproval: false }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Registration failed'
      setError(message)
      throw err
    }
  }

  // Everything a signed-out browser must forget: tokens, the form draft (it may
  // hold another system's secrets, and belongs to this user), and — via
  // SIGNED_OUT_EVENT — the query cache and task store, which otherwise showed
  // the previous user's builds to whoever signed in next on this tab.
  const signOutLocally = () => {
    tokenManager.clearTokens()
    clearFormDraft()
    setUser(null)
    setPermissions(new Set())
    if (refreshTimeoutRef.current) {
      clearTimeout(refreshTimeoutRef.current)
    }
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
  }

  const logout = async () => {
    const refreshToken = tokenManager.getRefreshToken()
    const accessToken = tokenManager.getAccessToken()

    if (refreshToken && accessToken) {
      try {
        await fetch(`${API_BASE}/logout`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
      } catch {
        // Ignore errors during logout
      }
    }

    signOutLocally()
  }

  const logoutAllDevices = async () => {
    const accessToken = tokenManager.getAccessToken()

    if (accessToken) {
      try {
        await fetch(`${API_BASE}/logout-all`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        })
      } catch {
        // Ignore errors
      }
    }

    signOutLocally()
  }

  const refreshToken = async (): Promise<boolean> => {
    return refreshTokenInternal()
  }

  const hasPermission = (code: string): boolean => {
    // Direct match
    if (permissions.has(code)) return true

    // Superadmin wildcard
    if (permissions.has('*:*')) return true

    // Parse required permission
    if (!code.includes(':')) return false
    const [resource, action] = code.split(':', 2)

    // Resource wildcard (e.g., "task:*" matches "task:create")
    if (permissions.has(`${resource}:*`)) return true

    // Action wildcard (e.g., "*:view" matches "task:view")
    if (permissions.has(`*:${action}`)) return true

    return false
  }

  const hasAnyPermission = (...codes: string[]): boolean => {
    return codes.some((code) => hasPermission(code))
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        permissions,
        login,
        register,
        logout,
        logoutAllDevices,
        refreshToken,
        hasPermission,
        hasAnyPermission,
        error,
        notice,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export async function checkFirstUser(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/check-first-user`)
    const data = await res.json()
    return data.is_first_user
  } catch {
    return false
  }
}
