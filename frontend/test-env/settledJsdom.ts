import { builtinEnvironments } from 'vitest/runtime'
import type { Environment } from 'vitest/runtime'

/**
 * Vitest's jsdom environment, torn down only once React has finished the work it
 * already queued.
 *
 * React runs work outside act() (antd's message countdown sets state on every
 * animation frame, Modal.confirm closes on a timeout) through its scheduler, and
 * the scheduler queues each task with Node's setImmediate, which jsdom does not
 * own. The stock teardown stops jsdom's timers and deletes `window` in one go, so
 * a task queued just before it then runs without `window` and fails the whole run
 * with "window is not defined", although every test passed.
 *
 * Here the teardown closes the window first (no timer or frame fires after that,
 * so nothing new is queued), lets the tasks already queued run while `window`
 * still exists, and only then removes the globals.
 */

const jsdom = builtinEnvironments.jsdom

// Each round lets the scheduler run one queued task. A task can queue the next
// (a commit queues its passive effects, which may render again), so allow a chain.
const DRAIN_ROUNDS = 20

const settledJsdom: Environment = {
  ...jsdom,
  name: 'settled-jsdom',
  async setup(global, options) {
    const env = await jsdom.setup(global, options)
    return {
      async teardown(global) {
        ;(global.jsdom as { window: { close(): void } }).window.close()
        for (let round = 0; round < DRAIN_ROUNDS; round++) {
          await new Promise((resolve) => setImmediate(resolve))
        }
        await env.teardown(global)
      },
    }
  },
}

export default settledJsdom
