import { describe, it, expect } from 'vitest'
import { describeDevice } from './device'

describe('describeDevice', () => {
  it.each([
    ['Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Chrome on Linux'],
    ['Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/131.0.0.0 Safari/537.36', 'Headless Chrome on Linux'],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0', 'Edge on Windows'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15', 'Safari on macOS'],
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0 Mobile/15E148 Safari/604.1', 'Chrome on iOS'],
    ['Mozilla/5.0 (Android 14; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0', 'Firefox on Android'],
    ['curl/8.5.0', 'curl'],
    ['Python-urllib/3.13', 'Python script'],
    ['python-requests/2.32.3', 'Python script'],
  ])('%s → %s', (ua, expected) => {
    expect(describeDevice(ua)).toBe(expected)
  })

  it('falls back to a shortened string, or says it does not know', () => {
    expect(describeDevice(null)).toBe('Unknown device')
    expect(describeDevice('SomeInternalAgent/1.0')).toBe('SomeInternalAgent/1.0')
    expect(describeDevice('x'.repeat(60))).toHaveLength(41)
  })
})
