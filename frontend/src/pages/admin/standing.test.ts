import { describe, it, expect } from 'vitest'
import { standing } from './standing'

describe('standing', () => {
  it('tells a new registration apart from an account that was switched off', () => {
    expect(standing({ is_active: true, last_login: null }).key).toBe('active')
    expect(standing({ is_active: false, last_login: null }).key).toBe('waiting')
    expect(standing({ is_active: false, last_login: '2026-11-01T00:00:00' }).key).toBe('disabled')
  })
})
