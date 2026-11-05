import type { ReactNode } from 'react'

/**
 * The one page heading every screen uses: a title, a line saying what the page
 * is for, and the page's own actions on the right (they wrap under on phones).
 */
export default function PageHeader({ title, lead, actions }: { title: ReactNode; lead?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="min-w-0">
        <h1 className="page-title">{title}</h1>
        {lead && <p className="page-lead">{lead}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}
