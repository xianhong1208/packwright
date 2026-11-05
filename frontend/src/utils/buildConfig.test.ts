import { describe, it, expect } from 'vitest'
import { binaryName } from './buildConfig'

describe('binaryName', () => {
  it('uses the explicit output name when one was set', () => {
    expect(binaryName({ output_name: 'server', entry_point: 'main.py' })).toBe('server')
  })

  it('derives the stem of the entry point when output name is empty', () => {
    expect(binaryName({ output_name: '', entry_point: 'main.py' })).toBe('main')
    expect(binaryName({ output_name: '', entry_point: 'src/app/cli.py' })).toBe('cli')
  })

  it('shows a dash rather than a blank when nothing is known', () => {
    expect(binaryName({ output_name: '', entry_point: '' })).toBe('—')
  })
})
