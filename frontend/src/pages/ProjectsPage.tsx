import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Empty, Input, Spin, Tooltip } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { projectApi } from '../api/client'
import { MagnifyingGlassIcon, PlusIcon, RocketLaunchIcon } from '../components/ui/icons'
import PageHeader from '../components/layout/PageHeader'
import { STATUS_META } from '../utils/statusMeta'
import { PROJECT_TYPE_META } from '../utils/projectTypeMeta'
import { parseUtc, timeAgo } from '../utils/time'
import BuildVersionModal from './projects/BuildVersionModal'
import { sourceLabel } from './projects/versions'

/** Every project the team builds, the most recently built first. */
export default function ProjectsPage() {
  const navigate = useNavigate()
  const { data: projects, isLoading } = useQuery({ queryKey: ['projects'], queryFn: projectApi.list })
  const [query, setQuery] = useState('')
  const [building, setBuilding] = useState<number | null>(null)

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (projects ?? []).filter((p) => !q || p.name.toLowerCase().includes(q) || p.source.toLowerCase().includes(q))
  }, [projects, query])

  return (
    <div className="max-w-5xl">
      <PageHeader title="Projects" lead="The code your team builds, and every version built from it." />

      {(projects?.length ?? 0) > 0 && (
        <Input
          allowClear
          prefix={<MagnifyingGlassIcon />}
          placeholder="Search by name or source"
          aria-label="Search projects"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="!w-full sm:!w-80 mb-4"
        />
      )}

      {isLoading ? (
        <div className="py-16 text-center"><Spin /></div>
      ) : (projects?.length ?? 0) === 0 ? (
        <section className="glass-card p-6 sm:p-8" aria-labelledby="no-projects">
          <h2 id="no-projects" className="text-[17px] font-semibold m-0" style={{ color: 'var(--ink)' }}>No projects yet</h2>
          <p className="mt-1 mb-5 text-sm" style={{ color: 'var(--ink-muted)', maxWidth: '62ch' }}>
            A project is made the first time something is built. After that, its page lists every version, and a new
            version is one click.
          </p>
          <Button type="primary" icon={<PlusIcon />} onClick={() => navigate('/create')}>Build something</Button>
        </section>
      ) : shown.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span style={{ color: 'var(--ink-muted)' }}>No project matches “{query}”.</span>} />
      ) : (
        <ul className="build-list" aria-label="Projects">
          {shown.map((p) => {
            const type = PROJECT_TYPE_META[p.project_type]
            const latest = p.latest
            const meta = latest ? STATUS_META[latest.status] : null
            return (
              <li key={p.id} className="build-row">
                <span className="cred-mark" aria-hidden="true">{type?.icon}</span>
                <div className="min-w-0 flex-1">
                  <Link to={`/projects/${p.id}`} className="build-name">{p.name}</Link>
                  <div className="build-meta">
                    <span>{type?.label}</span>
                    <span className="truncate" title={p.source}>{sourceLabel(p)}</span>
                    <span>{p.builds === 1 ? '1 build' : `${p.builds} builds`}</span>
                  </div>
                </div>
                {latest && meta && (
                  <div className="project-latest">
                    {latest.version && <span className="version-chip">{latest.version}</span>}
                    <span style={{ color: meta.color }}>{meta.label}</span>
                    <Tooltip title={parseUtc(latest.start_time).toLocaleString()}>
                      <span className="build-meta">{timeAgo(latest.start_time)}</span>
                    </Tooltip>
                  </div>
                )}
                <Tooltip title="Build a new version">
                  <Button aria-label={`Build a new version of ${p.name}`} icon={<RocketLaunchIcon />} onClick={() => setBuilding(p.id)} />
                </Tooltip>
              </li>
            )
          })}
        </ul>
      )}

      {building !== null && <BuildVersionModal projectId={building} open onClose={() => setBuilding(null)} />}
    </div>
  )
}
