// Settings that come from the repository's packwright.toml. The file wins over the
// project's saved settings, so on project settings those fields are read-only and
// say where they are changed. Only a build can know what the file sets (the file
// lives in the source), so this is what the project's latest build found.
import type { ReactNode } from 'react'
import { ConfigProvider, Form, Tag, Tooltip, type FormItemProps } from 'antd'
import type { BuildConfig, FileKeyRef } from '../../api/types'
import { FileTextIcon } from '../../components/ui/icons'
import { useFileField } from './fileFieldsContext'

/** "from packwright.toml", with the key and its line on hover. */
export function FromFileTag({ field }: { field: FileKeyRef }) {
  return (
    <Tooltip
      title={
        <div>
          <div>
            packwright.toml{field.line ? `, line ${field.line}` : ''}:
          </div>
          <code style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{field.text || field.key}</code>
          <div className="mt-2">Edit it in the repository. The project's own value applies when the file leaves it out.</div>
        </div>
      }
    >
      <Tag className="from-file-tag" icon={<FileTextIcon />} data-testid={`from-file-${field.key}`}>
        from packwright.toml
      </Tag>
    </Tooltip>
  )
}

function editHint(field: FileKeyRef): ReactNode {
  return (
    <span className="text-xs" style={{ color: 'var(--ink-faint)' }}>
      Set by <code>{field.key}</code>{field.line ? ` (line ${field.line})` : ''} in the repository's packwright.toml: edit it in the repo.
    </span>
  )
}

/**
 * Form.Item for a setting. When the setting comes from packwright.toml it is shown
 * read-only, labelled as such, with where to change it; otherwise it is a plain Form.Item.
 */
export function SettingItem(props: FormItemProps) {
  const name = typeof props.name === 'string' ? props.name : undefined
  const field = useFileField(name)
  if (!field || props.noStyle) {
    if (!field) return <Form.Item {...props} />
    return (
      <ConfigProvider componentDisabled>
        <Form.Item {...props} />
      </ConfigProvider>
    )
  }
  const label = props.label ? (
    <span className="inline-flex items-center gap-2 flex-wrap">
      {props.label}
      <FromFileTag field={field} />
    </span>
  ) : undefined
  return (
    <ConfigProvider componentDisabled>
      <Form.Item
        {...props}
        label={label}
        tooltip={undefined}
        extra={
          <>
            {!props.label && <FromFileTag field={field} />}
            {editHint(field)}
          </>
        }
      />
    </ConfigProvider>
  )
}

/** A block of controls for one setting (the folder pickers), read-only when the file sets it. */
export function FileLocked({ field: name, children }: { field: keyof BuildConfig; children: ReactNode }) {
  const field = useFileField(name)
  if (!field) return <>{children}</>
  return (
    <div data-file-locked={name}>
      <div className="mb-2 flex items-center gap-2 flex-wrap">
        <FromFileTag field={field} />
        {editHint(field)}
      </div>
      <ConfigProvider componentDisabled>
        <div aria-disabled="true" style={{ pointerEvents: 'none', opacity: 0.7 }}>
          {children}
        </div>
      </ConfigProvider>
    </div>
  )
}
