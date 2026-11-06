import { useQuery } from '@tanstack/react-query'
import api from '../../api/client'
import type { CompileCacheStatus } from '../../api/types'
import { formatBytes } from '../../utils/bytes'

/**
 * Whether builds reuse compiled C files. Without ccache every build compiles all
 * of them again and nothing else says so; with it a rebuild can be several times
 * faster. Read once a minute: the size changes only as builds run.
 */
export default function CompileCache() {
  const { data } = useQuery<CompileCacheStatus>({
    queryKey: ['compileCache'],
    queryFn: async () => (await api.get('/monitoring/compile-cache')).data,
    refetchInterval: 60_000,
  })
  if (!data) return null
  const size = data.size_bytes === null ? null
    : data.max_size_bytes ? `${formatBytes(data.size_bytes)} of ${formatBytes(data.max_size_bytes)}`
    : formatBytes(data.size_bytes)
  return (
    <section className="glass-card p-5 mb-4" aria-labelledby="compile-cache">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h2 id="compile-cache" className="text-[17px] font-semibold m-0" style={{ color: 'var(--ink)' }}>Compile cache</h2>
        <span className="text-sm" style={{ color: data.enabled ? 'var(--color-teal-400)' : 'var(--color-signal-400)' }}>
          {data.enabled ? 'On' : 'Off'}
        </span>
      </div>
      {data.enabled ? (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-muted)' }}>
          Rebuilds reuse the C files that did not change.{size && <> The cache holds {size}{data.files !== null ? `, ${data.files} files` : ''}.</>}
        </p>
      ) : (
        <p className="m-0 text-sm" style={{ color: 'var(--ink-muted)' }}>
          {data.reason ?? 'ccache is not installed'}, so every build compiles all of its C files again.
          {data.reason?.startsWith('NUITKA_CCACHE_BINARY') ? ' Fix the path, or unset it to use ccache from PATH.' : (
            <> Install it on the build host (<code>apt install ccache</code>, <code>dnf install ccache</code>);
            the next build uses it, no restart needed.</>
          )}
        </p>
      )}
      <p className="m-0 mt-2 text-[13px] break-all" style={{ color: 'var(--ink-faint)' }}>
        Stored in <code>{data.directory}</code>
      </p>
    </section>
  )
}
