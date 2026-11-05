import { describe, expect, it } from 'vitest'
import { isSessionRejected } from './session'

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
