import { CodeOutlined, GlobalOutlined, AppstoreOutlined, CloudServerOutlined } from '@ant-design/icons'
import { useCreateTask } from '../context'
import { SectionHeader, SummaryRow } from '../ui'
import type { ProjectType } from '../../../api/types'
import { PROJECT_TYPE_META } from '../../../utils/projectTypeMeta'

export default function ReviewStep() {
  const {
    projectType,
    dockerEnabled,
    sourceType,
    hasBackend,
    showFrontendSettings,
    form,
    selectedDirs,
    selectedDataDirs,
  } = useCreateTask()
  return (
    <>
      <h3 className="text-base font-semibold mb-2" style={{ color: 'var(--ink)' }}>Review your build</h3>
      <p className="text-sm mb-6" style={{ color: 'var(--ink-muted)' }}>Check everything below before you start the build.</p>

      {/* Project Info Summary */}
      <div className="glass-card p-5 mb-4">
        <SectionHeader icon={<AppstoreOutlined />} title="Project" />
        <SummaryRow label="Name" value={form.getFieldValue('project_name')} />
        <SummaryRow label="Type" value={projectType ? PROJECT_TYPE_META[projectType as ProjectType]?.label ?? projectType : projectType} />
        {sourceType === 'git' ? (
          <>
            <SummaryRow label="Source" value="Git URL" highlight />
            <SummaryRow label="Git URL" value={form.getFieldValue('git_url')} mono />
            <SummaryRow
              label={form.getFieldValue('git_ref_type') === 'tag' ? 'Tag' : 'Branch'}
              value={form.getFieldValue('git_ref')}
              mono
            />
          </>
        ) : (
          <>
            <SummaryRow label="Source" value="Local path" />
            <SummaryRow label="Project path" value={form.getFieldValue('project_path')} mono />
          </>
        )}
        {/* output_dir is a Nuitka/backend concept and only editable in
            the backend step; frontend-only builds use frontend_output_dir
            instead, so keep this row out of their summary. */}
        {hasBackend && (
          <SummaryRow label="Output directory" value={form.getFieldValue('output_dir') || 'dist'} mono />
        )}
      </div>

      {/* Backend Summary */}
      {hasBackend && (
        <div className="glass-card p-5 mb-4">
          <SectionHeader icon={<CodeOutlined />} title="Backend (Nuitka)" />
          <SummaryRow label="Python version" value={form.getFieldValue('python_version')} />
          <SummaryRow label="Entry point" value={form.getFieldValue('entry_point')} mono />
          <SummaryRow label="Binary name" value={form.getFieldValue('output_name') || (form.getFieldValue('entry_point') || 'main').replace(/\.py$/, '')} mono />
          <SummaryRow label="Nuitka mode" value={form.getFieldValue('pack_mode') === 'external' ? 'External (libs/, recommended)' : 'Full (very long build, 8h+)'} />
          <SummaryRow label="Single-file binary" value={form.getFieldValue('onefile') ? 'On' : 'Off'} />
          <SummaryRow label="Shrink binary" value={form.getFieldValue('enable_anti_bloat') ? 'On (anti-bloat)' : 'Off'} />
          <SummaryRow label="Verify after build" value={form.getFieldValue('verify_after_build') ? 'On (runs the binary once)' : 'Off'} highlight={form.getFieldValue('verify_after_build')} />
          {form.getFieldValue('generate_report') && (
            <SummaryRow label="Compilation report" value="compilation-report.xml will be generated" />
          )}
          {form.getFieldValue('include_package_data') && (
            <SummaryRow label="Package data files" value={form.getFieldValue('include_package_data')} mono />
          )}
          {(form.getFieldValue('nuitka_jobs') ?? 0) > 0 && (
            <SummaryRow label="CPU parallelism" value={`${form.getFieldValue('nuitka_jobs')} cores`} />
          )}
          {form.getFieldValue('include_packages') && (
            <SummaryRow label="Force-included packages" value={form.getFieldValue('include_packages')} mono />
          )}
          {(() => {
            const group = form.getFieldValue('dependency_group') as string | undefined
            return group ? (
              <SummaryRow
                label="Dependency group"
                value={`--group ${group}`}
                mono
                highlight
              />
            ) : null
          })()}
          {selectedDirs.length > 0 && (
            <SummaryRow label="Bundled source code" value={selectedDirs.join(', ')} mono />
          )}
          {selectedDataDirs.length > 0 && (
            <SummaryRow label="Data directories" value={selectedDataDirs.join(', ')} mono />
          )}
        </div>
      )}

      {/* Frontend Summary */}
      {showFrontendSettings && (
        <div className="glass-card p-5 mb-4">
          <SectionHeader icon={<GlobalOutlined />} title="Frontend" tone="matrix" />
          <SummaryRow label="Frontend directory" value={form.getFieldValue('frontend_dir') || '.'} mono />
          <SummaryRow label="Build tool" value={form.getFieldValue('frontend_build_tool') || 'npm'} />
          <SummaryRow label="Build command" value={`${form.getFieldValue('frontend_build_tool') || 'npm'} run ${form.getFieldValue('frontend_build_command') || 'build'}`} mono />
          <SummaryRow label="Output directory" value={form.getFieldValue('frontend_output_dir') || 'dist'} mono />
          {form.getFieldValue('frontend_env_content') && (
            <SummaryRow label="Env filename" value={form.getFieldValue('frontend_env_filename') || '.env'} mono />
          )}
          {form.getFieldValue('frontend_env_content') && (
            <div className="flex py-1.5">
              <span className="text-sm w-36 flex-shrink-0" style={{ color: 'var(--ink-faint)' }}>Env content</span>
              <pre className="text-sm font-mono whitespace-pre-wrap m-0 flex-1 bg-void-950 rounded px-2 py-1" style={{ color: 'var(--ink)', maxHeight: 120, overflow: 'auto' }}>
                {form.getFieldValue('frontend_env_content')}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Docker Summary */}
      <div className="glass-card p-5 mb-4">
        <SectionHeader icon={<CloudServerOutlined />} title="Docker" />
        <SummaryRow label="Docker enabled" value={dockerEnabled ? 'Yes' : 'No'} highlight={dockerEnabled} />
        {dockerEnabled && (
          <>
            <SummaryRow label="Image name" value={form.getFieldValue('docker_image_name') || '(auto)'} mono />
            <SummaryRow label="Base image" value={form.getFieldValue('docker_base_image') || 'python:3.13-slim'} mono />
            <SummaryRow label="Exposed port" value={form.getFieldValue('docker_expose_port') || 8000} />
            {projectType === 'frontend_only' && form.getFieldValue('docker_api_proxy') && (
              <SummaryRow label="API proxy" value={form.getFieldValue('docker_api_proxy')} mono />
            )}
            {projectType === 'frontend_only' && (
              <>
                <SummaryRow
                  label="Max upload"
                  value={(form.getFieldValue('nginx_client_max_body_size') || '0') === '0'
                    ? '0 (unlimited)'
                    : form.getFieldValue('nginx_client_max_body_size')}
                  mono
                />
                <SummaryRow label="Proxy timeout" value={form.getFieldValue('nginx_proxy_read_timeout') || '300s'} mono />
                <SummaryRow label="Streaming mode" value={form.getFieldValue('nginx_streaming') === false ? 'Off (Nginx buffers the whole response)' : 'On'} />
                <SummaryRow label="gzip compression" value={form.getFieldValue('nginx_gzip') ? 'On' : 'Off'} />
              </>
            )}
            {form.getFieldValue('docker_install_node') && (
              <SummaryRow label="Install Node.js" value="Yes" />
            )}
            {form.getFieldValue('docker_env_vars') && (
              <div className="flex py-1.5">
                <span className="text-sm w-36 flex-shrink-0" style={{ color: 'var(--ink-faint)' }}>ENV variables</span>
                <pre className="text-sm font-mono whitespace-pre-wrap m-0 flex-1 bg-void-950 rounded px-2 py-1" style={{ color: 'var(--ink)', maxHeight: 100, overflow: 'auto' }}>
                  {form.getFieldValue('docker_env_vars')}
                </pre>
              </div>
            )}
            {form.getFieldValue('docker_custom_commands') && (
              <div className="flex py-1.5">
                <span className="text-sm w-36 flex-shrink-0" style={{ color: 'var(--ink-faint)' }}>Custom commands</span>
                <pre className="text-sm font-mono whitespace-pre-wrap m-0 flex-1 bg-void-950 rounded px-2 py-1" style={{ color: 'var(--ink)', maxHeight: 100, overflow: 'auto' }}>
                  {form.getFieldValue('docker_custom_commands')}
                </pre>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
