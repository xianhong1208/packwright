// The values the New build form starts from: a fresh build's defaults, or a stored
// config (a rebuild, a project's settings) with the fields older configs lack filled in.
import type { BuildConfig } from '../../api/types'

export interface Preset {
  projectName: string
  config: BuildConfig
}

export function initialValues(preset: Preset | null): Record<string, unknown> {
  if (preset) {
    const rebuildState = preset
    return {
      project_name: rebuildState.projectName,
      ...rebuildState.config,
      // Fall back for historical tasks that predate git support.
      // Spread comes first so these only fill when the config lacks them.
      source_type: rebuildState.config.source_type ?? 'local',
      git_url: rebuildState.config.git_url ?? '',
      git_ref: rebuildState.config.git_ref ?? '',
      git_ref_type: rebuildState.config.git_ref_type ?? 'branch',
      // Picker is single-select; collapse the historical array to its
      // first entry. The config still round-trips as a list on submit.
      dependency_group: rebuildState.config.dependency_groups?.[0],
      // Fall back for tasks that predate the Nuitka optimization fields.
      enable_anti_bloat: rebuildState.config.enable_anti_bloat ?? true,
      include_package_data: rebuildState.config.include_package_data ?? '',
      generate_report: rebuildState.config.generate_report ?? false,
      verify_after_build: rebuildState.config.verify_after_build ?? true,
      nginx_client_max_body_size: rebuildState.config.nginx_client_max_body_size ?? '0',
      nginx_proxy_read_timeout: rebuildState.config.nginx_proxy_read_timeout ?? '300s',
      nginx_streaming: rebuildState.config.nginx_streaming ?? true,
      nginx_gzip: rebuildState.config.nginx_gzip ?? true,
    }
  }
  return {
      project_type: 'backend_only',
      source_type: 'local',
      git_url: '',
      git_ref: '',
      git_ref_type: 'branch',
      python_version: 'auto',
      entry_point: 'main.py',
      output_dir: '',
      onefile: true,
      pack_mode: 'external',
      include_packages: '',
      dependency_group: undefined,
      frontend_dir: '.',
      frontend_build_tool: 'npm',
      frontend_build_command: 'build',
      frontend_output_dir: 'dist',
      frontend_env_filename: '.env',
      frontend_env_content: '',
      docker_base_image: 'python:3.13-slim',
      docker_expose_port: 8000,
      docker_custom_commands: '',
      docker_enabled: false,
      docker_install_node: false,
      docker_api_proxy: '',
      nginx_client_max_body_size: '0',
      nginx_proxy_read_timeout: '300s',
      nginx_streaming: true,
      nginx_gzip: true,
      nuitka_jobs: 0,
      enable_anti_bloat: true,
      include_package_data: '',
      generate_report: false,
      verify_after_build: true,
    }
}
