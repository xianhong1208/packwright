// What the Dependency group field says about itself. Kept pure so each case is
// tested: the field used to ask for a project path after one had been entered,
// because "no groups" and "not read yet" looked the same.

/** Whether the project's pyproject.toml has been read for groups. */
export type DepGroupsRead = 'unread' | 'read' | 'failed'

export interface DepGroupState {
  count: number
  loading: boolean
  read: DepGroupsRead
  sourceType: 'local' | 'git'
}

export function depGroupHint({ count, loading, read, sourceType }: DepGroupState): string {
  if (loading) return 'Reading pyproject.toml…'
  if (count > 0) return `Read ${count} ${count === 1 ? 'group' : 'groups'} from pyproject.toml. Pick one, or leave it blank for the default dependencies.`
  if (read === 'read') return 'This project defines no dependency groups, so the default dependencies are installed.'
  if (read === 'failed') return 'Could not read this project’s pyproject.toml. The build installs the default dependencies.'
  return sourceType === 'git'
    ? 'Pick a branch or tag to read this repo’s pyproject.toml groups.'
    : 'Enter the project path to read the groups defined in pyproject.toml.'
}

export function depGroupPlaceholder({ count, read }: Pick<DepGroupState, 'count' | 'read'>): string {
  if (count > 0) return 'Pick a dependency group'
  return read === 'read' ? 'None defined' : 'Nothing to pick yet'
}
