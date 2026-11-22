import api from './client'

export type TokenScope = 'builds:read' | 'builds:write' | 'projects:read'

// What each scope opens, in the order the server lists them.
export const TOKEN_SCOPES: { value: TokenScope; label: string; description: string }[] = [
  { value: 'builds:read', label: 'Read builds', description: 'List and follow builds, read their logs and download their results' },
  { value: 'builds:write', label: 'Start builds', description: 'Start builds and cancel them' },
  { value: 'projects:read', label: 'Read projects', description: 'List projects and read their settings' },
]

export const EXPIRY_PRESETS = [7, 30, 90, 365] as const

// A token as listed. The token itself is never returned, only its first characters.
export interface ApiToken {
  id: number
  name: string
  prefix: string
  scopes: TokenScope[]
  owner: string
  created_at: string
  expires_at: string
  last_used_at: string | null
  revoked_at: string | null
  status: 'active' | 'expired' | 'revoked'
}

// The answer to creating one: the only time the token is shown.
export interface CreatedApiToken extends ApiToken {
  token: string
}

export interface ApiTokenCreate {
  name: string
  scopes: TokenScope[]
  expires_in_days: number
}

const BASE = '/tokens'

export const apiTokensApi = {
  list: async (everyone = false): Promise<ApiToken[]> => {
    const { data } = await api.get<ApiToken[]>(BASE, { params: everyone ? { everyone: true } : undefined })
    return data
  },
  create: async (payload: ApiTokenCreate): Promise<CreatedApiToken> => {
    const { data } = await api.post<CreatedApiToken>(BASE, payload)
    return data
  },
  revoke: async (id: number): Promise<void> => {
    await api.delete(`${BASE}/${id}`)
  },
}

export default apiTokensApi
