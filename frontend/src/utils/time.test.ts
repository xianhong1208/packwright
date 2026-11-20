import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest'
import { expiryText, parseUtc, timeAgo } from './time'

describe('parseUtc', () => {
  // The browser is not in UTC; in a UTC test run a local-time parse would look right.
  beforeAll(() => { vi.stubEnv('TZ', 'Asia/Taipei') })
  afterAll(() => { vi.unstubAllEnvs() })
  it('reads a timestamp without a zone as UTC, not local time', () => {
    expect(parseUtc('2026-11-05T05:00:00').toISOString()).toBe('2026-11-05T05:00:00.000Z')
    expect(parseUtc('2026-11-05 05:00:00').toISOString()).toBe('2026-11-05T05:00:00.000Z')
    expect(parseUtc('2026-11-05T05:00:00+08:00').toISOString()).toBe('2026-11-04T21:00:00.000Z')
  })
})

describe('timeAgo', () => {
  it('reads server time as UTC', () => {
    const now = Date.parse('2026-11-05T05:03:00Z')
    expect(timeAgo('2026-11-05T05:00:00', now)).toBe('3 min ago')
    expect(timeAgo('2026-11-04T04:00:00', now)).toBe('yesterday')
  })
})

describe('expiryText', () => {
  const now = Date.parse('2026-11-20T00:00:00Z')
  it('counts days ahead, hours on the last day, and says when it has passed', () => {
    expect(expiryText('2026-12-20T00:00:00', now)).toBe('expires in 30 days')
    expect(expiryText('2026-11-21T12:00:00', now)).toBe('expires tomorrow')
    expect(expiryText('2026-11-20T05:30:00', now)).toBe('expires in 5 h')
    expect(expiryText('2026-11-17T00:00:00', now)).toBe('expired 3 days ago')
  })
})
