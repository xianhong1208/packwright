import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
const BACKEND = process.env.PACKWRIGHT_BACKEND || 'http://localhost:5018'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        // Split only libraries that are (a) needed on every route anyway and
        // (b) essentially frozen between releases. Paired with the immutable
        // cache headers on /assets/, a deploy then invalidates the app chunk
        // and leaves React in the browser's cache.
        //
        // antd is deliberately NOT lumped together: Vite already emits its
        // heavier pieces (Table, ~190 kB) as lazily-loaded chunks, and forcing
        // them into a shared vendor chunk would drag them into the initial
        // download the moment the app shell touches any antd component.
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(id)) {
            return 'vendor-react'
          }
          if (id.includes('@tanstack')) return 'vendor-query'
        },
      },
    },
  },
  server: {
    port: 5173,
    // The backend the dev server forwards to. Set PACKWRIGHT_BACKEND when the
    // backend you are developing against is not on :5018 (e.g. another
    // service already holds that port on this machine).
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/auth': { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND.replace(/^http/, 'ws'), ws: true },
    },
  },
})
