import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Separate from vite.config.ts so the dev-server proxy and build options do not
// leak into test runs — the two configs answer different questions.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Only our own sources; node_modules holds thousands of vendored tests.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // The New build wizard tests (CreateTask, ProjectSettingsPage) wait on the
    // page's real 500 ms detection debounce and allow findBy* up to 3-5 s; the
    // default 5 s per test was tighter than the waits inside them, so a busy
    // machine failed them on time alone. A test that is really stuck still fails.
    testTimeout: 15_000,
  },
})
