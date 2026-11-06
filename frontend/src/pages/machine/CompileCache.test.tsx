import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { CompileCacheStatus } from '../../api/types'

const get = vi.hoisted(() => vi.fn())
vi.mock('../../api/client', () => ({ default: { get } }))

import CompileCache from './CompileCache'

function renderWith(status: CompileCacheStatus) {
  get.mockResolvedValue({ data: status })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CompileCache />
    </QueryClientProvider>,
  )
}

const on: CompileCacheStatus = {
  enabled: true,
  binary: '/usr/bin/ccache',
  directory: '/srv/packwright/nuitka-cache/ccache',
  size_bytes: 4848 * 1024,
  max_size_bytes: 5 * 1024 ** 3,
  files: 164,
}

beforeEach(() => get.mockReset())

describe('Compile cache on the Machine page', () => {
  it('says the cache is on, how full it is and where it is', async () => {
    renderWith(on)
    expect(await screen.findByText('On')).toBeInTheDocument()
    expect(screen.getByText(/The cache holds 4.7 MB of 5.0 GB, 164 files/)).toBeInTheDocument()
    expect(screen.getByText('/srv/packwright/nuitka-cache/ccache')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/monitoring/compile-cache')
  })

  it('leaves out a limit ccache does not have', async () => {
    renderWith({ ...on, max_size_bytes: null })
    expect(await screen.findByText(/The cache holds 4.7 MB, 164 files/)).toBeInTheDocument()
  })

  it('says how to turn it on when ccache is missing', async () => {
    renderWith({ ...on, enabled: false, binary: null, size_bytes: null, max_size_bytes: null, files: null })
    expect(await screen.findByText('Off')).toBeInTheDocument()
    expect(screen.getByText(/every build compiles all of its C files again/)).toBeInTheDocument()
    expect(screen.getByText('apt install ccache')).toBeInTheDocument()
  })
})
