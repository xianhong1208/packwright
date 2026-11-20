import { describe, expect, it } from 'vitest'
import { shortCommit, triggerLabel } from './buildOrigin'

describe('build origin', () => {
  it('TC-FE-ORG-001: names every trigger, and an unrecorded one as the console', () => {
    expect(triggerLabel('push')).toBe('Push')
    expect(triggerLabel('tag')).toBe('Tag push')
    expect(triggerLabel('schedule')).toBe('Schedule')
    expect(triggerLabel('api')).toBe('API')
    expect(triggerLabel(undefined)).toBe('Console')
    expect(triggerLabel(null)).toBe('Console')
  })

  it('TC-FE-ORG-002: shows seven characters of a commit', () => {
    expect(shortCommit('3f2a9c1d4b5e6f708192a3b4c5d6e7f809a1b2c3')).toBe('3f2a9c1')
  })
})
