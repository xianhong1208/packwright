import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Empty, Input, Pagination, Select, Spin, Tooltip, message } from 'antd'
import { ArrowClockwiseIcon, CubeIcon, DownloadSimpleIcon, MagnifyingGlassIcon, PlusIcon } from '../components/ui/icons'
import { useQuery } from '@tanstack/react-query'
import { taskApi } from '../api/client'
import type { HistoryItem } from '../api/types'
import { triggerDownload, triggerUrlDownload } from '../utils/download'
import { useAuth } from '../contexts/AuthContext'
import { STATUS_META } from '../utils/statusMeta'
import { getErrorDetail } from '../utils/errors'
import { PROJECT_TYPE_META } from '../utils/projectTypeMeta'
import { outcomeLine } from './dashboard/bench'
import { parseUtc, timeAgo } from '../utils/time'
import PageHeader from '../components/layout/PageHeader'
import { DEFAULT_FILTERS, filterBuilds, statusCounts, type BuildFilters, type StatusFilter } from './builds/filter'

const PAGE_SIZE = 20

const STATUS_CHIPS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'completed', label: 'Passed' },
  { key: 'failed', label: 'Failed' },
  { key: 'cancelled', label: 'Cancelled' },
]

export default function History() {
  const navigate = useNavigate()
  const { hasPermission } = useAuth()
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const [filters, setFilters] = useState<BuildFilters>(DEFAULT_FILTERS)
  const [page, setPage] = useState(1)

  // Only view_all holders can scope the list to another user; for view_own
  // users the backend already returns their own builds only.
  const canFilterByUser = hasPermission('history:view_all')
  const [userFilter, setUserFilter] = useState<string | undefined>(undefined)

  const { data: history, isLoading } = useQuery({
    queryKey: ['history', userFilter ?? null],
    queryFn: () => taskApi.getHistory(userFilter ? { user_name: userFilter } : undefined),
  })
  const { data: historyUsers } = useQuery({ queryKey: ['historyUsers'], queryFn: taskApi.listHistoryUsers, enabled: canFilterByUser })

  const shown = useMemo(() => filterBuilds(history ?? [], filters), [history, filters])
  const counts = useMemo(() => statusCounts(history ?? [], filters), [history, filters])
  const pageItems = shown.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const filtering = filters.query !== '' || filters.status !== 'all' || filters.type !== 'all'

  const update = (patch: Partial<BuildFilters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }

  const handleExport = async () => {
    try {
      const blob = await taskApi.exportHistory(userFilter)
      triggerDownload(blob, userFilter ? `history-${userFilter}.csv` : 'history.csv')
      message.success('Exported as CSV')
    } catch (err) {
      message.error(getErrorDetail(err, 'Could not export the builds'))
    }
  }

  const rebuild = (record: HistoryItem) =>
    record.config && navigate('/create', { state: { rebuild: true, projectName: record.project_name, config: record.config } })

  const download = async (record: HistoryItem) => {
    setDownloadingId(record.task_id)
    try {
      triggerUrlDownload(await taskApi.getOutputDownloadUrl(record.task_id))
      message.success('Download started')
    } catch (err: unknown) {
      message.error(getErrorDetail(err, 'Could not download the output'))
    } finally {
      setDownloadingId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Builds"
        lead={history ? `${history.length} ${history.length === 1 ? 'build' : 'builds'}${userFilter ? ` by ${userFilter}` : ''}.` : ' '}
        actions={<>
          {canFilterByUser && (
            <Select
              allowClear
              showSearch
              placeholder="Anyone"
              style={{ width: 180 }}
              value={userFilter}
              onChange={(v) => { setUserFilter(v); setPage(1) }}
              options={(historyUsers ?? []).map((u) => ({ label: u, value: u }))}
              aria-label="Builds by"
            />
          )}
          <Button icon={<DownloadSimpleIcon />} onClick={handleExport}>Export CSV</Button>
        </>}
      />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Input
          allowClear
          prefix={<MagnifyingGlassIcon />}
          placeholder="Search by project or person"
          value={filters.query}
          onChange={(e) => update({ query: e.target.value })}
          className="!w-full sm:!w-72"
          aria-label="Search builds"
        />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Status">
          {STATUS_CHIPS.map((c) => (
            <button
              key={c.key}
              type="button"
              aria-pressed={filters.status === c.key}
              onClick={() => update({ status: c.key })}
              className="chip"
            >
              {c.label} <span className="chip-count">{counts[c.key]}</span>
            </button>
          ))}
        </div>
        <div className="flex gap-2 sm:ml-auto">
          <Select
            value={filters.type}
            onChange={(v) => update({ type: v })}
            style={{ width: 140 }}
            aria-label="Project type"
            options={[
              { value: 'all', label: 'All types' },
              { value: 'backend_only', label: 'Backend' },
              { value: 'frontend_only', label: 'Frontend' },
              { value: 'fullstack', label: 'Full stack' },
            ]}
          />
          <Select
            value={filters.sort}
            onChange={(v) => update({ sort: v })}
            style={{ width: 130 }}
            aria-label="Order"
            options={[
              { value: 'newest', label: 'Newest' },
              { value: 'oldest', label: 'Oldest' },
              { value: 'longest', label: 'Longest' },
            ]}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="py-20 text-center"><Spin size="large" /></div>
      ) : shown.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          className="py-12"
          description={<span style={{ color: 'var(--ink-muted)' }}>{filtering ? 'No builds match these filters.' : 'Nothing has been built yet.'}</span>}
        >
          {filtering ? (
            <Button onClick={() => update(DEFAULT_FILTERS)}>Clear filters</Button>
          ) : (
            <Button type="primary" icon={<PlusIcon />} onClick={() => navigate('/create')}>New build</Button>
          )}
        </Empty>
      ) : (
        <>
          <ul className="build-list" aria-label="Builds">
            {pageItems.map((record) => {
              const meta = STATUS_META[record.status]
              const type = record.config?.project_type ? PROJECT_TYPE_META[record.config.project_type] : null
              const line = outcomeLine(record)
              return (
                <li key={record.task_id} className="build-row">
                  <span className="build-status" style={{ color: meta.color }} title={meta.label} aria-label={meta.label}>{meta.icon}</span>
                  <div className="min-w-0 flex-1">
                    <Link to={`/history/${record.task_id}`} className="build-name">{record.project_name}</Link>
                    <div className="build-meta">
                      {type && <span className="inline-flex items-center gap-1">{type.icon}{type.label}</span>}
                      {record.config?.docker_enabled && (
                        <Tooltip title={record.config.docker_image_name || 'Docker image'}>
                          <span className="inline-flex items-center gap-1"><CubeIcon />Docker</span>
                        </Tooltip>
                      )}
                      <span>{record.user_name}</span>
                      <Tooltip title={parseUtc(record.start_time).toLocaleString()}><span>{timeAgo(record.start_time)}</span></Tooltip>
                    </div>
                  </div>
                  <div className="build-verdict" style={{ color: meta.color }}>
                    {line.verdict}
                    {record.status === 'failed' && line.detail && <div className="build-meta truncate max-w-[280px]">{line.detail}</div>}
                  </div>
                  <div className="flex gap-1.5 flex-none">
                    {record.config && (
                      <Tooltip title="Rebuild with these settings">
                        <Button aria-label={`Rebuild ${record.project_name}`} icon={<ArrowClockwiseIcon />} onClick={() => rebuild(record)} />
                      </Tooltip>
                    )}
                    {record.status === 'completed' && (
                      <Tooltip title="Download output">
                        <Button
                          aria-label={`Download ${record.project_name}`}
                          icon={<DownloadSimpleIcon />}
                          loading={downloadingId === record.task_id}
                          onClick={() => download(record)}
                        />
                      </Tooltip>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
          {shown.length > PAGE_SIZE && (
            <div className="flex justify-end mt-4">
              <Pagination current={page} pageSize={PAGE_SIZE} total={shown.length} onChange={setPage} showSizeChanger={false} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
