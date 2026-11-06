import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button, Input, Modal, Popconfirm, Spin, Tooltip, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectApi, taskApi } from '../api/client'
import { ArrowLeftIcon, CaretDownIcon, DownloadSimpleIcon, PencilSimpleIcon, RocketLaunchIcon, SlidersIcon, TrashIcon } from '../components/ui/icons'
import PageHeader from '../components/layout/PageHeader'
import { STATUS_META } from '../utils/statusMeta'
import { PROJECT_TYPE_META } from '../utils/projectTypeMeta'
import { parseUtc, timeAgo } from '../utils/time'
import { getErrorDetail } from '../utils/errors'
import { triggerUrlDownload } from '../utils/download'
import BuildVersionModal from './projects/BuildVersionModal'
import { groupByVersion, type VersionGroup } from './projects/versions'

function VersionRow({ group }: { group: VersionGroup }) {
  const [open, setOpen] = useState(false)
  const latest = group.builds[0]
  const meta = STATUS_META[latest.status]
  const download = async () => {
    if (!group.lastPassed) return
    try {
      triggerUrlDownload(await taskApi.getOutputDownloadUrl(group.lastPassed.task_id))
    } catch (err) {
      message.error(getErrorDetail(err, 'Could not download the output'))
    }
  }
  return (
    <li className="version-row">
      <div className="build-row !border-0">
        <span className="version-label">{group.version ?? 'No version'}</span>
        <div className="min-w-0 flex-1">
          <span style={{ color: meta.color }} className="font-semibold">{meta.label}</span>
          <div className="build-meta">
            <Tooltip title={parseUtc(latest.start_time).toLocaleString()}><span>{timeAgo(latest.start_time)}</span></Tooltip>
            <span>by {latest.user_name}</span>
            <span>{group.builds.length === 1 ? '1 build' : `${group.builds.length} builds`}</span>
          </div>
        </div>
        <div className="flex gap-1.5 flex-none">
          {group.lastPassed && (
            <Tooltip title={`Download the last passed build of ${group.version ?? 'this'}`}>
              <Button aria-label={`Download ${group.version ?? 'build'}`} icon={<DownloadSimpleIcon />} onClick={download} />
            </Tooltip>
          )}
          <Tooltip title={open ? 'Hide builds' : 'Show builds'}>
            <Button aria-label={`Builds of ${group.version ?? 'no version'}`} aria-expanded={open} icon={<CaretDownIcon />}
              onClick={() => setOpen((o) => !o)} className={open ? 'rotate-180' : ''} />
          </Tooltip>
        </div>
      </div>
      {open && (
        <ul className="version-builds">
          {group.builds.map((b) => (
            <li key={b.task_id}>
              <span style={{ color: STATUS_META[b.status].color }}>{STATUS_META[b.status].label}</span>
              <span className="build-meta">{parseUtc(b.start_time).toLocaleString()} by {b.user_name}</span>
              <Link to={`/history/${b.task_id}`}>Open</Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

/** One project: its versions, and building a new one. */
export default function ProjectPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: project, isLoading, isError } = useQuery({ queryKey: ['project', id], queryFn: () => projectApi.get(id) })
  const [building, setBuilding] = useState(false)

  const remove = useMutation({
    mutationFn: () => projectApi.remove(id),
    onSuccess: () => {
      message.success('Project deleted; its builds are still under Builds')
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate('/projects')
    },
    onError: (err) => message.error(getErrorDetail(err, 'Could not delete the project')),
  })

  const rename = () => {
    let name = project?.name ?? ''
    Modal.confirm({
      title: 'Rename the project',
      content: <Input defaultValue={name} aria-label="Project name" onChange={(e) => { name = e.target.value }} className="mt-3" />,
      okText: 'Rename',
      onOk: async () => {
        try {
          await projectApi.update(id, { name: name.trim() })
          message.success('Renamed')
          queryClient.invalidateQueries({ queryKey: ['project', id] })
          queryClient.invalidateQueries({ queryKey: ['projects'] })
        } catch (err) {
          message.error(getErrorDetail(err, 'Could not rename the project'))
          throw err
        }
      },
    })
  }

  if (isLoading) return <div className="py-16 text-center"><Spin /></div>
  if (isError || !project) {
    return (
      <div className="glass-card p-8 max-w-xl">
        <p className="m-0 mb-4" style={{ color: 'var(--ink-muted)' }}>This project does not exist, or was deleted.</p>
        <Button icon={<ArrowLeftIcon />} onClick={() => navigate('/projects')}>All projects</Button>
      </div>
    )
  }

  const type = PROJECT_TYPE_META[project.project_type]
  const groups = groupByVersion(project.history)
  const c = project.config
  const defaults: [string, string][] = [
    ['Type', type?.label ?? project.project_type],
    ...(project.project_type !== 'frontend_only'
      ? ([
          ['Packing', c.pack_mode === 'full' ? 'Full' : 'External'],
          ['Output', c.onefile === false ? 'A folder' : 'One file'],
          ['Python', !c.python_version || c.python_version === 'auto' ? 'Automatic' : c.python_version],
          ['Starts from', c.entry_point],
        ] as [string, string][])
      : []),
    ['Docker image', c.docker_enabled ? 'Yes' : 'No'],
    ...(project.source_type === 'git' ? ([['Branch or tag', c.git_ref || 'main']] as [string, string][]) : []),
  ]

  return (
    <div className="max-w-5xl">
      <Link to="/projects" className="inline-flex items-center gap-2 mb-3 text-sm" style={{ color: 'var(--ink-muted)' }}>
        <ArrowLeftIcon /> All projects
      </Link>
      <PageHeader
        title={project.name}
        lead={<span className="break-all">{type?.label} from {project.source}</span>}
        actions={
          <>
            {project.can_edit && (
              <>
                <Tooltip title="Rename"><Button aria-label="Rename the project" icon={<PencilSimpleIcon />} onClick={rename} /></Tooltip>
                <Popconfirm
                  title={`Delete ${project.name}?`}
                  description="Its builds stay under Builds; only the project goes."
                  okText="Delete"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => remove.mutate()}
                >
                  <Tooltip title="Delete"><Button aria-label="Delete the project" danger icon={<TrashIcon />} /></Tooltip>
                </Popconfirm>
              </>
            )}
            <Button icon={<SlidersIcon />} onClick={() => navigate(`/projects/${project.id}/settings`)}>Settings</Button>
            <Button type="primary" icon={<RocketLaunchIcon />} onClick={() => setBuilding(true)}>Build a new version</Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section aria-labelledby="versions">
          <h2 id="versions" className="text-[17px] font-semibold m-0 mb-3" style={{ color: 'var(--ink)' }}>Versions</h2>
          {groups.length === 0 ? (
            <p style={{ color: 'var(--ink-muted)' }}>Nothing has been built yet.</p>
          ) : (
            <ul className="build-list" aria-label="Versions">
              {groups.map((g) => <VersionRow key={g.version ?? '—'} group={g} />)}
            </ul>
          )}
        </section>
        <aside className="glass-card p-5 self-start" aria-labelledby="defaults">
          <h2 id="defaults" className="text-[15px] font-semibold m-0 mb-1" style={{ color: 'var(--ink)' }}>New versions are built with</h2>
          <p className="m-0 mb-3 text-sm" style={{ color: 'var(--ink-muted)' }}>Change them under <Link to={`/projects/${project.id}/settings`}>Settings</Link>, or for one build in the build dialog.</p>
          <dl className="project-defaults">
            {defaults.map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          <p className="m-0 mt-3 text-xs" style={{ color: 'var(--ink-faint)' }}>Created by {project.created_by} {timeAgo(project.created_at)}.</p>
        </aside>
      </div>

      {building && <BuildVersionModal projectId={project.id} open onClose={() => setBuilding(false)} />}
    </div>
  )
}
