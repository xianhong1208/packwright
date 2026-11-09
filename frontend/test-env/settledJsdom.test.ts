import { describe, expect, it } from 'vitest'
import type { Environment } from 'vitest/runtime'
import settledJsdom from './settledJsdom'

type Global = Parameters<Environment['setup']>[0]

async function start() {
  const global = {} as Global
  const env = await settledJsdom.setup(global, {})
  return { global, env }
}

const hasWindow = (global: Global) => typeof (global as { window?: unknown }).window === 'object'

describe('settled jsdom environment', () => {
  it('runs work queued before teardown while window still exists', async () => {
    const { global, env } = await start()
    const seen: boolean[] = []
    // What React's scheduler does: a task queued with setImmediate, which queues the next
    // (a commit queuing its passive effects).
    setImmediate(() => {
      seen.push(hasWindow(global))
      setImmediate(() => seen.push(hasWindow(global)))
    })

    await env.teardown(global)

    expect(seen).toEqual([true, true])
    expect(hasWindow(global)).toBe(false)
  })

  it('stops jsdom timers before it waits, so nothing new is queued meanwhile', async () => {
    const { global, env } = await start()
    const win = (global as unknown as { window: { requestAnimationFrame(callback: () => void): number } }).window
    // A countdown that sets state on every frame, like antd's message notices.
    let tearingDown = false
    const frames: boolean[] = []
    const frame = () => {
      frames.push(tearingDown)
      win.requestAnimationFrame(frame)
    }
    win.requestAnimationFrame(frame)
    await new Promise((resolve) => setTimeout(resolve, 50))
    // Queued work slow enough (about 80 ms) that frames would keep coming while it drains.
    const busy = (links: number) => {
      const until = Date.now() + 8
      while (Date.now() < until) { /* a slow render */ }
      if (links > 1) setImmediate(() => busy(links - 1))
    }
    setImmediate(() => busy(10))

    tearingDown = true
    await env.teardown(global)

    expect(frames.length).toBeGreaterThan(0)
    expect(frames).not.toContain(true)
  })
})
