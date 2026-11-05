import { describe, expect, it } from 'vitest'
import { advanceSamples, EMPTY_SAMPLES, MAX_HISTORY } from './monitoringSamples'

const snap = (cpuPercent: number, bytesSent = 0, bytesRecv = 0) => ({ cpuPercent, bytesSent, bytesRecv })

describe('advanceSamples', () => {
  it('records each fetched snapshot exactly once', () => {
    // StrictMode renders twice; the same fetch time must not add a second point.
    const once = advanceSamples(EMPTY_SAMPLES, snap(10), 1000)
    expect(advanceSamples(once, snap(10), 1000)).toBe(once)
    expect(once.cpu).toEqual([10])
  })

  it('divides by the real time between fetches, not a fixed 2 s', () => {
    const a = advanceSamples(EMPTY_SAMPLES, snap(0, 1_000, 5_000), 10_000)
    const b = advanceSamples(a, snap(0, 9_000, 9_000), 14_000) // 4 s later
    expect(b.rate).toEqual({ sent: 2_000, recv: 1_000 })
  })

  it('never reports a negative rate when counters reset', () => {
    const a = advanceSamples(EMPTY_SAMPLES, snap(0, 9_000, 9_000), 1_000)
    const b = advanceSamples(a, snap(0, 100, 100), 3_000)
    expect(b.rate).toEqual({ sent: 0, recv: 0 })
  })

  it('keeps at most MAX_HISTORY points', () => {
    let s = EMPTY_SAMPLES
    for (let i = 1; i <= MAX_HISTORY + 5; i++) s = advanceSamples(s, snap(i), i * 1000)
    expect(s.cpu).toHaveLength(MAX_HISTORY)
    expect(s.cpu[0]).toBe(6)
  })
})
