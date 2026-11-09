import { describe, expect, it } from 'vitest'
import { isSessionRejected, retryAfterSeconds } from './session'

describe('isSessionRejected', () => {
  it('treats 400/401/403 from the refresh endpoint as a dead session', () => {
    for (const status of [400, 401, 403]) {
      expect(isSessionRejected({ response: { status } })).toBe(true)
    }
  })

  it('keeps the session through network errors and server errors', () => {
    // A backend restart answered 502 or nothing at all; neither means the
    // stored tokens are invalid.
    expect(isSessionRejected(new Error('Network Error'))).toBe(false)
    expect(isSessionRejected({ response: { status: 502 } })).toBe(false)
    expect(isSessionRejected({ response: { status: 500 } })).toBe(false)
    expect(isSessionRejected(null)).toBe(false)
  })
})

describe('retryAfterSeconds', () => {
  it('waits what the server asks, within 1 to 30 seconds', () => {
    expect(retryAfterSeconds('12')).toBe(12)
    expect(retryAfterSeconds('59')).toBe(30)
    expect(retryAfterSeconds('0')).toBe(5)
  })

  it('falls back to 5 seconds without a usable header', () => {
    expect(retryAfterSeconds(null)).toBe(5)
    expect(retryAfterSeconds('Wed, 21 Oct 2026 07:28:00 GMT')).toBe(5)
  })
})
