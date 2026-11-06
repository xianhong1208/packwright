import { describe, it, expect } from 'vitest'
import { depGroupHint, depGroupPlaceholder } from './depGroups'

const base = { count: 0, loading: false, read: 'unread' as const, sourceType: 'local' as const }

describe('depGroupHint', () => {
  it('asks for the source only until it has been read', () => {
    expect(depGroupHint(base)).toMatch(/Enter the project path/)
    expect(depGroupHint({ ...base, sourceType: 'git' })).toMatch(/Pick a branch or tag/)
  })
  it('says a project without groups has none, instead of asking for the path again', () => {
    const hint = depGroupHint({ ...base, read: 'read' })
    expect(hint).toBe('This project defines no dependency groups, so the default dependencies are installed.')
  })
  it('tells a failed read apart from an empty one', () => {
    expect(depGroupHint({ ...base, read: 'failed' })).toMatch(/Could not read/)
  })
  it('counts what it found, in the singular for one', () => {
    expect(depGroupHint({ ...base, read: 'read', count: 1 })).toMatch(/^Read 1 group from/)
    expect(depGroupHint({ ...base, read: 'read', count: 3 })).toMatch(/^Read 3 groups from/)
  })
  it('says it is reading while it is', () => {
    expect(depGroupHint({ ...base, read: 'read', count: 3, loading: true })).toBe('Reading pyproject.toml…')
  })
})

describe('depGroupPlaceholder', () => {
  it('only claims "none defined" after a read', () => {
    expect(depGroupPlaceholder({ count: 0, read: 'unread' })).toBe('Nothing to pick yet')
    expect(depGroupPlaceholder({ count: 0, read: 'failed' })).toBe('Nothing to pick yet')
    expect(depGroupPlaceholder({ count: 0, read: 'read' })).toBe('None defined')
    expect(depGroupPlaceholder({ count: 2, read: 'read' })).toBe('Pick a dependency group')
  })
})
