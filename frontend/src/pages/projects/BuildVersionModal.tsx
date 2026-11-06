import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Input, Modal, Segmented, Select, Spin, Switch, message } from 'antd'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectApi, taskApi } from '../../api/client'
import type { ProjectDetail } from '../../api/types'
import { RocketLaunchIcon, WarningIcon } from '../../components/ui/icons'
import { getErrorDetail } from '../../utils/errors'
import { parseUtc } from '../../utils/time'
import { pickDefaultRef } from '../createTask/pythonVersion'
import { passedBefore } from './versions'

/**
 * Build a new version of a project: which code (a branch or tag, for Git), which
 * version it is (read from the code when it says), and the usual settings, which
 * start from the project's. Says so when that version already passed.
 */
export default function BuildVersionModal({ projectId, open, onClose }: { projectId: number; open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const { data: project } = useQuery({ queryKey: ['project', projectId], queryFn: () => projectApi.get(projectId), enabled: open })
  return (
    <Modal open={open} onCancel={onClose} footer={null} width={560} destroyOnHidden title={project ? `Build a new version of ${project.name}` : 'Build a new version'}>
      {project ? <Form project={project} onDone={(taskId) => navigate(`/task/${taskId}`)} onCancel={onClose} /> : <div className="py-10 text-center"><Spin /></div>}
    </Modal>
  )
}

function Form({ project, onDone, onCancel }: { project: ProjectDetail; onDone: (taskId: string) => void; onCancel: () => void }) {
  const git = project.source_type === 'git'
  const backend = project.project_type !== 'frontend_only'
  const [chosenRef, setRef] = useState<{ name: string; kind: 'branch' | 'tag' } | null>(null)
  // What the person typed; until then the field shows what the code says.
  const [typedVersion, setTypedVersion] = useState<string | null>(null)
  const [settings, setSettings] = useState({
    pack_mode: project.config.pack_mode ?? 'external',
    onefile: project.config.onefile ?? true,
    verify_after_build: project.config.verify_after_build ?? true,
    docker_enabled: project.config.docker_enabled ?? false,
  })

  const { data: refs, isLoading: loadingRefs } = useQuery({
    queryKey: ['gitRefs', project.source],
    queryFn: () => taskApi.listGitRefs(project.source),
    enabled: git,
  })
  // The ref to build: the one picked, else the project's, else main/master.
  const ref = chosenRef
    ?? (!git ? null
      : project.config.git_ref ? { name: project.config.git_ref, kind: project.config.git_ref_type }
        : refs ? { name: pickDefaultRef(refs, '') ?? '', kind: 'branch' as const } : null)

  // What version the code says it is: a tag is one; otherwise pyproject.toml or package.json.
  const { data: detected, isFetching: reading } = useQuery({
    queryKey: ['detectedVersion', project.source, ref?.name, ref?.kind],
    queryFn: async () => {
      if (!git) return (await taskApi.diagnoseRepo(project.source)).version ?? null
      if (ref?.kind === 'tag') return { value: ref.name, source: 'Git tag' }
      return (await taskApi.scanGitTree(project.source, ref!.name, 'branch')).version ?? null
    },
    enabled: !git || Boolean(ref?.name),
    retry: false,
  })
  const version = typedVersion ?? detected?.value ?? ''

  const already = passedBefore(project.history, version)

  const build = useMutation({
    mutationFn: () =>
      projectApi.build(project.id, {
        version: version.trim(),
        overrides: { ...settings, ...(git && ref ? { git_ref: ref.name, git_ref_type: ref.kind } : {}) },
      }),
    onSuccess: (task) => {
      message.success('Build started')
      onDone(task.id)
    },
    onError: (err) => message.error(getErrorDetail(err, 'Could not start the build')),
  })

  return (
    <div className="flex flex-col gap-5 pt-2">
      {git && (
        <label className="block">
          <span className="modal-label">Branch or tag</span>
          <Select
            className="w-full"
            showSearch
            loading={loadingRefs}
            value={ref?.name}
            aria-label="Branch or tag"
            onChange={(name, option) => setRef({ name, kind: (option as { kind: 'branch' | 'tag' }).kind })}
            options={[
              ...(refs?.branches ?? []).map((n) => ({ value: n, label: n, kind: 'branch' as const })),
              ...(refs?.tags ?? []).map((n) => ({ value: n, label: `${n} (tag)`, kind: 'tag' as const })),
            ]}
          />
        </label>
      )}

      <label className="block">
        <span className="modal-label">Version</span>
        <Input
          value={version}
          placeholder="1.2.0"
          aria-label="Version"
          onChange={(e) => setTypedVersion(e.target.value)}
        />
        <span className="modal-help">
          {reading
            ? 'Reading the version from the code…'
            : detected
              ? `Read from ${detected.source}. Change it if this build is another version.`
              : 'The code does not say. Type one, or leave it empty.'}
        </span>
      </label>

      {already && (
        <div className="notice" data-tone="warn" role="status">
          <WarningIcon />
          <span>
            {version.trim()} already passed on {parseUtc(already.start_time).toLocaleDateString()}, built by {already.user_name}.
            Building it again makes a second build of {version.trim()}. <Link to={`/history/${already.task_id}`}>Open that build</Link>
          </span>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {backend && (
          <div className="flex items-center justify-between gap-3">
            <span className="modal-label !mb-0">Packing</span>
            <Segmented value={settings.pack_mode} onChange={(v) => setSettings((s) => ({ ...s, pack_mode: v as 'external' | 'full' }))}
              options={[{ value: 'external', label: 'External' }, { value: 'full', label: 'Full' }]} aria-label="Packing" />
          </div>
        )}
        {backend && (
          <div className="flex items-center justify-between gap-3">
            <span className="modal-label !mb-0">Output</span>
            <Segmented value={settings.onefile} onChange={(v) => setSettings((s) => ({ ...s, onefile: v as boolean }))}
              options={[{ value: true, label: 'One file' }, { value: false, label: 'A folder' }]} aria-label="Output" />
          </div>
        )}
        {backend && (
          <div className="flex items-center justify-between gap-3">
            <span className="modal-label !mb-0">Check it starts</span>
            <Switch checked={settings.verify_after_build} onChange={(v) => setSettings((s) => ({ ...s, verify_after_build: v }))} aria-label="Check it starts" />
          </div>
        )}
        <div className="flex items-center justify-between gap-3">
          <span className="modal-label !mb-0">Docker image</span>
          <Switch checked={settings.docker_enabled} onChange={(v) => setSettings((s) => ({ ...s, docker_enabled: v }))} aria-label="Docker image" />
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <Button onClick={onCancel}>Cancel</Button>
        <Button
          type="primary"
          icon={<RocketLaunchIcon />}
          loading={build.isPending}
          disabled={git && !ref?.name}
          onClick={() => build.mutate()}
        >
          {version.trim() ? `Build ${version.trim()}` : 'Build'}
        </Button>
      </div>
    </div>
  )
}
