import { describe, it, expect } from 'vitest'
import { hostProblem } from './gitHost'

describe('hostProblem', () => {
  it('accepts host names and addresses a clone URL can have', () => {
    for (const host of ['gitlab.example.com', ' GitLab.Example.COM. ', 'git-01.corp_internal.example', '10.0.0.5', '[2001:db8::1]', '', undefined]) {
      expect(hostProblem(host)).toBeNull()
    }
  })

  it('refuses what can never match, saying what to enter instead', () => {
    expect(hostProblem('https://gitlab.example.com/')).toMatch(/without https:\/\//)
    expect(hostProblem('gitlab.example.com/group')).toMatch(/without https:\/\//)
    expect(hostProblem('localhost')).toMatch(/localhost/)
    expect(hostProblem('gitlab.example.com:8443')).toMatch(/port/)
    for (const host of ['a b.com', '-bad.example.com', 'bad..example.com', 'ex@mple.com']) {
      expect(hostProblem(host)).toBe('Not a valid host name')
    }
  })
})
