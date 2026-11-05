// The console's icons: Phosphor, wrapped so antd lays them out like its own.
//
// Each icon renders inside a <span class="anticon">: antd's Button, Tag, Menu and
// Dropdown space an icon from its label by that class, so a bare <svg> would sit
// flush against the text. Import icons from here, not from @phosphor-icons/react
// or @ant-design/icons, so every screen draws from the one set.
import type { CSSProperties } from 'react'
import type { Icon as PhosphorIcon, IconWeight } from '@phosphor-icons/react'
import {
  ArrowClockwiseIcon as ArrowClockwise,
  ArrowLeftIcon as ArrowLeft,
  ArrowLineDownIcon as ArrowLineDown,
  ArrowRightIcon as ArrowRight,
  ArrowUpIcon as ArrowUp,
  ArrowsClockwiseIcon as ArrowsClockwise,
  CheckIcon as Check,
  CheckCircleIcon as CheckCircle,
  CircleNotchIcon as CircleNotch,
  ClockIcon as Clock,
  ClockCounterClockwiseIcon as ClockCounterClockwise,
  CodeIcon as Code,
  CopyIcon as Copy,
  CrownIcon as Crown,
  CubeIcon as Cube,
  DesktopIcon as Desktop,
  DeviceMobileIcon as DeviceMobile,
  DeviceTabletIcon as DeviceTablet,
  DownloadSimpleIcon as DownloadSimple,
  FileZipIcon as FileZip,
  FolderIcon as Folder,
  GaugeIcon as Gauge,
  GearIcon as Gear,
  GitBranchIcon as GitBranch,
  GithubLogoIcon as GithubLogo,
  GitlabLogoIcon as GitlabLogo,
  GlobeIcon as Globe,
  HardDrivesIcon as HardDrives,
  HouseIcon as House,
  KeyIcon as Key,
  LinkIcon as Link,
  ListIcon as List,
  LockIcon as Lock,
  MagnifyingGlassIcon as MagnifyingGlass,
  MinusCircleIcon as MinusCircle,
  PauseIcon as Pause,
  PencilSimpleIcon as PencilSimple,
  PlusIcon as Plus,
  ProhibitIcon as Prohibit,
  QuestionIcon as Question,
  RocketLaunchIcon as RocketLaunch,
  ScanIcon as Scan,
  SealCheckIcon as SealCheck,
  ShieldCheckIcon as ShieldCheck,
  SignOutIcon as SignOut,
  SquaresFourIcon as SquaresFour,
  TagIcon as Tag,
  TrashIcon as Trash,
  UserIcon as User,
  UsersIcon as Users,
  WarningIcon as Warning,
  WarningCircleIcon as WarningCircle,
  XCircleIcon as XCircle,
} from '@phosphor-icons/react'

export interface IconProps {
  className?: string
  style?: CSSProperties
  /** Turn continuously (loading and running states). */
  spin?: boolean
  /** `duotone` marks the selected item in the rail. */
  weight?: IconWeight
  /** Give it a name only when it stands alone; next to a label it is decoration. */
  'aria-label'?: string
}

function wrap(Glyph: PhosphorIcon, name: string, defaults: Partial<IconProps> = {}) {
  const Wrapped = ({ className, style, spin = defaults.spin, weight = 'regular', 'aria-label': label }: IconProps) => (
    <span
      role="img"
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={['anticon', 'pw-icon', spin ? 'animate-spin' : '', className ?? ''].filter(Boolean).join(' ')}
      style={style}
    >
      <Glyph weight={weight} />
    </span>
  )
  Wrapped.displayName = name
  return Wrapped
}

export const ArrowClockwiseIcon = wrap(ArrowClockwise, 'ArrowClockwiseIcon')
export const ArrowLeftIcon = wrap(ArrowLeft, 'ArrowLeftIcon')
export const ArrowLineDownIcon = wrap(ArrowLineDown, 'ArrowLineDownIcon')
export const ArrowRightIcon = wrap(ArrowRight, 'ArrowRightIcon')
export const ArrowUpIcon = wrap(ArrowUp, 'ArrowUpIcon')
export const ArrowsClockwiseIcon = wrap(ArrowsClockwise, 'ArrowsClockwiseIcon')
export const CheckIcon = wrap(Check, 'CheckIcon')
export const CheckCircleIcon = wrap(CheckCircle, 'CheckCircleIcon')
export const ClockIcon = wrap(Clock, 'ClockIcon')
export const ClockCounterClockwiseIcon = wrap(ClockCounterClockwise, 'ClockCounterClockwiseIcon')
export const CodeIcon = wrap(Code, 'CodeIcon')
export const CopyIcon = wrap(Copy, 'CopyIcon')
export const CrownIcon = wrap(Crown, 'CrownIcon')
export const CubeIcon = wrap(Cube, 'CubeIcon')
export const DesktopIcon = wrap(Desktop, 'DesktopIcon')
export const DeviceMobileIcon = wrap(DeviceMobile, 'DeviceMobileIcon')
export const DeviceTabletIcon = wrap(DeviceTablet, 'DeviceTabletIcon')
export const DownloadSimpleIcon = wrap(DownloadSimple, 'DownloadSimpleIcon')
export const FileZipIcon = wrap(FileZip, 'FileZipIcon')
export const FolderIcon = wrap(Folder, 'FolderIcon')
export const GaugeIcon = wrap(Gauge, 'GaugeIcon')
export const GearIcon = wrap(Gear, 'GearIcon')
export const GitBranchIcon = wrap(GitBranch, 'GitBranchIcon')
export const GithubLogoIcon = wrap(GithubLogo, 'GithubLogoIcon')
export const GitlabLogoIcon = wrap(GitlabLogo, 'GitlabLogoIcon')
export const GlobeIcon = wrap(Globe, 'GlobeIcon')
export const HardDrivesIcon = wrap(HardDrives, 'HardDrivesIcon')
export const HouseIcon = wrap(House, 'HouseIcon')
export const KeyIcon = wrap(Key, 'KeyIcon')
export const LinkIcon = wrap(Link, 'LinkIcon')
export const ListIcon = wrap(List, 'ListIcon')
export const LockIcon = wrap(Lock, 'LockIcon')
export const MagnifyingGlassIcon = wrap(MagnifyingGlass, 'MagnifyingGlassIcon')
export const MinusCircleIcon = wrap(MinusCircle, 'MinusCircleIcon')
export const PauseIcon = wrap(Pause, 'PauseIcon')
export const PencilSimpleIcon = wrap(PencilSimple, 'PencilSimpleIcon')
export const PlusIcon = wrap(Plus, 'PlusIcon')
export const ProhibitIcon = wrap(Prohibit, 'ProhibitIcon')
export const QuestionIcon = wrap(Question, 'QuestionIcon')
export const RocketLaunchIcon = wrap(RocketLaunch, 'RocketLaunchIcon')
export const ScanIcon = wrap(Scan, 'ScanIcon')
export const SealCheckIcon = wrap(SealCheck, 'SealCheckIcon')
export const ShieldCheckIcon = wrap(ShieldCheck, 'ShieldCheckIcon')
export const SignOutIcon = wrap(SignOut, 'SignOutIcon')
export const SquaresFourIcon = wrap(SquaresFour, 'SquaresFourIcon')
export const TagIcon = wrap(Tag, 'TagIcon')
export const TrashIcon = wrap(Trash, 'TrashIcon')
export const UserIcon = wrap(User, 'UserIcon')
export const UsersIcon = wrap(Users, 'UsersIcon')
export const WarningIcon = wrap(Warning, 'WarningIcon')
export const WarningCircleIcon = wrap(WarningCircle, 'WarningCircleIcon')
export const XCircleIcon = wrap(XCircle, 'XCircleIcon')
/** The busy indicator: always turning. */
export const SpinnerIcon = wrap(CircleNotch, 'SpinnerIcon', { spin: true })
