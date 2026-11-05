/**
 * A short, human name for the device behind a session's User-Agent string
 * ("Chrome on Linux", "curl", "Python script") instead of the raw header.
 */
export function describeDevice(ua: string | null | undefined): string {
  if (!ua) return 'Unknown device'
  const s = ua.toLowerCase()
  if (s.startsWith('curl/')) return 'curl'
  if (s.includes('python-requests') || s.includes('python-urllib') || s.includes('httpx') || s.includes('aiohttp')) return 'Python script'
  if (s.startsWith('node') || s.includes('axios/') || s.includes('undici')) return 'Node.js script'
  if (s.startsWith('go-http-client')) return 'Go program'
  if (s.startsWith('mcp gate') || s.includes('mcp gate sso')) return 'MCP Gate sign-in'

  const browser = s.includes('edg/')
    ? 'Edge'
    : s.includes('headlesschrome')
      ? 'Headless Chrome'
      : s.includes('chrome/') || s.includes('crios/')
        ? 'Chrome'
        : s.includes('firefox/') || s.includes('fxios/')
          ? 'Firefox'
          : s.includes('safari/')
            ? 'Safari'
            : null
  const os = s.includes('iphone') || s.includes('ipad')
    ? 'iOS'
    : s.includes('android')
      ? 'Android'
      : s.includes('windows')
        ? 'Windows'
        : s.includes('mac os x') || s.includes('macintosh')
          ? 'macOS'
          : s.includes('linux') || s.includes('x11')
            ? 'Linux'
            : null
  if (browser && os) return `${browser} on ${os}`
  if (browser) return browser
  return ua.length > 40 ? `${ua.slice(0, 40)}…` : ua
}
