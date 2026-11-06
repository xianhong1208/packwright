import { Form, Input, Select, Switch, Button, Row, Col, Checkbox, Spin, Collapse } from 'antd'
import { ArrowsClockwiseIcon, CodeIcon, FolderIcon, GearIcon, WarningIcon } from '../../../components/ui/icons'

import { useCreateTask } from '../context'
import { SectionHeader } from '../ui'
import DetectedHint from './DetectedHint'
import { depGroupHint, depGroupPlaceholder } from '../depGroups'

const { Option } = Select

export default function BackendStep() {
  const {
    entryPoint,
    sourceType,
    pythonMismatch,
    hasBackend,
    fetchDirectories,
    projectPath,
    handleScanGitTree,
    renderDirTags,
    handleDirToggle,
    handleSelectAll,
    form,
    backendAdvKeys,
    setBackendAdvKeys,
    directories,
    selectedDirs,
    selectedDataDirs,
    setSelectedDataDirs,
    loadingDirs,
    dirError,
    analysis,
    cpuCount,
    pythonVersions,
    scanningTree,
    depGroups,
    loadingDepGroups,
    depGroupsRead,
  } = useCreateTask()
  return (
    <>
      {hasBackend && (
        <div className="glass-card p-5 mb-4">
          <SectionHeader icon={<CodeIcon />} title="Backend settings" />
          {/* Version mismatch is caught here rather than during the
              build. The same ABI detection already ran in preflight, but
              only after the user had filled in every step, queued, and
              waited — one project submitted a version its own .so files
              could not load 37 times that way. */}
          {pythonMismatch && (
            <div className="p-4 mb-4 rounded-lg border-l-2 border-signal-400 bg-signal-500/8">
              <div className="flex items-start gap-2">
                <WarningIcon style={{ color: 'var(--color-signal-400)', marginTop: 3 }} />
                <div className="flex-1">
                  <div className="text-sm text-signal-400">
                    This project's packages were compiled with <b>Python {pythonMismatch.detected}</b>,
                    but you chose <b>Python {pythonMismatch.chosen}</b>.
                  </div>
                  <div className="text-xs mt-1" style={{ color: 'var(--ink-muted)' }}>
                    Built this way, the binary raises ModuleNotFoundError on startup because it can't load the project's own .so files. This is the most common cause of failure.
                  </div>
                  <div className="text-xs mt-1 font-mono break-all" style={{ color: 'var(--ink-faint)' }}>
                    {pythonMismatch.detail}
                  </div>
                  <Button
                    size="small"
                    className="mt-2"
                    onClick={() => form.setFieldValue('python_version', 'auto')}
                  >
                    Switch to auto-detect
                  </Button>
                </div>
              </div>
            </div>
          )}
          {analysis?.detected_python?.inconsistent && (
            <div className="p-4 mb-4 rounded-lg border-l-2 border-alert-400 bg-alert-500/8">
              <div className="text-sm text-alert-400">
                This project's .venv contains packages built for several different Python versions.
              </div>
              <div className="text-xs mt-1" style={{ color: 'var(--ink-muted)' }}>
                Whichever version you pick, some packages will fail to load. Rebuild the .venv in the project directory (delete .venv, then run uv sync or pip install again), then come back to build.
              </div>
              <div className="text-xs mt-1 font-mono break-all" style={{ color: 'var(--ink-faint)' }}>
                {analysis.detected_python.detail}
              </div>
            </div>
          )}

          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="python_version"
                label={<span style={{ color: 'var(--ink-muted)' }}>Python version</span>}
                rules={[{ required: true }]}
                tooltip="Auto-detect reads the real Python version of the compiled packages (.so files) in the project's .venv and compiles to match — the most reliable way to avoid a version mismatch. Leave it on Auto unless you're sure."
                extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>Auto compiles to match the .so files in the project's .venv (recommended). Choosing a version by hand warns you on a mismatch.</span>}
              >
                <Select>
                  <Option value="auto">Auto-detect (recommended)</Option>
                  {pythonVersions.map((v) => (
                    <Option key={v} value={v}>Python {v}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="entry_point"
                extra={<DetectedHint field="entry_point" />}
                label={<span style={{ color: 'var(--ink-muted)' }}>Entry point</span>}
                tooltip="The main Python file to compile, relative to the project path."
                validateTrigger={['onBlur', 'onChange']}
                rules={[{ required: true }]}
              >
                <Input placeholder="main.py" className="input-field" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="output_name"
                label={<span style={{ color: 'var(--ink-muted)' }}>Binary name</span>}
                tooltip="Name of the compiled binary. Leave blank to derive it from the entry point."
              >
                <Input
                  placeholder={entryPoint ? entryPoint.replace(/\.py$/, '') : 'main'}
                  className="input-field"
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="pack_mode"
                label={<span style={{ color: 'var(--ink-muted)' }}>Nuitka pack mode</span>}
                tooltip="External (recommended): third-party packages go in a separate libs/ directory and compile faster. Full: every dependency is packed into a single binary, but Nuitka takes a very long time — hours on a large project."
                extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>When in doubt use External — fast and reliable. Full bundles everything into one binary but compiles for a very long time.</span>}
              >
                <Select>
                  <Option value="external">External (recommended, libs/)</Option>
                  <Option value="full">Full (very slow build)</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="onefile"
                label={<span style={{ color: 'var(--ink-muted)' }}>Single-file binary</span>}
                valuePropName="checked"
              >
                <Switch checkedChildren="On" unCheckedChildren="Off" />
              </Form.Item>
            </Col>
          </Row>

          {/* ── Dependency Group (PEP 735) — single-select from pyproject ── */}
          <Form.Item
            name="dependency_group"
            label={
              <span style={{ color: 'var(--ink-muted)' }}>
                Dependency group (uv <code className="text-[var(--ink)]">--group</code>)
              </span>
            }
            tooltip={
              <div>
                <div>Options are read from the <code>[dependency-groups]</code> section of pyproject.toml.</div>
                <div className="mt-2">At build time this becomes <code>uv sync --group &lt;name&gt;</code>.</div>
                <div className="mt-2">Typical use: pick the right PyTorch wheel per platform (rocm / cuda / cpu).</div>
                <div className="mt-2" style={{ color: 'var(--ink-muted)' }}>Single-select. Leave blank to omit the --group flag (the default).</div>
              </div>
            }
            extra={
              <span className="text-xs" style={{ color: 'var(--ink-faint)' }}>
                {depGroupHint({ count: depGroups.length, loading: loadingDepGroups, read: depGroupsRead, sourceType: sourceType === 'git' ? 'git' : 'local' })}
              </span>
            }
          >
            <Select
              allowClear
              placeholder={depGroupPlaceholder({ count: depGroups.length, read: depGroupsRead })}
              style={{ width: '100%' }}
              loading={loadingDepGroups}
              disabled={depGroups.length === 0}
              notFoundContent={loadingDepGroups ? <Spin size="small" /> : null}
              options={depGroups.map((g) => ({ label: g, value: g }))}
            />
          </Form.Item>

          {/* Advanced Backend Settings — default open on dedicated Backend step */}
          <Collapse
            ghost
            activeKey={backendAdvKeys}
            onChange={(keys) => setBackendAdvKeys(keys as string[])}
            items={[{
              key: 'backend-advanced',
              forceRender: true,
              label: (
                <span className="text-sm" style={{ color: 'var(--ink-muted)' }}>
                  <GearIcon className="mr-2" />Advanced: CPU parallelism, forced packages, extra directories
                </span>
              ),
              children: (
                <>
                  <Row gutter={16}>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="nuitka_jobs"
                        label={<span style={{ color: 'var(--ink-muted)' }}>CPU parallelism</span>}
                        tooltip="Number of parallel C-compile jobs. More is faster, but uses more memory. Auto uses every core when this build runs alone, and shares them with the other builds running at the same time."
                      >
                        <Select>
                          <Option value={0}>Auto</Option>
                          {cpuCount > 0 && (
                            <Option value={cpuCount}>All cores ({cpuCount})</Option>
                          )}
                          {[1, 2, 4, 8, 16, 32, 64, 128]
                            .filter((n) => n < cpuCount)
                            .map((n) => (
                              <Option key={n} value={n}>{n} cores</Option>
                            ))}
                        </Select>
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={16}>
                      <Form.Item
                        name="include_packages"
                        label={<span style={{ color: 'var(--ink-muted)' }}>Force-include packages</span>}
                        tooltip="Comma-separated. For packages Nuitka can't detect because they load dynamically or lazily."
                      >
                        <Input placeholder="e.g. litellm, openai" className="input-field" />
                      </Form.Item>
                    </Col>
                  </Row>

                  <Row gutter={16}>
                    <Col xs={24} md={12}>
                      <Form.Item
                        name="output_dir"
                        label={<span style={{ color: 'var(--ink-muted)' }}>Output directory</span>}
                        tooltip="Leave blank to use the default, 'dist'."
                      >
                        <Input placeholder="dist (default)" className="input-field" />
                      </Form.Item>
                    </Col>
                  </Row>

                  <div className="border-t border-[var(--seam)] my-3" />

                  {/* ── Nuitka compile optimization & diagnostics ── */}
                  <div className="mb-1 text-sm" style={{ color: 'var(--ink-muted)' }}>
                    <GearIcon className="mr-2" />Compile optimization and diagnostics
                  </div>
                  <div className="text-xs mb-3" style={{ color: 'var(--ink-faint)', lineHeight: 1.6 }}>
                    You can leave all three at their defaults. Reach for them to shrink the binary, or when the built binary can't find a file at runtime.
                  </div>
                  <Row gutter={16}>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="enable_anti_bloat"
                        label={<span style={{ color: 'var(--ink-muted)' }}>Shrink binary</span>}
                        valuePropName="checked"
                        tooltip="Enables Nuitka's anti-bloat plugin, which strips test code, docs, and dev-only imports bundled inside packages. Noticeable in Full mode; barely matters in External mode."
                        extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>Removes unused tests and docs to make the binary smaller (on by default).</span>}
                      >
                        <Switch checkedChildren="On" unCheckedChildren="Off" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="generate_report"
                        label={<span style={{ color: 'var(--ink-muted)' }}>Compilation report</span>}
                        valuePropName="checked"
                        tooltip="Writes compilation-report.xml to the output directory (included in the download). It lists whether each module was bundled — useful for debugging things missing at runtime."
                        extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>Use it to find what got left out when a package is missing.</span>}
                      >
                        <Switch checkedChildren="On" unCheckedChildren="Off" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="verify_after_build"
                        label={<span style={{ color: 'var(--ink-muted)' }}>Verify after build</span>}
                        valuePropName="checked"
                        tooltip="Launches the binary once after compiling to confirm it doesn't crash on startup for a missing package. A ModuleNotFoundError marks the task as failed and reports the missing module."
                        extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>Runs the binary once to confirm it starts (on by default, strongly recommended).</span>}
                      >
                        <Switch checkedChildren="On" unCheckedChildren="Off" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item
                    name="include_package_data"
                    label={<span style={{ color: 'var(--ink-muted)' }}>Force-include package data files</span>}
                    tooltip="Comma-separated package names. Bundles the non-.py data files inside a package (JSON, certificates, templates). Common ones (certifi, litellm, and so on) are detected automatically — list only the extras here."
                    extra={<span className="text-xs" style={{ color: 'var(--ink-faint)' }}>Only needed when a runtime FileNotFoundError is missing a data file that ships inside a package.</span>}
                  >
                    <Input placeholder="e.g. certifi, litellm" className="input-field" />
                  </Form.Item>

                  <div className="border-t border-[var(--seam)] my-3" />

                  {/* Extra Source Directories */}
                  <div className="mt-2">
                    <div className="flex items-center justify-between mb-3">
                      <label className="text-sm" style={{ color: 'var(--ink-muted)' }}>
                        <FolderIcon className="mr-2" />Source code to bundle (Python)
                      </label>
                      {directories.length > 0 && (
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={handleSelectAll}
                            className="text-xs text-cyber-400 hover:text-cyber-300"
                          >
                            {selectedDirs.length === directories.length ? 'Clear all' : 'Select all'}
                          </button>
                          <button
                            type="button"
                            onClick={() => { if (sourceType === 'git') { void handleScanGitTree() } else { void fetchDirectories(projectPath || '') } }}
                            className="p-1"
                            style={{ color: 'var(--ink-muted)' }}
                            title="Refresh"
                          >
                            <ArrowsClockwiseIcon />
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="text-xs mb-2" style={{ color: 'var(--ink-faint)', lineHeight: 1.6 }}>
                      These directories are compiled into the binary as Python source (importable). Pick the package and module directories other than your entry point.
                    </div>
                    <div className="rounded-lg border border-[var(--seam)] bg-void-950 p-4 min-h-[60px]">
                      {(loadingDirs || scanningTree) ? (
                        <div className="flex items-center justify-center py-2">
                          <Spin size="small" />
                          <span className="ml-2 text-sm" style={{ color: 'var(--ink-muted)' }}>Loading…</span>
                        </div>
                      ) : dirError ? (
                        <div className="text-alert-400 text-sm py-2">{dirError}</div>
                      ) : directories.length === 0 ? (
                        <div className="text-sm py-2" style={{ color: 'var(--ink-faint)' }}>
                          {projectPath ? 'No directories found' : 'Enter the project path first'}
                        </div>
                      ) : (
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                          {directories.map((dir) => (
                            <Checkbox
                              key={dir}
                              checked={selectedDirs.includes(dir)}
                              onChange={(e) => handleDirToggle(dir, e.target.checked)}
                            >
                              <span className="text-sm">{dir}</span>
                              {renderDirTags(dir)}
                            </Checkbox>
                          ))}
                        </div>
                      )}
                    </div>
                    {selectedDirs.length > 0 && (
                      <div className="mt-2 text-xs" style={{ color: 'var(--ink-muted)' }}>
                        Selected: {selectedDirs.join(', ')}
                      </div>
                    )}
                  </div>

                  {/* Data Directories */}
                  <div className="mt-4">
                    <div className="flex items-center justify-between mb-3">
                      <label className="text-sm" style={{ color: 'var(--ink-muted)' }}>
                        <FolderIcon className="mr-2" />Data directories (copied as-is next to the binary)
                      </label>
                    </div>
                    <div className="text-xs mb-2" style={{ color: 'var(--ink-faint)', lineHeight: 1.6 }}>
                      These directories aren't compiled in — they're copied unchanged next to the binary after the build. Good for static files, templates, and config.
                    </div>
                    <div className="rounded-lg border border-[var(--seam)] bg-void-950 p-4 min-h-[60px]">
                      {(loadingDirs || scanningTree) ? (
                        <div className="flex items-center justify-center py-2">
                          <Spin size="small" />
                        </div>
                      ) : directories.length === 0 ? (
                        <div className="text-sm py-2" style={{ color: 'var(--ink-faint)' }}>Enter the project path first</div>
                      ) : (
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                          {directories.map((dir) => (
                            <Checkbox
                              key={`data-${dir}`}
                              checked={selectedDataDirs.includes(dir)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedDataDirs((prev) => [...prev, dir])
                                } else {
                                  setSelectedDataDirs((prev) => prev.filter((d) => d !== dir))
                                }
                              }}
                            >
                              <span className="text-sm">{dir}</span>
                              {renderDirTags(dir)}
                            </Checkbox>
                          ))}
                        </div>
                      )}
                    </div>
                    {selectedDataDirs.length > 0 && (
                      <div className="mt-2 text-xs" style={{ color: 'var(--ink-muted)' }}>
                        Selected: {selectedDataDirs.join(', ')}
                      </div>
                    )}
                  </div>
                </>
              ),
            }]}
          />
        </div>
      )}
    </>
  )
}
