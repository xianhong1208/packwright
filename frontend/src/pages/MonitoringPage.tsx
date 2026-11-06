import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Spin, Button, Tooltip } from 'antd'
import { ArrowUpIcon, ArrowsClockwiseIcon, WarningCircleIcon } from '../components/ui/icons'
import api from '../api/client'
import { getErrorDetail } from '../utils/errors'
import type { SystemStats } from '../api/types'
import { formatBytes } from '../utils/bytes'
import CompileCache from './machine/CompileCache'
import { advanceSamples, EMPTY_SAMPLES, type Samples } from './monitoringSamples'
import { heatColor } from './dashboard/bench'
import PageHeader from '../components/layout/PageHeader'


const meterColor = (pct: number): string =>
  pct >= 90 ? 'var(--color-alert-400)' : pct >= 75 ? 'var(--color-signal-400)' : 'var(--ink-muted)'

function Meter({ pct }: { pct: number }) {
  return (
    <div className="meter" role="presentation">
      <span style={{ width: `${Math.min(100, pct)}%`, background: meterColor(pct), transition: 'width 0.3s ease' }} />
    </div>
  )
}

/** One headline figure of the machine, with what it is out of. */
function Tile({ label, value, of, pct, children }: { label: string; value: string; of?: string; pct?: number; children?: React.ReactNode }) {
  return (
    <div className="glass-card p-5 min-w-0">
      <div className="text-[15px] font-semibold" style={{ color: 'var(--ink-muted)' }}>{label}</div>
      <div className="text-[34px] font-bold leading-tight mt-1" style={{ color: 'var(--ink)' }}>{value}</div>
      {of && <div className="text-sm" style={{ color: 'var(--ink-faint)' }}>{of}</div>}
      {pct !== undefined && <Meter pct={pct} />}
      {children}
    </div>
  )
}

function Sparkline({ data, height = 36, label }: { data: number[]; height?: number; label: string }) {
  if (data.length < 2) return null
  const w = 200
  const points = data.map((v, i) => `${(i / (data.length - 1)) * w},${height - (v / 100) * height}`)
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${w} ${height}`} style={{ width: '100%', height }} preserveAspectRatio="none" className="mt-3">
      <title>{label}</title>
      <polygon points={`0,${height} ${points.join(' ')} ${w},${height}`} fill="var(--color-teal-500)" opacity={0.15} />
      <polyline points={points.join(' ')} fill="none" stroke="var(--color-teal-400)" strokeWidth={1.5} />
    </svg>
  )
}

export default function MonitoringPage() {
  const { data: stats, dataUpdatedAt, isLoading, isError, error, refetch } = useQuery<SystemStats>({
    queryKey: ['systemStats'],
    queryFn: async () => (await api.get('/monitoring/stats')).data,
    refetchInterval: 2000,
  })

  // Advance the rolling samples once per fetched snapshot (deriving state from a
  // changing input while rendering, keyed on dataUpdatedAt).
  const [samples, setSamples] = useState<Samples>(EMPTY_SAMPLES)
  if (stats && dataUpdatedAt > samples.at) {
    setSamples(advanceSamples(samples, {
      cpuPercent: stats.cpu.percent,
      bytesSent: stats.network.bytes_sent,
      bytesRecv: stats.network.bytes_recv,
    }, dataUpdatedAt))
  }

  if (isError && !stats) {
    return (
      <div className="glass-card flex flex-col items-center justify-center gap-3 py-16 px-4 text-center">
        <WarningCircleIcon style={{ fontSize: 36, color: 'var(--color-alert-400)' }} aria-hidden="true" />
        <div className="font-semibold text-alert-400">Could not read the machine's load</div>
        <div className="max-w-md" style={{ color: 'var(--ink-muted)' }}>{getErrorDetail(error)}</div>
        <Button icon={<ArrowsClockwiseIcon />} onClick={() => refetch()}>Try again</Button>
      </div>
    )
  }

  if (isLoading || !stats) {
    return <div className="flex items-center justify-center h-64"><Spin size="large" /></div>
  }

  const cores = stats.cpu.percent_per_core
  const hot = cores.filter((p) => p >= 80).length
  const busy = cores.filter((p) => p >= 5).length
  const ghz = stats.cpu.frequency_current ? `, ${(stats.cpu.frequency_current / 1000).toFixed(1)} GHz` : ''

  return (
    <div>
      <PageHeader title="Machine" lead="Load on the build host, refreshed every 2 seconds." />

      <div className="grid gap-4 mb-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile label="Processor" value={`${Math.round(stats.cpu.percent)}% busy`} of={`${stats.cpu.count_logical} threads on ${stats.cpu.count_physical} cores${ghz}`}>
          <Sparkline data={samples.cpu} label={`Processor load over the last minute, now ${stats.cpu.percent.toFixed(0)}%`} />
        </Tile>
        <Tile label="Memory" value={formatBytes(stats.memory.used)} of={`of ${formatBytes(stats.memory.total)}${stats.swap.total > 0 ? `, swap ${formatBytes(stats.swap.used)} of ${formatBytes(stats.swap.total)}` : ''}`} pct={stats.memory.percent} />
        <Tile label="Disk" value={formatBytes(stats.disk.used)} of={`of ${formatBytes(stats.disk.total)}, ${formatBytes(stats.disk.free)} free`} pct={stats.disk.percent} />
        <Tile label="Network" value={`${formatBytes(samples.rate.recv)}/s`} of="received now">
          <div className="flex flex-col gap-1 mt-3 text-sm" style={{ color: 'var(--ink-muted)' }}>
            <span className="inline-flex items-center gap-2"><ArrowUpIcon />{formatBytes(samples.rate.sent)}/s sent now</span>
            <span>{formatBytes(stats.network.bytes_sent)} sent, {formatBytes(stats.network.bytes_recv)} received since boot</span>
          </div>
        </Tile>
      </div>

      <section className="glass-card p-5 mb-4" aria-label="Cores">
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
          <h2 className="text-[17px] font-semibold m-0" style={{ color: 'var(--ink)' }}>Cores</h2>
          <span className="text-sm" style={{ color: 'var(--ink-muted)' }}>
            {busy} of {cores.length} working{hot > 0 ? `, ${hot} near full load` : ''}
          </span>
        </div>
        <div className="core-grid" role="img" aria-label={`Load of each of ${cores.length} cores: ${busy} working, ${hot} near full load`}>
          {cores.map((pct, i) => (
            <Tooltip key={i} title={`Core ${i}: ${Math.round(pct)}%`} mouseEnterDelay={0}>
              <i style={{ background: heatColor(pct) }} />
            </Tooltip>
          ))}
        </div>
        <div className="flex flex-wrap gap-4 mt-3 text-[13px]" style={{ color: 'var(--ink-faint)' }} aria-hidden="true">
          {[['Idle', 0], ['Light', 20], ['Busy', 50], ['Near full', 90]].map(([label, pct]) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <i className="inline-block w-3 h-3 rounded-[3px]" style={{ background: heatColor(pct as number) }} />{label}
            </span>
          ))}
        </div>
      </section>

      <CompileCache />

      {stats.gpus.length > 0 && (
        <section className="glass-card p-5" aria-label="GPUs">
          <h2 className="text-[17px] font-semibold m-0 mb-3" style={{ color: 'var(--ink)' }}>Graphics cards</h2>
          <div className="grid gap-5 md:grid-cols-2">
            {stats.gpus.map((gpu) => (
              <div key={gpu.id}>
                <div className="flex justify-between gap-2"><b>GPU {gpu.id}, {gpu.name}</b><span style={{ color: gpu.temperature > 80 ? 'var(--color-alert-400)' : 'var(--ink-muted)' }}>{gpu.temperature}°C</span></div>
                <div className="flex justify-between text-sm mt-2" style={{ color: 'var(--ink-muted)' }}><span>Load</span><span>{Math.round(gpu.load)}%</span></div>
                <Meter pct={gpu.load} />
                <div className="flex justify-between text-sm mt-2" style={{ color: 'var(--ink-muted)' }}>
                  <span>Memory</span><span>{formatBytes(gpu.memory_used * 1024 * 1024)} of {formatBytes(gpu.memory_total * 1024 * 1024)}</span>
                </div>
                <Meter pct={gpu.memory_percent} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
