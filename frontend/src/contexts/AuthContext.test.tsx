import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { AuthProvider, useAuth } from './AuthContext'

// A rate-limited session check (429 on /auth/me) used to end like a dead server:
// no user, so the protected routes sent a signed-in person to the sign-in page.

const payload = btoa(JSON.stringify({ permissions: ['task:create'], exp: Math.floor(Date.now() / 1000) + 3600 }))
const token = `x.${payload}.y`

function Probe() {
  const { isLoading, isAuthenticated, notice, error } = useAuth()
  return (
    <div>
      <span data-testid="state">{isLoading ? 'loading' : isAuthenticated ? 'signed-in' : 'signed-out'}</span>
      <span data-testid="notice">{notice ?? ''}</span>
      <span data-testid="error">{error ?? ''}</span>
    </div>
  )
}

const tooMany = () => new Response(JSON.stringify({ detail: 'Too many requests' }), { status: 429, headers: { 'Retry-After': '2' } })
const me = () => new Response(JSON.stringify({ id: 1, username: 'admin' }), { status: 200 })

describe('session check under a rate limit', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    sessionStorage.setItem('access_token', token)
    sessionStorage.setItem('refresh_token', 'refresh')
    sessionStorage.setItem('token_expiry', String(Date.now() + 3600_000))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('waits out a 429 and keeps the person signed in', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(tooMany()).mockResolvedValueOnce(me())
    vi.stubGlobal('fetch', fetchMock)

    render(<AuthProvider><Probe /></AuthProvider>)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    expect(screen.getByTestId('state').textContent).toBe('loading')
    expect(screen.getByTestId('notice').textContent).toMatch(/again in 2 s/)

    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('state').textContent).toBe('signed-in')
    expect(screen.getByTestId('notice').textContent).toBe('')
  })

  it('gives up after a while but keeps the stored session', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => tooMany())
    vi.stubGlobal('fetch', fetchMock)

    render(<AuthProvider><Probe /></AuthProvider>)
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })

    expect(screen.getByTestId('state').textContent).toBe('signed-out')
    expect(screen.getByTestId('error').textContent).toMatch(/Too many requests/)
    expect(sessionStorage.getItem('access_token')).toBe(token)
    expect(fetchMock.mock.calls.length).toBeGreaterThan(2)
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(46)
  })
})
