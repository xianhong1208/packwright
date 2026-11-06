import { Form, Input, Select, Button, Row, Col, AutoComplete } from 'antd'
import { DownloadSimpleIcon, GlobeIcon, ScanIcon } from '../../../components/ui/icons'

import { useCreateTask } from '../context'
import { SectionHeader } from '../ui'
import DetectedHint from './DetectedHint'

const { Option } = Select

export default function FrontendStep() {
  const {
    sourceType,
    showFrontendSettings,
    fetchEnvFiles,
    handleLoadEnv,
    detectFrontendConfig,
    handlePreviewGitFrontend,
    previewingFrontend,
    loadingEnv,
    detectingConfig,
    envFiles,
    loadingEnvFiles,
  } = useCreateTask()
  return (
    <>
      {showFrontendSettings && (
        <div className="glass-card p-5 mb-4">
          <SectionHeader
            icon={<GlobeIcon />}
            title="Frontend settings"
            tone="matrix"
            action={
              <Button
                size="small"
                icon={<ScanIcon />}
                loading={sourceType === 'git' ? previewingFrontend : detectingConfig}
                onClick={() => {
                  if (sourceType === 'git') { void handlePreviewGitFrontend() }
                  else { void detectFrontendConfig(false) }
                }}
              >
                Auto-detect
              </Button>
            }
          />
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="frontend_dir"
                extra={<DetectedHint field="frontend_dir" />}
                label={<span style={{ color: 'var(--ink-muted)' }}>Frontend directory</span>}
                tooltip="Use '.' for the project root. If the frontend lives in a subdirectory, enter its name, e.g. 'frontend'."
              >
                <Input placeholder=". (project root)" className="input-field" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="frontend_build_tool"
                extra={<DetectedHint field="frontend_build_tool" />}
                label={<span style={{ color: 'var(--ink-muted)' }}>Build tool</span>}
              >
                <Select>
                  <Option value="npm">npm</Option>
                  <Option value="yarn">yarn</Option>
                  <Option value="pnpm">pnpm</Option>
                  <Option value="bun">bun</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="frontend_build_command"
                extra={<DetectedHint field="frontend_build_command" />}
                label={<span style={{ color: 'var(--ink-muted)' }}>Build command</span>}
                tooltip="e.g. build, build:prod"
              >
                <Input placeholder="build" className="input-field" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="frontend_output_dir"
                extra={<DetectedHint field="frontend_output_dir" />}
                label={<span style={{ color: 'var(--ink-muted)' }}>Output directory</span>}
                tooltip="Where the frontend build lands, e.g. dist."
              >
                <Input placeholder="dist" className="input-field" />
              </Form.Item>
            </Col>
          </Row>

          <div className="border-t border-[var(--seam)] my-4" />
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm" style={{ color: 'var(--ink-muted)' }}>Frontend build env (.env)</span>
            <div className="flex gap-2">
              <Button
                size="small"
                icon={<ScanIcon />}
                loading={sourceType === 'git' ? previewingFrontend : loadingEnvFiles}
                onClick={() => {
                  if (sourceType === 'git') { void handlePreviewGitFrontend() }
                  else { void fetchEnvFiles() }
                }}
              >
                Scan
              </Button>
              <Button
                size="small"
                icon={<DownloadSimpleIcon />}
                loading={loadingEnv}
                onClick={handleLoadEnv}
              >
                {sourceType === 'git' ? 'Load from Git' : 'Load from project'}
              </Button>
            </div>
          </div>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="frontend_env_filename"
                label={<span style={{ color: 'var(--ink-muted)' }}>Env filename</span>}
                tooltip="e.g. .env.production (takes priority over .env at build time)."
                validateTrigger={['onBlur', 'onChange']}
                rules={[{ pattern: /^\.env(\.\w+)*$/, message: 'Must be .env or .env.*' }]}
              >
                <AutoComplete
                  placeholder=".env"
                  className="input-field"
                  options={envFiles.map((f) => ({ value: f, label: f }))}
                  filterOption={(input, option) =>
                    (option?.value as string)?.toLowerCase().includes(input.toLowerCase())
                  }
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="frontend_env_content"
            label={<span style={{ color: 'var(--ink-muted)' }}>Env content</span>}
            tooltip="Written into the frontend directory before the build. One KEY=VALUE per line."
          >
            <Input.TextArea
              rows={4}
              placeholder={"VITE_API_BASE_URL=https://api.example.com\nVITE_APP_TITLE=My App"}
              className="input-field"
              style={{ fontFamily: 'var(--font-mono)' }}
            />
          </Form.Item>
        </div>
      )}
    </>
  )
}
