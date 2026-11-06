import { CheckCircleIcon, CubeIcon, DownloadSimpleIcon, FolderIcon, GearIcon } from '../ui/icons'

const STEPS = [
  { Icon: FolderIcon, name: 'Your code', does: 'A folder on this server, or a Git repository.' },
  { Icon: GearIcon, name: 'Compiled', does: 'Python becomes a native program; a frontend is built.' },
  { Icon: CubeIcon, name: 'Packed', does: 'The libraries and files it needs go with it.' },
  { Icon: CheckCircleIcon, name: 'Checked', does: 'It is run once, to be sure it starts.' },
  { Icon: DownloadSimpleIcon, name: 'Yours', does: 'Download it, or take it as a Docker image.' },
]

/**
 * What a build does, for someone who has never run one: a parcel travels from
 * the code to the download and each step lights as it passes. Shown where a
 * first-time user lands (an empty home page, Quick build before a source).
 * With reduced motion the parcel is gone and every step is lit.
 */
export default function BuildFlow() {
  return (
    <div className="flow" role="img" aria-label="How a build goes: your code is compiled, packed with what it needs, checked, and handed back to you.">
      <span className="flow-parcel" aria-hidden="true" />
      <ol className="flow-steps" aria-hidden="true">
        {STEPS.map(({ Icon, name, does }, i) => (
          <li key={name} className="flow-step" style={{ ['--i' as string]: i }}>
            <span className="flow-node"><Icon /></span>
            <span className="flow-name">{name}</span>
            <span className="flow-does">{does}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
