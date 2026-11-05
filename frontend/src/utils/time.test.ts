import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest'
import { parseUtc, timeAgo } from './time'

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
