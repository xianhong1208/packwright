import { Form, Input, Select, Row, Col, Spin, AutoComplete, Radio } from 'antd'
import { CodeIcon, FolderIcon, GitBranchIcon, GlobeIcon, LinkIcon, ScanIcon, SquaresFourIcon, TagIcon } from '../../../components/ui/icons'

import { useCreateTask } from '../context'
import { SectionHeader } from '../ui'

const { Option } = Select

export default function BasicsStep() {
  const {
    sourceType,
    gitRefType,
    sourceModeRef,
    gitUrlRef,
    refSelectRef,
    hasBackend,
    form,
    directories,
    currentPath,
    gitRefs,
    loadingRefs,
    scanningTree,
    workspaceDir,
  } = useCreateTask()
  return (
    <>
      <div className="glass-card p-6 mb-4">
      <h3 className="text-base font-semibold mb-4" style={{ color: 'var(--ink)' }}>What do you want to build?</h3>

      <Form.Item
        name="project_name"
        label={<span style={{ color: 'var(--ink-muted)' }}>Project name</span>}
        rules={[{ required: true, message: 'Give the project a name' }]}
      >
        <Input placeholder="my-project" className="input-field" size="large" />
      </Form.Item>

      <Form.Item
        name="project_type"
        label={<span style={{ color: 'var(--ink-muted)' }}>Project type</span>}
        rules={[{ required: true }]}
      >
        <Select size="large">
          <Option value="backend_only">
            <CodeIcon className="mr-2" />Backend (Python)
          </Option>
          <Option value="frontend_only">
            <GlobeIcon className="mr-2" />Frontend (React, Vue, and so on)
          </Option>
          <Option value="fullstack">
            <SquaresFourIcon className="mr-2" />Full stack (frontend + backend)
          </Option>
        </Select>
      </Form.Item>

      {/* ── Source mode switcher ── */}
      <div ref={sourceModeRef}>
        <Form.Item
          name="source_type"
          label={<span style={{ color: 'var(--ink-muted)' }}>Source</span>}
          tooltip="Choose Local path to point at a project directory that already exists on the server, or Git URL to have the server clone a branch or tag for you."
          rules={[{ required: true }]}
        >
          <Radio.Group size="large" buttonStyle="solid">
            <Radio.Button value="local">
              <FolderIcon /> Local path
            </Radio.Button>
            <Radio.Button value="git">
              <LinkIcon /> Git URL
            </Radio.Button>
          </Radio.Group>
        </Form.Item>
      </div>

      {/* ── Local path mode ── */}
      {sourceType !== 'git' && (
        <Form.Item
          name="project_path"
          label={<span style={{ color: 'var(--ink-muted)' }}>Project path</span>}
          tooltip="Absolute path to the project on the server. The allowed roots are set by the operator (LOCAL_SOURCE_ROOTS)."
          validateTrigger={['onBlur', 'onChange']}
          rules={[
            { required: true, message: 'Enter the project path' },
            {
              pattern: /^\//,
              message: 'Enter an absolute path (starting with /)',
            },
          ]}
        >
          <Input
            placeholder="/path/to/your/project"
            className="input-field"
            size="large"
          />
        </Form.Item>
      )}

      </div>

      {/* ── Git URL mode ── */}
      {sourceType === 'git' && (
        <div className="glass-card p-5 mb-4">
          <SectionHeader icon={<LinkIcon />} title="Git source" />
          <div ref={gitUrlRef}>
            <Form.Item
              name="git_url"
              label={<span style={{ color: 'var(--ink-muted)' }}>Git URL</span>}
              tooltip="The access token is injected server-side from .env — do not put credentials in the URL."
              validateTrigger={['onBlur', 'onChange']}
              rules={[
                { required: true, message: 'Enter the Git URL' },
                {
                  pattern: /^https?:\/\//,
                  message: 'Only http and https URLs are supported',
                },
              ]}
            >
              <Input
                placeholder="https://gitlab.example.com/group/project.git"
                className="input-field"
                size="large"
                suffix={loadingRefs ? <Spin size="small" /> : null}
              />
            </Form.Item>
          </div>

          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="git_ref_type"
                label={<span style={{ color: 'var(--ink-muted)' }}>Ref type</span>}
              >
                <Radio.Group
                  onChange={() => {
                    // Reset selection so the user consciously re-picks
                    form.setFieldValue('git_ref', '')
                  }}
                >
                  <Radio.Button value="branch">
                    <GitBranchIcon /> Branch
                  </Radio.Button>
                  <Radio.Button value="tag">
                    <TagIcon /> Tag
                  </Radio.Button>
                </Radio.Group>
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <div ref={refSelectRef}>
                <Form.Item
                  name="git_ref"
                  label={
                    <span style={{ color: 'var(--ink-muted)' }}>
                      {gitRefType === 'tag' ? 'Tag' : 'Branch'}
                    </span>
                  }
                  tooltip={
                    gitRefType === 'tag'
                      ? 'A tag points at a fixed commit, so a later rebuild pulls the exact same code.'
                      : 'A branch keeps moving. Each rebuild pulls the latest commit on that branch.'
                  }
                  rules={[{ required: true, message: 'Pick or type a branch or tag' }]}
                >
                  {/* AutoComplete = single-select combobox: pick from
                      the fetched list OR type a custom ref freely.
                      Previously a <Select mode="tags"> which gave the
                      wrong multi-select feel. */}
                  <AutoComplete
                    className="input-field"
                    size="large"
                    allowClear
                    placeholder={
                      gitRefs.branches.length === 0 && gitRefs.tags.length === 0
                        ? 'Enter a Git URL to list available refs, or type one'
                        : gitRefType === 'tag'
                        ? 'Pick a tag, or type one'
                        : 'Pick a branch, or type one'
                    }
                    options={(gitRefType === 'tag' ? gitRefs.tags : gitRefs.branches).map(
                      (name) => ({ label: name, value: name }),
                    )}
                    filterOption={(input, option) =>
                      (option?.value as string)?.toLowerCase().includes(input.toLowerCase())
                    }
                    notFoundContent={loadingRefs ? <Spin size="small" /> : null}
                  />
                </Form.Item>
              </div>
            </Col>
          </Row>

          {/* Auto-scanned repo tree status (for extra_dirs / data_dirs) */}
          {hasBackend && (
            <div className="mb-3 text-xs" style={{ lineHeight: 1.6 }}>
              {scanningTree ? (
                <span style={{ color: 'var(--ink-muted)' }}>
                  <Spin size="small" />
                  <span className="ml-2">Scanning the repo structure…</span>
                </span>
              ) : currentPath.startsWith('git:') && directories.length > 0 ? (
                <span className="text-matrix-400">
                  <ScanIcon className="mr-1" />
                  Found {directories.length} directories. Pick the ones to bundle under Backend settings → Advanced below.
                </span>
              ) : currentPath.startsWith('git:') && directories.length === 0 ? (
                <span style={{ color: 'var(--ink-muted)' }}>
                  <ScanIcon className="mr-1" />
                  No selectable subdirectories in the repo root.
                </span>
              ) : (
                <span style={{ color: 'var(--ink-faint)' }}>
                  <ScanIcon className="mr-1" />
                  Once you pick a branch or tag, we scan for source and data directories to bundle, and read the pyproject dependency groups.
                </span>
              )}
            </div>
          )}

          {/* Git mode hint */}
          <div className="text-xs" style={{ color: 'var(--ink-faint)', lineHeight: 1.6 }}>
            <ScanIcon className="mr-1" />
            After the build starts, the server clones the repo into a per-task workspace{workspaceDir ? <> under <code style={{ color: 'var(--ink-muted)' }}>{workspaceDir}</code></> : null}.
            When it finishes, open the task detail page to see the repo-structure diagnostics.
            {hasBackend && (
              <>
                <br />
                <ScanIcon className="mr-1" />
                When <code style={{ color: 'var(--ink-muted)' }}>pyproject.toml</code>, <code style={{ color: 'var(--ink-muted)' }}>uv.lock</code>, or <code style={{ color: 'var(--ink-muted)' }}>requirements.txt</code> is present, it runs <code style={{ color: 'var(--ink-muted)' }}>uv sync --frozen</code> to build the <code style={{ color: 'var(--ink-muted)' }}>.venv</code>.
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}
