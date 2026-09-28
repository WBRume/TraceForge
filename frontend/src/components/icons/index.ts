import { h, defineComponent, type Component } from 'vue'
import {
  AdjustmentsHorizontalIcon as RawAdjustmentsHorizontalIcon,
  ArchiveBoxIcon as RawArchiveBoxIcon,
  ArrowDownIcon as RawArrowDownIcon,
  ArrowDownOnSquareIcon as RawArrowDownOnSquareIcon,
  ArrowDownTrayIcon as RawArrowDownTrayIcon,
  ArrowLeftIcon as RawArrowLeftIcon,
  ArrowPathIcon as RawArrowPathIcon,
  ArrowRightIcon as RawArrowRightIcon,
  ArrowRightOnRectangleIcon as RawArrowRightOnRectangleIcon,
  ArrowTopRightOnSquareIcon as RawArrowTopRightOnSquareIcon,
  ArrowTrendingUpIcon as RawArrowTrendingUpIcon,
  ArrowUpTrayIcon as RawArrowUpTrayIcon,
  ArrowUturnLeftIcon as RawArrowUturnLeftIcon,
  ArrowsPointingInIcon as RawArrowsPointingInIcon,
  ArrowsPointingOutIcon as RawArrowsPointingOutIcon,
  ArrowsRightLeftIcon as RawArrowsRightLeftIcon,
  BeakerIcon as RawBeakerIcon,
  BellIcon as RawBellIcon,
  BoltIcon as RawBoltIcon,
  BookOpenIcon as RawBookOpenIcon,
  BookmarkIcon as RawBookmarkIcon,
  BookmarkSlashIcon as RawBookmarkSlashIcon,
  BookmarkSquareIcon as RawBookmarkSquareIcon,
  BriefcaseIcon as RawBriefcaseIcon,
  BugAntIcon as RawBugAntIcon,
  BuildingLibraryIcon as RawBuildingLibraryIcon,
  CalendarDaysIcon as RawCalendarDaysIcon,
  ChartBarIcon as RawChartBarIcon,
  ChatBubbleLeftEllipsisIcon as RawChatBubbleLeftEllipsisIcon,
  ChatBubbleLeftRightIcon as RawChatBubbleLeftRightIcon,
  CheckBadgeIcon as RawCheckBadgeIcon,
  CheckCircleIcon as RawCheckCircleIcon,
  CheckIcon as RawCheckIcon,
  ChevronDownIcon as RawChevronDownIcon,
  ChevronLeftIcon as RawChevronLeftIcon,
  ChevronRightIcon as RawChevronRightIcon,
  CircleStackIcon as RawCircleStackIcon,
  ClipboardDocumentIcon as RawClipboardDocumentIcon,
  ClipboardDocumentListIcon as RawClipboardDocumentListIcon,
  ClockIcon as RawClockIcon,
  CloudArrowUpIcon as RawCloudArrowUpIcon,
  CodeBracketIcon as RawCodeBracketIcon,
  CodeBracketSquareIcon as RawCodeBracketSquareIcon,
  Cog6ToothIcon as RawCog6ToothIcon,
  CommandLineIcon as RawCommandLineIcon,
  ComputerDesktopIcon as RawComputerDesktopIcon,
  CpuChipIcon as RawCpuChipIcon,
  CubeIcon as RawCubeIcon,
  CurrencyDollarIcon as RawCurrencyDollarIcon,
  CursorArrowRaysIcon as RawCursorArrowRaysIcon,
  DocumentArrowUpIcon as RawDocumentArrowUpIcon,
  DocumentCheckIcon as RawDocumentCheckIcon,
  DocumentDuplicateIcon as RawDocumentDuplicateIcon,
  DocumentIcon as RawDocumentIcon,
  DocumentMagnifyingGlassIcon as RawDocumentMagnifyingGlassIcon,
  DocumentMinusIcon as RawDocumentMinusIcon,
  DocumentPlusIcon as RawDocumentPlusIcon,
  DocumentTextIcon as RawDocumentTextIcon,
  EllipsisHorizontalIcon as RawEllipsisHorizontalIcon,
  EnvelopeIcon as RawEnvelopeIcon,
  ExclamationCircleIcon as RawExclamationCircleIcon,
  ExclamationTriangleIcon as RawExclamationTriangleIcon,
  EyeIcon as RawEyeIcon,
  EyeSlashIcon as RawEyeSlashIcon,
  FolderIcon as RawFolderIcon,
  FolderOpenIcon as RawFolderOpenIcon,
  FolderPlusIcon as RawFolderPlusIcon,
  GlobeAltIcon as RawGlobeAltIcon,
  HashtagIcon as RawHashtagIcon,
  HeartIcon as RawHeartIcon,
  InboxIcon as RawInboxIcon,
  InformationCircleIcon as RawInformationCircleIcon,
  LanguageIcon as RawLanguageIcon,
  LightBulbIcon as RawLightBulbIcon,
  LinkIcon as RawLinkIcon,
  LinkSlashIcon as RawLinkSlashIcon,
  LockClosedIcon as RawLockClosedIcon,
  MagnifyingGlassIcon as RawMagnifyingGlassIcon,
  MinusCircleIcon as RawMinusCircleIcon,
  MinusIcon as RawMinusIcon,
  NumberedListIcon as RawNumberedListIcon,
  PaperAirplaneIcon as RawPaperAirplaneIcon,
  PauseCircleIcon as RawPauseCircleIcon,
  PencilIcon as RawPencilIcon,
  PencilSquareIcon as RawPencilSquareIcon,
  PhotoIcon as RawPhotoIcon,
  PlayIcon as RawPlayIcon,
  PlusIcon as RawPlusIcon,
  PowerIcon as RawPowerIcon,
  QuestionMarkCircleIcon as RawQuestionMarkCircleIcon,
  QueueListIcon as RawQueueListIcon,
  RocketLaunchIcon as RawRocketLaunchIcon,
  ScissorsIcon as RawScissorsIcon,
  ServerIcon as RawServerIcon,
  ServerStackIcon as RawServerStackIcon,
  ShareIcon as RawShareIcon,
  ShieldCheckIcon as RawShieldCheckIcon,
  ShieldExclamationIcon as RawShieldExclamationIcon,
  SignalIcon as RawSignalIcon,
  SparklesIcon as RawSparklesIcon,
  Square2StackIcon as RawSquare2StackIcon,
  Square3Stack3DIcon as RawSquare3Stack3DIcon,
  Squares2X2Icon as RawSquares2X2Icon,
  StarIcon as RawStarIcon,
  StopIcon as RawStopIcon,
  SwatchIcon as RawSwatchIcon,
  TableCellsIcon as RawTableCellsIcon,
  TagIcon as RawTagIcon,
  TrashIcon as RawTrashIcon,
  TvIcon as RawTvIcon,
  UserIcon as RawUserIcon,
  UsersIcon as RawUsersIcon,
  VideoCameraIcon as RawVideoCameraIcon,
  WrenchIcon as RawWrenchIcon,
  WrenchScrewdriverIcon as RawWrenchScrewdriverIcon,
  XCircleIcon as RawXCircleIcon,
  XMarkIcon as RawXMarkIcon,
} from '@heroicons/vue/24/outline'

import GitBranchIconComponent from './GitBranchIcon.vue'
import GitPullRequestIconComponent from './GitPullRequestIcon.vue'
import GitCommitIconComponent from './GitCommitIcon.vue'
import GithubIconComponent from './GithubIcon.vue'

export function wrapIcon(IconComponent: Component, defaultName?: string): Component {
  return defineComponent({
    name: defaultName || (IconComponent as any).name || 'HeroiconWrapper',
    props: {
      size: [Number, String],
      strokeWidth: [Number, String],
      'stroke-width': [Number, String],
    },
    setup(props, { attrs, slots }) {
      return () => {
        const extraStyle: Record<string, string> = {}
        const extraAttrs: Record<string, any> = {}
        const s = props.size
        if (s !== undefined && s !== null && s !== '') {
          const px = typeof s === 'number' ? `${s}px` : (s.endsWith('px') || s.endsWith('rem') || s.endsWith('em') ? s : `${s}px`)
          extraStyle.width = px
          extraStyle.height = px
        }
        const sw = props.strokeWidth ?? props['stroke-width']
        if (sw !== undefined && sw !== null && sw !== '') {
          extraAttrs['stroke-width'] = String(sw)
        }
        return h(IconComponent, {
          style: extraStyle,
          ...extraAttrs,
          ...attrs,
        }, slots)
      }
    },
  })
}

// Canonical Heroicons 24/outline wrapped components
export const AdjustmentsHorizontalIcon = wrapIcon(RawAdjustmentsHorizontalIcon, 'AdjustmentsHorizontalIcon')
export const ArchiveBoxIcon = wrapIcon(RawArchiveBoxIcon, 'ArchiveBoxIcon')
export const ArrowDownIcon = wrapIcon(RawArrowDownIcon, 'ArrowDownIcon')
export const ArrowDownOnSquareIcon = wrapIcon(RawArrowDownOnSquareIcon, 'ArrowDownOnSquareIcon')
export const ArrowDownTrayIcon = wrapIcon(RawArrowDownTrayIcon, 'ArrowDownTrayIcon')
export const ArrowLeftIcon = wrapIcon(RawArrowLeftIcon, 'ArrowLeftIcon')
export const ArrowPathIcon = wrapIcon(RawArrowPathIcon, 'ArrowPathIcon')
export const ArrowRightIcon = wrapIcon(RawArrowRightIcon, 'ArrowRightIcon')
export const ArrowRightOnRectangleIcon = wrapIcon(RawArrowRightOnRectangleIcon, 'ArrowRightOnRectangleIcon')
export const ArrowTopRightOnSquareIcon = wrapIcon(RawArrowTopRightOnSquareIcon, 'ArrowTopRightOnSquareIcon')
export const ArrowTrendingUpIcon = wrapIcon(RawArrowTrendingUpIcon, 'ArrowTrendingUpIcon')
export const ArrowUpTrayIcon = wrapIcon(RawArrowUpTrayIcon, 'ArrowUpTrayIcon')
export const ArrowUturnLeftIcon = wrapIcon(RawArrowUturnLeftIcon, 'ArrowUturnLeftIcon')
export const ArrowsPointingInIcon = wrapIcon(RawArrowsPointingInIcon, 'ArrowsPointingInIcon')
export const ArrowsPointingOutIcon = wrapIcon(RawArrowsPointingOutIcon, 'ArrowsPointingOutIcon')
export const ArrowsRightLeftIcon = wrapIcon(RawArrowsRightLeftIcon, 'ArrowsRightLeftIcon')
export const BeakerIcon = wrapIcon(RawBeakerIcon, 'BeakerIcon')
export const BellIcon = wrapIcon(RawBellIcon, 'BellIcon')
export const BoltIcon = wrapIcon(RawBoltIcon, 'BoltIcon')
export const BookOpenIcon = wrapIcon(RawBookOpenIcon, 'BookOpenIcon')
export const BookmarkIcon = wrapIcon(RawBookmarkIcon, 'BookmarkIcon')
export const BookmarkSlashIcon = wrapIcon(RawBookmarkSlashIcon, 'BookmarkSlashIcon')
export const BookmarkSquareIcon = wrapIcon(RawBookmarkSquareIcon, 'BookmarkSquareIcon')
export const BriefcaseIcon = wrapIcon(RawBriefcaseIcon, 'BriefcaseIcon')
export const BugAntIcon = wrapIcon(RawBugAntIcon, 'BugAntIcon')
export const BuildingLibraryIcon = wrapIcon(RawBuildingLibraryIcon, 'BuildingLibraryIcon')
export const CalendarDaysIcon = wrapIcon(RawCalendarDaysIcon, 'CalendarDaysIcon')
export const ChartBarIcon = wrapIcon(RawChartBarIcon, 'ChartBarIcon')
export const ChatBubbleLeftEllipsisIcon = wrapIcon(RawChatBubbleLeftEllipsisIcon, 'ChatBubbleLeftEllipsisIcon')
export const ChatBubbleLeftRightIcon = wrapIcon(RawChatBubbleLeftRightIcon, 'ChatBubbleLeftRightIcon')
export const CheckBadgeIcon = wrapIcon(RawCheckBadgeIcon, 'CheckBadgeIcon')
export const CheckCircleIcon = wrapIcon(RawCheckCircleIcon, 'CheckCircleIcon')
export const CheckIcon = wrapIcon(RawCheckIcon, 'CheckIcon')
export const ChevronDownIcon = wrapIcon(RawChevronDownIcon, 'ChevronDownIcon')
export const ChevronLeftIcon = wrapIcon(RawChevronLeftIcon, 'ChevronLeftIcon')
export const ChevronRightIcon = wrapIcon(RawChevronRightIcon, 'ChevronRightIcon')
export const CircleStackIcon = wrapIcon(RawCircleStackIcon, 'CircleStackIcon')
export const ClipboardDocumentIcon = wrapIcon(RawClipboardDocumentIcon, 'ClipboardDocumentIcon')
export const ClipboardDocumentListIcon = wrapIcon(RawClipboardDocumentListIcon, 'ClipboardDocumentListIcon')
export const ClockIcon = wrapIcon(RawClockIcon, 'ClockIcon')
export const CloudArrowUpIcon = wrapIcon(RawCloudArrowUpIcon, 'CloudArrowUpIcon')
export const CodeBracketIcon = wrapIcon(RawCodeBracketIcon, 'CodeBracketIcon')
export const CodeBracketSquareIcon = wrapIcon(RawCodeBracketSquareIcon, 'CodeBracketSquareIcon')
export const Cog6ToothIcon = wrapIcon(RawCog6ToothIcon, 'Cog6ToothIcon')
export const CommandLineIcon = wrapIcon(RawCommandLineIcon, 'CommandLineIcon')
export const ComputerDesktopIcon = wrapIcon(RawComputerDesktopIcon, 'ComputerDesktopIcon')
export const CpuChipIcon = wrapIcon(RawCpuChipIcon, 'CpuChipIcon')
export const CubeIcon = wrapIcon(RawCubeIcon, 'CubeIcon')
export const CurrencyDollarIcon = wrapIcon(RawCurrencyDollarIcon, 'CurrencyDollarIcon')
export const CursorArrowRaysIcon = wrapIcon(RawCursorArrowRaysIcon, 'CursorArrowRaysIcon')
export const DocumentArrowUpIcon = wrapIcon(RawDocumentArrowUpIcon, 'DocumentArrowUpIcon')
export const DocumentCheckIcon = wrapIcon(RawDocumentCheckIcon, 'DocumentCheckIcon')
export const DocumentDuplicateIcon = wrapIcon(RawDocumentDuplicateIcon, 'DocumentDuplicateIcon')
export const DocumentIcon = wrapIcon(RawDocumentIcon, 'DocumentIcon')
export const DocumentMagnifyingGlassIcon = wrapIcon(RawDocumentMagnifyingGlassIcon, 'DocumentMagnifyingGlassIcon')
export const DocumentMinusIcon = wrapIcon(RawDocumentMinusIcon, 'DocumentMinusIcon')
export const DocumentPlusIcon = wrapIcon(RawDocumentPlusIcon, 'DocumentPlusIcon')
export const DocumentTextIcon = wrapIcon(RawDocumentTextIcon, 'DocumentTextIcon')
export const EllipsisHorizontalIcon = wrapIcon(RawEllipsisHorizontalIcon, 'EllipsisHorizontalIcon')
export const EnvelopeIcon = wrapIcon(RawEnvelopeIcon, 'EnvelopeIcon')
export const ExclamationCircleIcon = wrapIcon(RawExclamationCircleIcon, 'ExclamationCircleIcon')
export const ExclamationTriangleIcon = wrapIcon(RawExclamationTriangleIcon, 'ExclamationTriangleIcon')
export const EyeIcon = wrapIcon(RawEyeIcon, 'EyeIcon')
export const EyeSlashIcon = wrapIcon(RawEyeSlashIcon, 'EyeSlashIcon')
export const FolderIcon = wrapIcon(RawFolderIcon, 'FolderIcon')
export const FolderOpenIcon = wrapIcon(RawFolderOpenIcon, 'FolderOpenIcon')
export const FolderPlusIcon = wrapIcon(RawFolderPlusIcon, 'FolderPlusIcon')
export const GlobeAltIcon = wrapIcon(RawGlobeAltIcon, 'GlobeAltIcon')
export const HashtagIcon = wrapIcon(RawHashtagIcon, 'HashtagIcon')
export const HeartIcon = wrapIcon(RawHeartIcon, 'HeartIcon')
export const InboxIcon = wrapIcon(RawInboxIcon, 'InboxIcon')
export const InformationCircleIcon = wrapIcon(RawInformationCircleIcon, 'InformationCircleIcon')
export const LanguageIcon = wrapIcon(RawLanguageIcon, 'LanguageIcon')
export const LightBulbIcon = wrapIcon(RawLightBulbIcon, 'LightBulbIcon')
export const LinkIcon = wrapIcon(RawLinkIcon, 'LinkIcon')
export const LinkSlashIcon = wrapIcon(RawLinkSlashIcon, 'LinkSlashIcon')
export const LockClosedIcon = wrapIcon(RawLockClosedIcon, 'LockClosedIcon')
export const MagnifyingGlassIcon = wrapIcon(RawMagnifyingGlassIcon, 'MagnifyingGlassIcon')
export const MinusCircleIcon = wrapIcon(RawMinusCircleIcon, 'MinusCircleIcon')
export const MinusIcon = wrapIcon(RawMinusIcon, 'MinusIcon')
export const NumberedListIcon = wrapIcon(RawNumberedListIcon, 'NumberedListIcon')
export const PaperAirplaneIcon = wrapIcon(RawPaperAirplaneIcon, 'PaperAirplaneIcon')
export const PauseCircleIcon = wrapIcon(RawPauseCircleIcon, 'PauseCircleIcon')
export const PencilIcon = wrapIcon(RawPencilIcon, 'PencilIcon')
export const PencilSquareIcon = wrapIcon(RawPencilSquareIcon, 'PencilSquareIcon')
export const PhotoIcon = wrapIcon(RawPhotoIcon, 'PhotoIcon')
export const PlayIcon = wrapIcon(RawPlayIcon, 'PlayIcon')
export const PlusIcon = wrapIcon(RawPlusIcon, 'PlusIcon')
export const PowerIcon = wrapIcon(RawPowerIcon, 'PowerIcon')
export const QuestionMarkCircleIcon = wrapIcon(RawQuestionMarkCircleIcon, 'QuestionMarkCircleIcon')
export const QueueListIcon = wrapIcon(RawQueueListIcon, 'QueueListIcon')
export const RocketLaunchIcon = wrapIcon(RawRocketLaunchIcon, 'RocketLaunchIcon')
export const ScissorsIcon = wrapIcon(RawScissorsIcon, 'ScissorsIcon')
export const ServerIcon = wrapIcon(RawServerIcon, 'ServerIcon')
export const ServerStackIcon = wrapIcon(RawServerStackIcon, 'ServerStackIcon')
export const ShareIcon = wrapIcon(RawShareIcon, 'ShareIcon')
export const ShieldCheckIcon = wrapIcon(RawShieldCheckIcon, 'ShieldCheckIcon')
export const ShieldExclamationIcon = wrapIcon(RawShieldExclamationIcon, 'ShieldExclamationIcon')
export const SignalIcon = wrapIcon(RawSignalIcon, 'SignalIcon')
export const SparklesIcon = wrapIcon(RawSparklesIcon, 'SparklesIcon')
export const Square2StackIcon = wrapIcon(RawSquare2StackIcon, 'Square2StackIcon')
export const Square3Stack3DIcon = wrapIcon(RawSquare3Stack3DIcon, 'Square3Stack3DIcon')
export const Squares2X2Icon = wrapIcon(RawSquares2X2Icon, 'Squares2X2Icon')
export const StarIcon = wrapIcon(RawStarIcon, 'StarIcon')
export const StopIcon = wrapIcon(RawStopIcon, 'StopIcon')
export const SwatchIcon = wrapIcon(RawSwatchIcon, 'SwatchIcon')
export const TableCellsIcon = wrapIcon(RawTableCellsIcon, 'TableCellsIcon')
export const TagIcon = wrapIcon(RawTagIcon, 'TagIcon')
export const TrashIcon = wrapIcon(RawTrashIcon, 'TrashIcon')
export const TvIcon = wrapIcon(RawTvIcon, 'TvIcon')
export const UserIcon = wrapIcon(RawUserIcon, 'UserIcon')
export const UsersIcon = wrapIcon(RawUsersIcon, 'UsersIcon')
export const VideoCameraIcon = wrapIcon(RawVideoCameraIcon, 'VideoCameraIcon')
export const WrenchIcon = wrapIcon(RawWrenchIcon, 'WrenchIcon')
export const WrenchScrewdriverIcon = wrapIcon(RawWrenchScrewdriverIcon, 'WrenchScrewdriverIcon')
export const XCircleIcon = wrapIcon(RawXCircleIcon, 'XCircleIcon')
export const XMarkIcon = wrapIcon(RawXMarkIcon, 'XMarkIcon')

// Custom Git domain icons in Heroicons 24/outline specifications
export const GitBranchIcon = wrapIcon(GitBranchIconComponent, 'GitBranchIcon')
export const GitPullRequestIcon = wrapIcon(GitPullRequestIconComponent, 'GitPullRequestIcon')
export const GitCommitIcon = wrapIcon(GitCommitIconComponent, 'GitCommitIcon')
export const GithubIcon = wrapIcon(GithubIconComponent, 'GithubIcon')

// Converged semantic mappings from previous Lucide variants
export const Activity = SignalIcon
export const AlertCircle = ExclamationCircleIcon
export const AlertTriangle = ExclamationTriangleIcon
export const Archive = ArchiveBoxIcon
export const ArrowDown = ArrowDownIcon
export const ArrowLeft = ArrowLeftIcon
export const ArrowRight = ArrowRightIcon
export const ArrowRightLeft = ArrowsRightLeftIcon
export const ArrowUpRight = ArrowTopRightOnSquareIcon
export const BarChart3 = ChartBarIcon
export const Bell = BellIcon
export const Book = BookOpenIcon
export const BookMarked = BookmarkSquareIcon
export const BookOpen = BookOpenIcon
export const Bot = CpuChipIcon
export const Box = CubeIcon
export const Boxes = CubeIcon
export const Braces = CodeBracketIcon
export const Brain = SparklesIcon
export const BrainCircuit = CpuChipIcon
export const Briefcase = BriefcaseIcon
export const Bug = BugAntIcon
export const CalendarDays = CalendarDaysIcon
export const Check = CheckIcon
export const CheckCheck = CheckCircleIcon
export const CheckCircle = CheckCircleIcon
export const CheckCircle2 = CheckCircleIcon
export const ChevronDown = ChevronDownIcon
export const ChevronLeft = ChevronLeftIcon
export const ChevronRight = ChevronRightIcon
export const Circle = MinusCircleIcon
export const CircleAlert = ExclamationCircleIcon
export const CircleCheckBig = CheckCircleIcon
export const CircleHelp = QuestionMarkCircleIcon
export const ClipboardList = ClipboardDocumentListIcon
export const Clock = ClockIcon
export const Clock3 = ClockIcon
export const CloudUpload = CloudArrowUpIcon
export const Code = CodeBracketIcon
export const Code2 = CodeBracketIcon
export const Copy = ClipboardDocumentIcon
export const Cpu = CpuChipIcon
export const Database = CircleStackIcon
export const DatabaseZap = CircleStackIcon
export const DollarSign = CurrencyDollarIcon
export const Dot = EllipsisHorizontalIcon
export const Download = ArrowDownTrayIcon
export const Edit3 = PencilSquareIcon
export const ExternalLink = ArrowTopRightOnSquareIcon
export const Eye = EyeIcon
export const EyeOff = EyeSlashIcon
export const File = DocumentIcon
export const FileArchive = ArchiveBoxIcon
export const FileCheck = DocumentCheckIcon
export const FileCode = CodeBracketSquareIcon
export const FileCode2 = CodeBracketSquareIcon
export const FileCog = DocumentIcon
export const FileDiff = DocumentDuplicateIcon
export const FileEdit = PencilSquareIcon
export const FileImage = PhotoIcon
export const FilePenLine = PencilSquareIcon
export const FilePlus = DocumentPlusIcon
export const FilePlus2 = DocumentPlusIcon
export const FileSearch = DocumentMagnifyingGlassIcon
export const FileSpreadsheet = TableCellsIcon
export const FileTerminal = CommandLineIcon
export const FileText = DocumentTextIcon
export const FileType = DocumentTextIcon
export const FileUp = DocumentArrowUpIcon
export const FileX = DocumentMinusIcon
export const Folder = FolderIcon
export const FolderCog = FolderIcon
export const FolderGit2 = FolderIcon
export const FolderKanban = FolderIcon
export const FolderOpen = FolderOpenIcon
export const FolderPlus = FolderPlusIcon
export const FolderRoot = FolderIcon
export const FolderTree = FolderIcon
export const GitBranch = GitBranchIcon
export const GitCommitHorizontal = GitCommitIcon
export const GitCompare = ArrowsRightLeftIcon
export const GitCompareArrows = ArrowsRightLeftIcon
export const GitFork = CodeBracketIcon
export const GitMerge = ArrowTrendingUpIcon
export const GitPullRequest = GitPullRequestIcon
export const Github = GithubIcon
export const Globe = GlobeAltIcon
export const Hammer = WrenchScrewdriverIcon
export const Hash = HashtagIcon
export const History = ClockIcon
export const Inbox = InboxIcon
export const Info = InformationCircleIcon
export const Languages = LanguageIcon
export const Laptop = ComputerDesktopIcon
export const Layers = Square2StackIcon
export const LayoutDashboard = Squares2X2Icon
export const LayoutGrid = Squares2X2Icon
export const LibraryBig = BuildingLibraryIcon
export const Lightbulb = LightBulbIcon
export const Link = LinkIcon
export const Link2 = LinkIcon
export const Link2Off = LinkSlashIcon
export const ListChecks = QueueListIcon
export const ListOrdered = NumberedListIcon
export const Loader2 = ArrowPathIcon
export const LoaderCircle = ArrowPathIcon
export const Lock = LockClosedIcon
export const LockKeyhole = LockClosedIcon
export const LogIn = ArrowRightOnRectangleIcon
export const Mail = EnvelopeIcon
export const Maximize2 = ArrowsPointingOutIcon
export const MessageCircle = ChatBubbleLeftRightIcon
export const MessageSquare = ChatBubbleLeftRightIcon
export const MessageSquareDiff = ChatBubbleLeftRightIcon
export const MessageSquarePlus = ChatBubbleLeftRightIcon
export const MessageSquareText = ChatBubbleLeftEllipsisIcon
export const MessagesSquare = ChatBubbleLeftRightIcon
export const Minimize2 = ArrowsPointingInIcon
export const Minus = MinusIcon
export const Monitor = TvIcon
export const MonitorCog = ComputerDesktopIcon
export const MoreHorizontal = EllipsisHorizontalIcon
export const MousePointer2 = CursorArrowRaysIcon
export const Network = ShareIcon
export const OctagonPause = PauseCircleIcon
export const Package = CubeIcon
export const Palette = SwatchIcon
export const PanelLeftClose = ChevronLeftIcon
export const PanelLeftOpen = ChevronRightIcon
export const Pencil = PencilSquareIcon
export const PencilLine = PencilIcon
export const Pin = BookmarkIcon
export const PinOff = BookmarkSlashIcon
export const Play = PlayIcon
export const Plug = PowerIcon
export const PlugZap = BoltIcon
export const Plus = PlusIcon
export const RefreshCw = ArrowPathIcon
export const Repeat = ArrowPathIcon
export const Rocket = RocketLaunchIcon
export const RotateCcw = ArrowUturnLeftIcon
export const RotateCw = ArrowPathIcon
export const Save = ArrowDownOnSquareIcon
export const Scissors = ScissorsIcon
export const ScrollText = DocumentTextIcon
export const Search = MagnifyingGlassIcon
export const SearchX = MagnifyingGlassIcon
export const Send = PaperAirplaneIcon
export const SendHorizonal = PaperAirplaneIcon
export const SendHorizontal = PaperAirplaneIcon
export const Server = ServerIcon
export const ServerCog = ServerStackIcon
export const Settings = Cog6ToothIcon
export const Settings2 = Cog6ToothIcon
export const Share2 = ShareIcon
export const Shield = ShieldCheckIcon
export const ShieldAlert = ShieldExclamationIcon
export const ShieldCheck = ShieldCheckIcon
export const SlidersHorizontal = AdjustmentsHorizontalIcon
export const Sparkles = SparklesIcon
export const Square = StopIcon
export const Star = StarIcon
export const Stethoscope = BugAntIcon
export const Tag = TagIcon
export const Target = CheckCircleIcon
export const Terminal = CommandLineIcon
export const TerminalSquare = CommandLineIcon
export const TestTube = BeakerIcon
export const Trash2 = TrashIcon
export const TrendingUp = ArrowTrendingUpIcon
export const TriangleAlert = ExclamationTriangleIcon
export const Undo2 = ArrowUturnLeftIcon
export const Unlink = LinkSlashIcon
export const Upload = ArrowUpTrayIcon
export const UploadCloud = CloudArrowUpIcon
export const User = UserIcon
export const UserCheck = UserIcon
export const UserRound = UserIcon
export const Users = UsersIcon
export const Verified = CheckBadgeIcon
export const Video = VideoCameraIcon
export const Workflow = Square3Stack3DIcon
export const Wrench = WrenchIcon
export const X = XMarkIcon
export const XCircle = XCircleIcon
export const Zap = BoltIcon
