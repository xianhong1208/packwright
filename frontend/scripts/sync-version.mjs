// Copy [project].version from ../pyproject.toml (the single source of truth)
// into package.json and package-lock.json. Runs before every `npm run build`.
import { readFileSync, writeFileSync } from 'node:fs'

const pyproject = readFileSync(new URL('../../pyproject.toml', import.meta.url), 'utf8')
const project = pyproject.split(/^\[project\]\s*$/m)[1]?.split(/^\[/m)[0] ?? ''
const version = project.match(/^version\s*=\s*"([^"]+)"/m)?.[1]
if (!version) {
  console.error('[sync-version] no [project].version in pyproject.toml')
  process.exit(1)
}

for (const file of ['package.json', 'package-lock.json']) {
  const url = new URL(`../${file}`, import.meta.url)
  const data = JSON.parse(readFileSync(url, 'utf8'))
  const before = data.version
  data.version = version
  if (data.packages?.['']) data.packages[''].version = version
  writeFileSync(url, JSON.stringify(data, null, 2) + '\n')
  if (before !== version) console.log(`[sync-version] ${file} ${before} -> ${version}`)
}
