/**
 * Rolling samples for the monitoring page, advanced once per fetched snapshot.
 *
 * A pure function of (previous samples, snapshot, fetch time). The page used to
 * push into refs from inside useMemo: render-time mutation, so React StrictMode's
 * double render recorded every sample twice, and the network rate divided by a
 * hard-coded 2 s instead of the real time between fetches.
 */

export const MAX_HISTORY = 60

export interface Samples {
  /** Overall CPU %, oldest first, at most MAX_HISTORY points. */
  cpu: number[]
  /** Counter values and fetch time of the previous snapshot. */
  last: { sent: number; recv: number; at: number } | null
  /** Bytes per second between the last two snapshots. */
  rate: { sent: number; recv: number }
  /** Fetch time of the snapshot these samples include (0 = none yet). */
  at: number
}

export const EMPTY_SAMPLES: Samples = { cpu: [], last: null, rate: { sent: 0, recv: 0 }, at: 0 }

export interface Snapshot {
  cpuPercent: number
  bytesSent: number
  bytesRecv: number
}

export function advanceSamples(prev: Samples, snap: Snapshot, at: number): Samples {
  if (at <= prev.at) return prev
  const cpu = [...prev.cpu, snap.cpuPercent].slice(-MAX_HISTORY)
  let rate = prev.rate
  if (prev.last && at > prev.last.at) {
    const seconds = (at - prev.last.at) / 1000
    rate = {
      // Counters reset when the host reboots; never report a negative rate.
      sent: Math.max(0, (snap.bytesSent - prev.last.sent) / seconds),
      recv: Math.max(0, (snap.bytesRecv - prev.last.recv) / seconds),
    }
  }
  return { cpu, rate, last: { sent: snap.bytesSent, recv: snap.bytesRecv, at }, at }
}
