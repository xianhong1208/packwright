import { describe, it, expect } from 'vitest'
import type { BuildBrief } from '../../api/types'
import { groupByVersion, passedBefore, sourceLabel } from './versions'

const b = (task_id: string, version: string | null, status: BuildBrief['status']): BuildBrief => ({
  task_id, version, status, user_name: 'tony', start_time: '2026-11-06T00:00:00', end_time: null,
})

// newest first, as the API returns them
const history = [b('5', '1.3.0', 'failed'), b('4', '1.2.0', 'completed'), b('3', null, 'completed'), b('2', '1.2.0', 'failed'), b('1', '1.1.0', 'completed')]

describe('groupByVersion', () => {
  it('groups by version, most recently built first, keeping builds newest first', () => {
    const groups = groupByVersion(history)
    expect(groups.map((g) => g.version)).toEqual(['1.3.0', '1.2.0', null, '1.1.0'])
    expect(groups[1].builds.map((x) => x.task_id)).toEqual(['4', '2'])
  })
  it('knows the last passed build of each version, if any', () => {
    const groups = groupByVersion(history)
    expect(groups[0].lastPassed).toBeNull()
    expect(groups[1].lastPassed?.task_id).toBe('4')
  })
})

describe('passedBefore', () => {
  it('finds a passed build of exactly that version', () => {
    expect(passedBefore(history, '1.2.0')?.task_id).toBe('4')
    expect(passedBefore(history, ' 1.2.0 ')?.task_id).toBe('4')
  })
  it('ignores failed builds, other versions and an empty version', () => {
    expect(passedBefore(history, '1.3.0')).toBeNull()
    expect(passedBefore(history, '1.2')).toBeNull()
    expect(passedBefore(history, '')).toBeNull()
  })
})

describe('sourceLabel', () => {
  it('shortens a path or a Git URL', () => {
    expect(sourceLabel({ source_type: 'local', source: '/srv/projects/team/shop' })).toBe('…/team/shop')
    expect(sourceLabel({ source_type: 'local', source: '/srv/shop' })).toBe('/srv/shop')
    expect(sourceLabel({ source_type: 'git', source: 'https://github.com/acme/shop.git' })).toBe('github.com/acme/shop')
  })
})
