import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormInstance } from 'antd'

const DRAFT_STORAGE_KEY = 'createTaskDraft'
const SAVE_DEBOUNCE_MS = 800

/**
 * Fields that must never reach localStorage.
 *
 * `frontend_env_content` is a paste of the project's real .env, and
 * `docker_env_vars` the container's runtime environment — in practice both
 * carry JWT signing keys, database passwords and third-party API keys.
 * localStorage is readable by any script on the origin and survives logout, so
 * a convenience feature would otherwise turn the browser into a durable copy
 * of other systems' credentials.
 */
const NEVER_PERSIST = ['frontend_env_content', 'docker_env_vars'] as const

/** Drop the stored draft. Called on sign-out: a draft belongs to the user who
 *  typed it, and the next person to sign in on this browser must not see it. */
export function clearFormDraft(): void {
  try {
    localStorage.removeItem(DRAFT_STORAGE_KEY)
  } catch {
    /* storage unavailable: nothing to clear */
  }
}

export interface FormDraft {
  /** Timestamp of the last successful save, for a "draft saved" indicator. */
  savedAt: number | null
  /** Debounced save; safe to call on every keystroke. */
  scheduleSave: () => void
  /** Discard the stored draft and cancel any pending save. */
  clear: () => void
}

/**
 * Persist a long form to localStorage so an accidental navigation or an idle
 * logout does not throw the work away.
 *
 * Disabled entirely when `isRebuild` is true: that form is seeded from an
 * existing task, and restoring a stale draft over it would silently rebuild
 * something other than what the user asked to rebuild.
 */
function hasStoredDraft(): boolean {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) ?? 'null')
    return !!draft && typeof draft === 'object'
  } catch {
    return false
  }
}

export function useFormDraft(
  form: FormInstance,
  isRebuild: boolean,
  onCleared?: () => void,
): FormDraft {
  // A draft that will be restored on mount counts as saved from the start; set
  // here rather than from the restore effect (setState inside an effect cascades).
  const [savedAt, setSavedAt] = useState<number | null>(() =>
    !isRebuild && hasStoredDraft() ? Date.now() : null,
  )
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const restoredRef = useRef(false)

  const scheduleSave = useCallback(() => {
    if (isRebuild) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      try {
        const values = { ...form.getFieldsValue(true) } as Record<string, unknown>
        for (const field of NEVER_PERSIST) delete values[field]
        localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(values))
        setSavedAt(Date.now())
      } catch {
        // Quota exceeded or an unserialisable value — losing a draft is not
        // worth interrupting the user over.
      }
    }, SAVE_DEBOUNCE_MS)
  }, [isRebuild, form])

  const clear = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    try {
      localStorage.removeItem(DRAFT_STORAGE_KEY)
    } catch {
      /* ignore */
    }
    setSavedAt(null)
    onCleared?.()
  }, [onCleared])

  // Restore once, on mount, for new tasks only.
  useEffect(() => {
    if (isRebuild) return
    if (restoredRef.current) return
    restoredRef.current = true
    try {
      const raw = localStorage.getItem(DRAFT_STORAGE_KEY)
      if (!raw) return
      const draft = JSON.parse(raw)
      if (draft && typeof draft === 'object') {
        // Drafts saved before a field joined NEVER_PERSIST still hold it: strip
        // it and rewrite the stored copy rather than restoring it.
        for (const field of NEVER_PERSIST) delete draft[field]
        localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft))
        form.setFieldsValue(draft)
      }
    } catch {
      // A malformed draft must not block the form from loading.
    }
  }, [isRebuild, form])

  // Cancel a pending save on unmount so it cannot fire against a dead form.
  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    [],
  )

  return { savedAt, scheduleSave, clear }
}

export const __testing = { DRAFT_STORAGE_KEY, NEVER_PERSIST, SAVE_DEBOUNCE_MS }
