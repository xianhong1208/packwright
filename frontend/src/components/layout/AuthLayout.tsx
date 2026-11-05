import type { ReactNode } from 'react'
import { CheckOutlined } from '@ant-design/icons'

/**
 * What a build goes through, in the words the build pages use. The sign-in
 * screen shows it instead of artwork: it is the one thing Packwright does.
 * One stage is drawn "running" so the track reads the way it does on the bench.
 */
const STAGES: { name: string; does: string; state: 'done' | 'on' | 'todo' }[] = [
  { name: 'Preflight', does: 'Checks the path, the entry point and the Python version before anything compiles.', state: 'done' },
  { name: 'Compile', does: 'Nuitka turns the Python into a native executable; npm, pnpm or bun build the frontend.', state: 'done' },
  { name: 'Bundle', does: 'Dependencies and data directories go next to it, or inside it.', state: 'done' },
  { name: 'Verify', does: 'Runs the result once, so a missing module fails here and not on a customer\'s machine.', state: 'on' },
  { name: 'Image', does: 'Optionally wraps it in a Docker image you can download.', state: 'todo' },
]

/**
 * The frame for signing in, registering and recovering a password: the form on
 * a narrow strip on the left, the build track on the right (hidden on phones).
 */
export default function AuthLayout({ title, lead, children }: { title: ReactNode; lead?: ReactNode; children: ReactNode }) {
  return (
    <div className="auth">
      <main className="auth-side">
        <div className="auth-brand">
          <span className="auth-mark" aria-hidden="true">P</span>
          Packwright
        </div>
        <div className="auth-body">
          <h1 className="page-title">{title}</h1>
          {lead && <p className="page-lead">{lead}</p>}
          <div className="mt-8">{children}</div>
        </div>
        <p className="auth-foot">A self-hosted build server for Python and web projects.</p>
      </main>

      <aside className="auth-bench" aria-label="What a build goes through">
        <p className="auth-claim">
          A folder or a Git URL in.
          <br />
          Something you can ship out.
        </p>
        <ol className="auth-track">
          {STAGES.map((s) => (
            <li key={s.name} className="auth-stage" data-state={s.state}>
              <span className="auth-node" aria-hidden="true">{s.state === 'done' && <CheckOutlined />}</span>
              <div>
                <div className="auth-stage-name">{s.name}</div>
                <div className="auth-stage-does">{s.does}</div>
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  )
}
