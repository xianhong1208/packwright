// Settings that come from the repository's packwright.toml (see fileFields.tsx).
import { createContext, useContext } from 'react'
import type { BuildConfig, FileKey, FileKeyRef } from '../../api/types'

export type FileFields = Partial<Record<keyof BuildConfig, FileKey | FileKeyRef>>

export const FileFieldsContext = createContext<FileFields | null>(null)

// Form field names that are not the setting's own name.
const ALIASES: Record<string, keyof BuildConfig> = { dependency_group: 'dependency_groups' }

/** Where packwright.toml sets the setting behind a form field, if it does. */
export function useFileField(name: string | undefined): FileKey | FileKeyRef | undefined {
  const fields = useContext(FileFieldsContext)
  if (!fields || !name) return undefined
  return fields[(ALIASES[name] ?? name) as keyof BuildConfig]
}
