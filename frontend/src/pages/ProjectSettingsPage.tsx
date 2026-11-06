import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button, Form, Spin, Tabs, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectApi } from '../api/client'
import type { ProjectDetail } from '../api/types'
import { ArrowLeftIcon, FloppyDiskIcon } from '../components/ui/icons'
import PageHeader from '../components/layout/PageHeader'
import { getErrorDetail } from '../utils/errors'
import { useCreateTaskModel } from './createTask/useCreateTaskModel'
import { CreateTaskContext } from './createTask/context'
import { initialValues } from './createTask/initialValues'
import BasicsStep from './createTask/sections/BasicsStep'
import BackendStep from './createTask/sections/BackendStep'
import FrontendStep from './createTask/sections/FrontendStep'
import DockerStep from './createTask/sections/DockerStep'
import CommandPreview from './projects/CommandPreview'
import Notifications from './projects/Notifications'

/** A project's settings — what new versions are built with — as tabs. */
export default function ProjectSettingsPage() {
  const id = Number(useParams().projectId)
  const { data: project, isLoading } = useQuery({ queryKey: ['project', id], queryFn: () => projectApi.get(id) })
  if (isLoading || !project) return <div className="py-16 text-center"><Spin /></div>
  return <Settings project={project} />
}

function Settings({ project }: { project: ProjectDetail }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('general')
  const preset = useMemo(() => ({ projectName: project.name, config: project.config }), [project])

  const save = useMutation({
    mutationFn: (body: { name: string; config: ProjectDetail['config'] }) => projectApi.update(project.id, body),
    onSuccess: () => {
      message.success('Saved. New versions are built with these settings.')
      queryClient.invalidateQueries({ queryKey: ['project', project.id] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${project.id}`)
    },
    onError: (err) => message.error(getErrorDetail(err, 'Could not save the settings')),
  })

  const model = useCreateTaskModel({
    preset,
    purpose: 'settings',
    onSubmit: (request) => save.mutate({ name: request.project_name, config: request.config }),
  })
  const { form, hasBackend, showFrontendSettings, handleManualSubmit } = model

  const submit = async () => {
    try {
      await form.validateFields()
    } catch {
      message.error('Some settings need attention; the tabs show where.')
      return
    }
    void handleManualSubmit()
  }

  const items = [
    { key: 'general', label: 'General', children: <BasicsStep /> },
    ...(hasBackend ? [{ key: 'backend', label: 'Backend', children: <BackendStep /> }] : []),
    ...(showFrontendSettings ? [{ key: 'frontend', label: 'Frontend', children: <FrontendStep /> }] : []),
    { key: 'docker', label: 'Docker', children: <DockerStep /> },
    { key: 'commands', label: 'Commands', children: <CommandPreview /> },
    { key: 'notifications', label: 'Notifications', children: <Notifications projectId={project.id} canEdit={project.can_edit} /> },
  ]

  return (
    <CreateTaskContext.Provider value={model}>
      <div className="max-w-5xl">
        <Link to={`/projects/${project.id}`} className="inline-flex items-center gap-2 mb-3 text-sm" style={{ color: 'var(--ink-muted)' }}>
          <ArrowLeftIcon /> {project.name}
        </Link>
        <PageHeader title="Settings" lead="What new versions of this project are built with. One build can still change any of it." />
        <Form form={form} layout="vertical" initialValues={initialValues(preset)}>
          {/* Every tab stays mounted so a field on a hidden tab is still validated and saved. */}
          <Tabs activeKey={tab} onChange={setTab} items={items.map((i) => ({ ...i, forceRender: true }))} />
          {/* Notifications save as they change; the defaults bar is for the other tabs. */}
          <div className="settings-bar" hidden={tab === 'notifications'}>
            <span className="text-sm" style={{ color: 'var(--ink-faint)' }}>
              {project.can_edit ? 'Saved settings apply to the next build.' : `Only ${project.created_by} or a project manager can change these.`}
            </span>
            <Button type="primary" icon={<FloppyDiskIcon />} loading={save.isPending} disabled={!project.can_edit} onClick={submit}>
              Save as defaults
            </Button>
          </div>
        </Form>
      </div>
    </CreateTaskContext.Provider>
  )
}
