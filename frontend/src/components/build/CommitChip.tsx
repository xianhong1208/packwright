import { Tooltip, message } from 'antd'
import { GitCommitIcon } from '../ui/icons'
import { shortCommit } from '../../utils/buildOrigin'

/** The commit a Git build checked out: seven characters, the full id copied on click. */
export default function CommitChip({ sha }: { sha: string }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sha)
      message.success('Commit copied')
    } catch {
      message.error('Could not copy the commit')
    }
  }
  return (
    <Tooltip title={<span className="font-mono">{sha}</span>}>
      <button
        type="button"
        className="commit-chip"
        onClick={copy}
        aria-label={`Commit ${sha}, copy`}
      >
        <GitCommitIcon />
        {shortCommit(sha)}
      </button>
    </Tooltip>
  )
}
