import { describe, it, expect } from 'vitest'
import type { RepoDiagnosisCheck } from '../../api/types'
import { guessProject, nameFromSource, outputSentence } from './quickPlan'

const ok = (key: string, path: string): RepoDiagnosisCheck => ({ key, label: '', status: 'ok', path })
const missing = (key: string): RepoDiagnosisCheck => ({ key, label: '', status: 'warn', path: null })

describe('guessProject', () => {
  it('a Python entry point and a package.json make a full stack, frontend where package.json is', () => {
    expect(guessProject([ok('entry_point', 'app/main.py'), ok('package_json', 'frontend/package.json')]))
      .toEqual({ projectType: 'fullstack', entryPoint: 'app/main.py', frontendDir: 'frontend' })
  })
  it('a root package.json alone is a frontend built from the root', () => {
    expect(guessProject([missing('entry_point'), ok('package_json', 'package.json')]))
      .toEqual({ projectType: 'frontend_only', entryPoint: null, frontendDir: '.' })
  })
  it('Python without a usual entry point is still a backend; the entry point is left to the user', () => {
    expect(guessProject([missing('entry_point'), ok('pyproject', 'pyproject.toml'), missing('package_json')]))
      .toEqual({ projectType: 'backend_only', entryPoint: null, frontendDir: null })
  })
  it('says nothing when there is nothing to go on', () => {
    expect(guessProject([missing('entry_point'), missing('package_json'), ok('dockerfile', 'Dockerfile')]).projectType).toBeNull()
    expect(guessProject([]).projectType).toBeNull()
  })
})

describe('nameFromSource', () => {
  it.each([
    ['/srv/apps/hello-web/', 'hello-web'],
    ['https://github.com/acme/build-bot.git', 'build-bot'],
    ['git@gitlab.example.com:team/api-server.git', 'api-server'],
    ['  /data/Report Tool  ', 'Report Tool'],
  ])('%s → %s', (source, name) => {
    expect(nameFromSource(source)).toBe(name)
  })
})

describe('outputSentence', () => {
  it('follows packing and output for a backend', () => {
    expect(outputSentence({ backend: true, packMode: 'external', onefile: true })).toBe(
      'One executable, with its libraries in a libs/ folder beside it. It is run once to check it starts.')
    expect(outputSentence({ backend: true, packMode: 'full', onefile: true, verify: false })).toBe('One executable with everything inside it.')
    expect(outputSentence({ backend: true, packMode: 'full', onefile: false, verify: false })).toBe('A folder with the program and everything it needs.')
    expect(outputSentence({ backend: true, packMode: 'external', onefile: false, verify: false })).toBe('A folder with the program, and its libraries in libs/.')
  })
  it('mentions the Docker image, and has no executable for a frontend', () => {
    expect(outputSentence({ backend: false, docker: true })).toBe('The built files, ready to put behind a web server. A Docker image of it is made too.')
  })
})
