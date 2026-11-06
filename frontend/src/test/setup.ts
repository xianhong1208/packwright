import '@testing-library/jest-dom/vitest'
import { afterAll } from 'vitest'
import { message, notification } from 'antd'

// Let work scheduled by the last test run before this file's jsdom is torn down.
// React's scheduler and antd's message/notification timers outlive the test
// that started them; when one fired after teardown it threw "window is not
// defined", failing CI with every test passed.
afterAll(async () => {
  message.destroy()
  notification.destroy()
  // Two timer turns: Node runs every setImmediate (React's scheduler) between them.
  await new Promise((resolve) => setTimeout(resolve, 0))
  await new Promise((resolve) => setTimeout(resolve, 0))
})

// Browser APIs antd relies on that jsdom does not implement.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}
if (!('ResizeObserver' in window)) {
  ;(window as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}
