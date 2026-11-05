import { Form, Input, Switch, Row, Col, InputNumber, Collapse } from 'antd'
import { CloudServerOutlined, SettingOutlined } from '@ant-design/icons'
import { useCreateTask } from '../context'
import { SectionHeader } from '../ui'

export default function DockerStep() {
  const { projectType, dockerEnabled, hasBackend, dockerAdvKeys, setDockerAdvKeys } = useCreateTask()
  return (
    <>
      <h3 className="text-base font-semibold mb-2" style={{ color: 'var(--ink)' }}>Build a Docker image?</h3>
      <p className="text-sm mb-6" style={{ color: 'var(--ink-muted)' }}>
        {hasBackend
          ? 'The backend is compiled with Nuitka on the host first, then packed into a slim Docker image.'
          : 'The frontend is built, placed in a Docker container, and served by Nginx.'}
      </p>

      <div className="glass-card flex items-center gap-6 p-6">
        <CloudServerOutlined style={{ fontSize: 32, color: dockerEnabled ? 'var(--color-cyber-400)' : 'var(--ink-faint)' }} />
        <div className="flex-1">
          <div className="font-medium" style={{ color: 'var(--ink)' }}>Docker image output</div>
          <div className="text-sm mt-1" style={{ color: 'var(--ink-muted)' }}>
            {dockerEnabled
              ? 'The build is exported as a Docker image (.tar.gz).'
              : 'Only local files are produced — no Docker image.'}
          </div>
        </div>
        <Form.Item name="docker_enabled" valuePropName="checked" style={{ marginBottom: 0 }}>
          <Switch
            checkedChildren="On"
            unCheckedChildren="Off"
            style={{ transform: 'scale(1.3)' }}
          />
        </Form.Item>
      </div>

      {/* Docker Settings — shown when enabled */}
      {dockerEnabled && (
        <div className="glass-card p-5 mt-6">
          <SectionHeader icon={<CloudServerOutlined />} title="Docker settings" />
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="docker_image_name"
                label={<span style={{ color: 'var(--ink-muted)' }}>Image name</span>}
                tooltip="e.g. myapp:latest"
              >
                <Input placeholder="myapp:latest" className="input-field" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="docker_base_image"
                label={<span style={{ color: 'var(--ink-muted)' }}>Base image</span>}
              >
                <Input placeholder="python:3.13-slim" className="input-field" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="docker_expose_port"
                label={<span style={{ color: 'var(--ink-muted)' }}>Exposed port</span>}
              >
                <InputNumber min={1} max={65535} style={{ width: '100%' }} placeholder="8000" />
              </Form.Item>
            </Col>
          </Row>

          {projectType === 'frontend_only' && (
            <>
              <Row gutter={16}>
                <Col xs={24} md={16}>
                  <Form.Item
                    name="docker_api_proxy"
                    label={<span style={{ color: 'var(--ink-muted)' }}>API proxy URL</span>}
                    tooltip="Nginx reverse-proxies /api to this URL."
                  >
                    <Input placeholder="http://backend:8000" className="input-field" />
                  </Form.Item>
                </Col>
              </Row>

              <div className="mb-1 text-sm" style={{ color: 'var(--ink-muted)' }}>
                <SettingOutlined className="mr-2" />Nginx settings
              </div>
              <div className="text-xs mb-3" style={{ color: 'var(--ink-faint)', lineHeight: 1.6 }}>
                A frontend-only Docker image is served by Nginx. These are the knobs people tweak most often — the defaults are fine.
              </div>

              {/* The timeout is the setting people get wrong, and the
                  reason is that its name suggests a request duration cap
                  when it actually measures upstream silence. A rule of
                  thumb here is cheaper than another 504 investigation. */}
              <Collapse
                ghost
                size="small"
                className="mb-3"
                items={[
                  {
                    key: 'timeout-help',
                    label: (
                      <span className="text-xs text-cyber-300">
                        Do I need to adjust the timeout? (open for how to decide)
                      </span>
                    ),
                    children: (
                      <div className="text-xs" style={{ color: 'var(--ink-muted)', lineHeight: 1.8 }}>
                        <div className="mb-2">
                          The timeout measures <b style={{ color: 'var(--ink)' }}>the longest single silence from the backend</b>,
                          not how long the request runs in total. Every byte received resets the clock.
                        </div>
                        <table className="w-full" style={{ borderCollapse: 'collapse' }}>
                          <tbody>
                            {[
                              ['SSE / token-streaming LLM', 'No change — every token resets the timer'],
                              ['Speech-to-text, one-shot LLM', 'Raise it only if the worst case could exceed the default'],
                              ['WebSocket with heartbeat', 'No change — the heartbeat resets the timer'],
                              ['WebSocket without heartbeat', 'Raise it — must exceed the longest quiet period'],
                              ['Large file upload', 'No change — streaming mode keeps data flowing'],
                            ].map(([k, v]) => (
                              <tr key={k}>
                                <td
                                  className="pr-3 align-top"
                                  style={{ color: 'var(--ink)', borderTop: '1px solid var(--seam)', padding: '4px 8px 4px 0', whiteSpace: 'nowrap' }}
                                >
                                  {k}
                                </td>
                                <td style={{ borderTop: '1px solid var(--seam)', padding: '4px 0' }}>
                                  {v}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="mt-2 text-signal-400">
                          Note: if another reverse proxy sits in front of the container (an outer Nginx, a load balancer), that layer has its own timeout.
                          Changing only this one does nothing — every layer in the chain applies, and the smallest wins.
                          If it still drops at around 60 seconds after a rebuild, it's the outer layer.
                        </div>
                        <div className="mt-1" style={{ color: 'var(--ink-faint)' }}>
                          The most reliable fix is to have the backend send data periodically while it works (SSE: a ": keepalive" line every 10 seconds), which satisfies every proxy layer at once.
                        </div>
                      </div>
                    ),
                  },
                ]}
              />
              <Row gutter={16}>
                <Col xs={24} md={8}>
                  <Form.Item
                    name="nginx_client_max_body_size"
                    label={<span style={{ color: 'var(--ink-muted)' }}>Max upload size</span>}
                    tooltip="nginx client_max_body_size. 0 = unlimited. e.g. 50m, 1g, 0"
                    extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>Raise this when uploads hit a 413. 0 = unlimited.</span>}
                    validateTrigger={['onBlur', 'onChange']}
                    rules={[{ pattern: /^\d+[kKmMgG]?$/, message: 'e.g. 50m / 1g / 0' }]}
                  >
                    <Input placeholder="0 (unlimited)" className="input-field" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item
                    name="nginx_proxy_read_timeout"
                    label={<span style={{ color: 'var(--ink-muted)' }}>Max backend silence</span>}
                    tooltip="nginx proxy_read_timeout / proxy_send_timeout. This is an idle timeout, not a cap on total request length."
                    extra={
                      <span className="text-xs" style={{ color: 'var(--ink-faint)' }}>
                        How long the backend can send nothing before Nginx gives up — not a cap on total request time.
                        Raise it for slow-to-respond APIs like speech-to-text or one-shot LLMs, or you'll get a 504.
                      </span>
                    }
                    validateTrigger={['onBlur', 'onChange']}
                    rules={[{ pattern: /^\d+[smhdSMHD]?$/, message: 'e.g. 300s / 10m' }]}
                  >
                    <Input placeholder="300s" className="input-field" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item
                    name="nginx_streaming"
                    label={<span style={{ color: 'var(--ink-muted)' }}>Streaming mode</span>}
                    valuePropName="checked"
                    tooltip="Turns off Nginx request/response buffering (proxy_buffering off)."
                    extra={
                      <span className="text-xs" style={{ color: 'var(--ink-faint)' }}>
                        Keep this on for token-streamed LLM output (SSE) and long audio uploads.
                        Off, Nginx buffers the whole response before sending, and streaming stops working.
                      </span>
                    }
                  >
                    <Switch checkedChildren="On" unCheckedChildren="Off" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col xs={24} md={8}>
                  <Form.Item
                    name="nginx_gzip"
                    label={<span style={{ color: 'var(--ink-muted)' }}>gzip compression</span>}
                    valuePropName="checked"
                    tooltip="Enables gzip for CSS/JS/JSON/SVG to cut transfer size."
                    extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>Compresses static assets (recommended on).</span>}
                  >
                    <Switch checkedChildren="On" unCheckedChildren="Off" />
                  </Form.Item>
                </Col>
              </Row>
            </>
          )}

          <Collapse
            ghost
            activeKey={dockerAdvKeys}
            onChange={(keys) => setDockerAdvKeys(keys as string[])}
            items={[{
              key: 'docker-advanced',
              forceRender: true,
              label: (
                <span className="text-sm" style={{ color: 'var(--ink-muted)' }}>
                  <SettingOutlined className="mr-2" />Advanced: Node.js, custom RUN commands, environment variables
                </span>
              ),
              children: (
                <>
                  <Row gutter={16}>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="docker_install_node"
                        label={<span style={{ color: 'var(--ink-muted)' }}>Install Node.js</span>}
                        valuePropName="checked"
                        tooltip="Installs Node.js 20.x inside the Docker image."
                      >
                        <Switch checkedChildren="On" unCheckedChildren="Off" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item
                    name="docker_env_vars"
                    label={<span style={{ color: 'var(--ink-muted)' }}>Runtime Docker ENV</span>}
                    tooltip="One KEY=VALUE per line. Lines starting with # are skipped."
                  >
                    <Input.TextArea
                      rows={3}
                      placeholder={"GOOGLE_API_KEY=xxxx\nMY_SECRET=yyyy"}
                      className="input-field"
                      style={{ fontFamily: 'var(--font-mono)' }}
                    />
                  </Form.Item>
                  <Form.Item
                    name="docker_custom_commands"
                    label={<span style={{ color: 'var(--ink-muted)' }}>Custom commands</span>}
                    tooltip="One command per line. Only apt-get, pip, npm, mkdir, chmod, and similar are allowed."
                  >
                    <Input.TextArea
                      rows={3}
                      placeholder={"apt-get update && apt-get install -y --no-install-recommends curl"}
                      className="input-field"
                      style={{ fontFamily: 'var(--font-mono)' }}
                    />
                  </Form.Item>
                </>
              ),
            }]}
          />
        </div>
      )}
    </>
  )
}
